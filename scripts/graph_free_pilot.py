#!/usr/bin/env python3
"""Run a small Uniswap v2/v3 GraphQL pilot using only a Graph API key.

The script reads candidate tokens from the already-frozen Week 1 sample. It
does not read the project archive credentials and does not claim that labels
are publication-ready; every query and pagination boundary is archived.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.week1_audit import (  # noqa: E402
    HttpClient,
    RawArchive,
    RequestFailure,
    read_jsonl,
    redact_url,
    utc_now,
    write_json,
    write_jsonl,
)


PAGE_SIZE = 1000
PRIMARY_OBSERVATION_DAYS = 7
OBSERVATION_DAYS = PRIMARY_OBSERVATION_DAYS
FOLLOWUP_DAYS = 90
VOLUME_THRESHOLD_USD = Decimal("1000")
LEGACY_OBSERVATION_SWAPS = 10
GRAPH_ENDPOINT = "https://gateway.thegraph.com/api/{api_key}/subgraphs/id/{subgraph_id}"
SUBGRAPHS = {
    "uniswap_v2": "A3Np3RQbaBA6oKJgiwDJeo5T3zrYfGHPWFYayMwtNDum",
    "uniswap_v3": "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV",
}


class GraphQueryFailure(RequestFailure):
    """A GraphQL response contained errors or no usable data."""


def unix_time(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        return None


def as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def safe_graph_error(errors: Any, api_key: str) -> str:
    text = json.dumps(errors, sort_keys=True, ensure_ascii=True)
    return text.replace(api_key, "REDACTED")[:500]


class GraphClient:
    def __init__(self, http: HttpClient, api_key: str) -> None:
        self.http = http
        self.api_key = api_key

    def query(self, protocol: str, query: str) -> tuple[dict[str, Any], str]:
        endpoint = GRAPH_ENDPOINT.format(api_key=self.api_key, subgraph_id=SUBGRAPHS[protocol])
        try:
            payload, request_id = self.http.request(
                "POST",
                endpoint,
                body={"query": query},
                archive_url=redact_url(endpoint, secrets=(self.api_key,)),
            )
        except RequestFailure as exc:
            raise GraphQueryFailure(str(exc)) from exc
        if not isinstance(payload, dict):
            raise GraphQueryFailure(f"expected GraphQL object, got {type(payload).__name__}")
        if payload.get("errors"):
            raise GraphQueryFailure(safe_graph_error(payload["errors"], self.api_key))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise GraphQueryFailure("GraphQL response did not contain an object in data")
        return data, request_id


def v2_pool_query(token: str, side: str, skip: int) -> str:
    return f"""
    query {{
      pairs(
        first: {PAGE_SIZE}, skip: {skip}
        where: {{ {side}: \"{token}\" }}
      ) {{
        id createdAtTimestamp createdAtBlockNumber
        token0 {{ id symbol }}
        token1 {{ id symbol }}
      }}
    }}
    """


def v3_pool_query(token: str, side: str, skip: int) -> str:
    return f"""
    query {{
      pools(
        first: {PAGE_SIZE}, skip: {skip}
        where: {{ {side}: \"{token}\" }}
      ) {{
        id createdAtTimestamp createdAtBlockNumber
        token0 {{ id symbol }}
        token1 {{ id symbol }}
      }}
    }}
    """


def event_query(protocol: str, pools: list[str], skip: int) -> str:
    pool_filter = "pair_in" if protocol == "uniswap_v2" else "pool_in"
    relation = "pair" if protocol == "uniswap_v2" else "pool"
    pool_values = ", ".join(json.dumps(pool) for pool in sorted(set(pools)))
    common = f"""
      id timestamp logIndex
      transaction {{ id blockNumber timestamp }}
      {relation} {{ id }}
    """
    swap_fields = f"""
      {common}
      amountUSD
    """
    return f"""
    query {{
      swaps(
        first: {PAGE_SIZE}, skip: {skip}
        orderBy: timestamp, orderDirection: asc
        where: {{ {pool_filter}: [{pool_values}] }}
      ) {{ {swap_fields} }}
      mints(
        first: {PAGE_SIZE}, skip: {skip}
        orderBy: timestamp, orderDirection: asc
        where: {{ {pool_filter}: [{pool_values}] }}
      ) {{ {common} }}
      burns(
        first: {PAGE_SIZE}, skip: {skip}
        orderBy: timestamp, orderDirection: asc
        where: {{ {pool_filter}: [{pool_values}] }}
      ) {{ {common} }}
    }}
    """


def normalize_pool(protocol: str, row: dict[str, Any]) -> dict[str, Any] | None:
    pool_address = str(row.get("id") or "").lower()
    token0 = row.get("token0") or {}
    token1 = row.get("token1") or {}
    creation_block = as_int(row.get("createdAtBlockNumber"))
    creation_timestamp = unix_time(row.get("createdAtTimestamp"))
    if not pool_address or not token0.get("id") or not token1.get("id"):
        return None
    return {
        "pool_address": pool_address,
        "protocol": protocol,
        "token0": str(token0["id"]).lower(),
        "token1": str(token1["id"]).lower(),
        "token0_symbol": token0.get("symbol"),
        "token1_symbol": token1.get("symbol"),
        "creation_block": creation_block,
        "creation_timestamp": creation_timestamp,
        "source": "the_graph",
    }


def fetch_pools(
    client: GraphClient,
    token: str,
    protocol: str,
    *,
    max_pages: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    request_ids: list[str] = []
    failures: list[str] = []
    page_count = 0
    complete = True
    page_builder = v2_pool_query if protocol == "uniswap_v2" else v3_pool_query
    page_fetches = [("token0", page_builder), ("token1", page_builder)]

    for side, query_builder in page_fetches:
        skip = 0
        while True:
            page_count += 1
            if page_count > max_pages:
                complete = False
                failures.append("pool_page_limit_reached")
                break
            query = query_builder(token, side, skip)
            try:
                data, request_id = client.query(protocol, query)
            except GraphQueryFailure as exc:
                complete = False
                failures.append(str(exc))
                break
            request_ids.append(request_id)
            page = data.get("pairs" if protocol == "uniswap_v2" else "pools") or []
            for row in page:
                pool = normalize_pool(protocol, row)
                if pool:
                    rows[pool["pool_address"]] = pool
            if len(page) < PAGE_SIZE:
                break
            skip += PAGE_SIZE
        if not complete:
            break

    return sorted(rows.values(), key=lambda row: (row["creation_block"] or 0, row["pool_address"])), {
        "token_address": token,
        "protocol": protocol,
        "pages": page_count,
        "request_ids": request_ids,
        "pool_count": len(rows),
        "complete": complete,
        "failure": ";".join(failures) if failures else None,
    }


def normalize_event(
    protocol: str,
    event_type: str,
    row: dict[str, Any],
    request_id: str,
    token_address: str,
) -> dict[str, Any] | None:
    relation = row.get("pair") if protocol == "uniswap_v2" else row.get("pool")
    relation = relation or {}
    transaction = row.get("transaction") or {}
    event_id = str(row.get("id") or "")
    timestamp = unix_time(row.get("timestamp") or transaction.get("timestamp"))
    block_number = as_int(transaction.get("blockNumber"))
    log_index = as_int(row.get("logIndex"))
    if not event_id or not relation.get("id") or not timestamp or block_number is None:
        return None
    transaction_hash = str(transaction.get("id") or event_id.split("#", 1)[0])
    return {
        "token_address": token_address,
        "protocol": protocol,
        "pool_address": str(relation["id"]).lower(),
        "event_type": event_type,
        "event_id": event_id,
        "transaction_hash": transaction_hash,
        "log_index": log_index if log_index is not None else 0,
        "block_number": block_number,
        "block_timestamp": timestamp,
        "amount_usd": str(row["amountUSD"]) if event_type == "swap" and row.get("amountUSD") is not None else None,
        "source_request_id": request_id,
        "source": "the_graph",
    }


def fetch_activity(
    client: GraphClient,
    token: str,
    protocol: str,
    pools: list[dict[str, Any]],
    *,
    max_pages: int,
    pool_group_size: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, str | None]:
    pool_addresses = [row["pool_address"] for row in pools]
    if not pool_addresses:
        return [], [], True, None
    if len(pool_addresses) > pool_group_size:
        merged_events: dict[str, dict[str, Any]] = {}
        merged_coverage: list[dict[str, Any]] = []
        failures: list[str] = []
        complete = True
        for start in range(0, len(pools), pool_group_size):
            group_events, group_coverage, group_complete, group_failure = fetch_activity(
                client,
                token,
                protocol,
                pools[start : start + pool_group_size],
                max_pages=max_pages,
                pool_group_size=pool_group_size,
            )
            merged_events.update({row["event_id"]: row for row in group_events})
            merged_coverage.extend(group_coverage)
            complete = complete and group_complete
            if group_failure:
                failures.append(group_failure)
        return (
            sorted(merged_events.values(), key=lambda row: (row["block_number"], row["log_index"], row["event_id"])),
            merged_coverage,
            complete,
            ";".join(failures) if failures else None,
        )
    events: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []
    request_ids: list[str] = []
    skip = 0
    pages = 0
    complete = True
    failure: str | None = None
    while True:
        pages += 1
        if pages > max_pages:
            complete = False
            failure = "activity_page_limit_reached"
            break
        try:
            data, request_id = client.query(protocol, event_query(protocol, pool_addresses, skip))
        except GraphQueryFailure as exc:
            complete = False
            failure = str(exc)
            break
        request_ids.append(request_id)
        page_counts: list[int] = []
        for event_type in ("swap", "mint", "burn"):
            source_rows = data.get(f"{event_type}s") or []
            page_counts.append(len(source_rows))
            for row in source_rows:
                normalized = normalize_event(protocol, event_type, row, request_id, token)
                if normalized:
                    events[normalized["event_id"]] = normalized
                else:
                    complete = False
                    failure = failure or "event_missing_required_field"
        if max(page_counts, default=0) < PAGE_SIZE:
            break
        skip += PAGE_SIZE
    for pool in pools:
        pool_events = [row for row in events.values() if row["pool_address"] == pool["pool_address"]]
        coverage.append(
            {
                "token_address": token,
                "pool_address": pool["pool_address"],
                "protocol": protocol,
                "pages": pages,
                "request_ids": request_ids,
                "event_count": len(pool_events),
                "complete": complete,
                "failure": failure,
            }
        )
    return sorted(events.values(), key=lambda row: (row["block_number"], row["log_index"], row["event_id"])), coverage, complete, failure


def select_candidates(rows: list[dict[str, Any]], pilot_size: int) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (int(row.get("sampling_rank", 10**9)), row["token_address"]))
    selected: list[dict[str, Any]] = []
    periods = sorted({row.get("launch_period") for row in ordered if row.get("launch_period")})
    for period in periods:
        match = next((row for row in ordered if row.get("launch_period") == period), None)
        if match and match not in selected and len(selected) < pilot_size:
            selected.append(match)
    for row in ordered:
        if row not in selected and len(selected) < pilot_size:
            selected.append(row)
    return selected


def entity_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "token_address": candidate["token_address"].lower(),
        "launch_period": candidate.get("launch_period"),
        "sampling_rank": candidate.get("sampling_rank"),
        "first_observed_block": candidate.get("first_observed_block"),
        "first_observed_timestamp": candidate.get("first_observed_timestamp"),
        "pools": [],
        "pool_scope_complete": False,
        "pool_scope_reason": None,
        "activity_collected": False,
        "activity_collection_reason": None,
    }


def event_time(row: dict[str, Any]) -> datetime | None:
    value = row.get("block_timestamp")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def outcome_for_entity(
    entity: dict[str, Any],
    events: list[dict[str, Any]],
    now: datetime,
    *,
    observation_days: int = OBSERVATION_DAYS,
    followup_days: int = FOLLOWUP_DAYS,
    volume_threshold_usd: Decimal = VOLUME_THRESHOLD_USD,
) -> dict[str, Any]:
    ordered = sorted(events, key=lambda row: (row["block_number"], row["log_index"], row["event_id"]))
    swaps = [row for row in ordered if row["event_type"] == "swap"]
    candidate_times = [
        parsed
        for pool in entity.get("pools", [])
        for parsed in [event_time({"block_timestamp": pool.get("creation_timestamp")})]
        if parsed is not None
    ]
    candidate_times.extend(parsed for row in ordered if (parsed := event_time(row)) is not None)
    t0 = min(candidate_times) if candidate_times else None
    result: dict[str, Any] = {
        "token_address": entity["token_address"],
        "launch_period": entity["launch_period"],
        "label_definition": "low_volume_dead",
        "t0": iso_time(t0) if t0 else None,
        "observation_days": observation_days,
        "followup_days": followup_days,
        "volume_threshold_usd": format(volume_threshold_usd, "f"),
        "volume_source": "the_graph_swap_amountUSD",
        "observation_swap_count": 0,
        "total_swap_count": len(swaps),
        "pool_count": len(entity["pools"]),
        "pool_scope_complete": entity["pool_scope_complete"],
        "activity_collected": entity["activity_collected"],
        "censoring_reason": None,
        "exclusion_reason": None,
        "evidence_event_ids": [row["event_id"] for row in ordered[:10]],
    }
    if not entity["pool_scope_complete"]:
        result["label"] = "censored"
        result["censoring_reason"] = f"pool_scope_incomplete:{entity['pool_scope_reason']}"
        return result
    if not entity["activity_collected"]:
        result["label"] = "censored"
        result["censoring_reason"] = f"activity_retrieval_incomplete:{entity['activity_collection_reason']}"
        return result
    if t0 is None:
        result["label"] = "censored"
        result["censoring_reason"] = "no_launch_or_activity_timestamp"
        return result
    cutoff = t0 + timedelta(days=observation_days)
    followup_end = cutoff + timedelta(days=followup_days)
    result["cutoff"] = iso_time(cutoff)
    result["followup_end"] = iso_time(followup_end)
    observation_swaps = [
        row
        for row in swaps
        if (timestamp := event_time(row)) is not None and t0 <= timestamp <= cutoff
    ]
    result["observation_swap_count"] = len(observation_swaps)
    result["cutoff_event_id"] = observation_swaps[-1]["event_id"] if observation_swaps else None
    if followup_end > now:
        result["label"] = "censored"
        result["censoring_reason"] = "followup_not_complete_at_retrieval"
        return result
    followup_swaps = [
        row
        for row in swaps
        if (timestamp := event_time(row)) is not None and cutoff < timestamp <= followup_end
    ]
    result["followup_swap_count"] = len(followup_swaps)
    result["followup_evidence_event_ids"] = [row["event_id"] for row in followup_swaps[:50]]
    missing_volume = [
        row["event_id"]
        for row in followup_swaps
        if (amount_usd := as_decimal(row.get("amount_usd"))) is None or amount_usd <= 0
    ]
    if missing_volume:
        result["label"] = "censored"
        result["censoring_reason"] = "missing_or_nonpositive_swap_usd"
        result["missing_volume_event_ids"] = missing_volume[:50]
        result["volume_complete"] = False
        return result
    volume_usd = sum(
        (as_decimal(row.get("amount_usd")) or Decimal("0") for row in followup_swaps),
        Decimal("0"),
    )
    result["followup_volume_usd"] = format(volume_usd, "f")
    result["volume_complete"] = True
    result["label"] = "low_volume_dead" if volume_usd < volume_threshold_usd else "continued_activity"
    return result


def zero_activity_outcome_for_entity(
    entity: dict[str, Any],
    events: list[dict[str, Any]],
    now: datetime,
    *,
    followup_days: int = FOLLOWUP_DAYS,
    observation_swaps: int = LEGACY_OBSERVATION_SWAPS,
) -> dict[str, Any]:
    """Preserve the former zero-activity rule as a sensitivity label."""
    ordered = sorted(events, key=lambda row: (row["block_number"], row["log_index"], row["event_id"]))
    qualifying = [row for row in ordered if row["event_type"] in {"swap", "mint", "burn"}]
    swaps = [row for row in ordered if row["event_type"] == "swap"]
    result: dict[str, Any] = {
        "token_address": entity["token_address"],
        "launch_period": entity["launch_period"],
        "label_definition": "zero_activity_after_tenth_swap",
        "t0": qualifying[0]["block_timestamp"] if qualifying else None,
        "observation_swap_count": len(swaps),
        "pool_count": len(entity["pools"]),
        "pool_scope_complete": entity["pool_scope_complete"],
        "activity_collected": entity["activity_collected"],
        "censoring_reason": None,
        "exclusion_reason": None,
        "evidence_event_ids": [row["event_id"] for row in ordered[:10]],
    }
    if not entity["pool_scope_complete"]:
        result["label"] = "censored"
        result["censoring_reason"] = f"pool_scope_incomplete:{entity['pool_scope_reason']}"
        return result
    if not entity["activity_collected"]:
        result["label"] = "censored"
        result["censoring_reason"] = f"activity_retrieval_incomplete:{entity['activity_collection_reason']}"
        return result
    if len(swaps) < observation_swaps:
        result["label"] = "excluded_early_death"
        result["exclusion_reason"] = "fewer_than_10_swaps_in_retrieved_history"
        return result
    cutoff = event_time(swaps[observation_swaps - 1])
    if cutoff is None:
        result["label"] = "censored"
        result["censoring_reason"] = "missing_cutoff_timestamp"
        return result
    followup_end = cutoff + timedelta(days=followup_days)
    result["cutoff"] = iso_time(cutoff)
    result["followup_end"] = iso_time(followup_end)
    result["cutoff_event_id"] = swaps[observation_swaps - 1]["event_id"]
    if followup_end > now:
        result["label"] = "censored"
        result["censoring_reason"] = "followup_not_complete_at_retrieval"
        return result
    followup = [
        row
        for row in qualifying
        if (timestamp := event_time(row)) is not None and cutoff < timestamp <= followup_end
    ]
    result["followup_event_count"] = len(followup)
    result["followup_evidence_event_ids"] = [row["event_id"] for row in followup[:50]]
    result["label"] = "continued_activity" if followup else "failure"
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    output = (project_root / args.output).resolve()
    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"{args.api_key_env} is not set; load only that variable before running")
    candidates = select_candidates(read_jsonl(project_root / args.candidates), args.pilot_size)
    archive = RawArchive(output)
    http = HttpClient(archive, user_agent="week1-graph-free-pilot/0.1", interval=args.request_interval, timeout=args.timeout)
    client = GraphClient(http, api_key)
    entities: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    pool_coverage: list[dict[str, Any]] = []
    activity_coverage: list[dict[str, Any]] = []
    for candidate in candidates:
        entity = entity_from_candidate(candidate)
        token = entity["token_address"]
        token_pools: dict[tuple[str, str], dict[str, Any]] = {}
        scope_complete = True
        scope_failures: list[str] = []
        for protocol in SUBGRAPHS:
            pools, coverage = fetch_pools(client, token, protocol, max_pages=args.max_pool_pages)
            pool_coverage.append(coverage)
            scope_complete = scope_complete and coverage["complete"]
            if coverage["failure"]:
                scope_failures.append(f"{protocol}:{coverage['failure']}")
            for pool in pools:
                token_pools[(protocol, pool["pool_address"])] = pool
        entity["pools"] = sorted(token_pools.values(), key=lambda row: (row["creation_block"] or 0, row["pool_address"]))
        entity["pool_scope_complete"] = scope_complete
        entity["pool_scope_reason"] = ";".join(scope_failures) if scope_failures else "graph_pool_queries_complete"
        token_events: list[dict[str, Any]] = []
        activity_complete = True
        activity_failures: list[str] = []
        for protocol in SUBGRAPHS:
            protocol_pools = [pool for pool in entity["pools"] if pool["protocol"] == protocol]
            events, coverage, complete, failure = fetch_activity(
                client,
                token,
                protocol,
                protocol_pools,
                max_pages=args.max_activity_pages,
                pool_group_size=args.activity_pool_group_size,
            )
            token_events.extend(events)
            activity_coverage.extend(coverage)
            activity_complete = activity_complete and complete
            if failure:
                activity_failures.append(f"{protocol}:{failure}")
        entity["activity_collected"] = activity_complete
        entity["activity_collection_reason"] = ";".join(activity_failures) if activity_failures else "graph_activity_queries_complete"
        entities.append(entity)
        all_events.extend(token_events)
    write_jsonl(output / "token_entities.jsonl", entities)
    write_jsonl(output / "events.jsonl", sorted(all_events, key=lambda row: (row["token_address"], row["block_number"], row["log_index"])))
    write_jsonl(output / "manifests" / "pool_coverage.jsonl", pool_coverage)
    write_jsonl(output / "manifests" / "activity_coverage.jsonl", activity_coverage)

    events_by_token: dict[str, list[dict[str, Any]]] = {entity["token_address"]: [] for entity in entities}
    for event in all_events:
        events_by_token.setdefault(event["token_address"], []).append(event)
    now = datetime.now(UTC)
    volume_threshold_usd = as_decimal(args.volume_threshold_usd)
    if volume_threshold_usd is None:
        raise SystemExit("--volume-threshold-usd must be a finite non-negative decimal")
    outcomes = [
        outcome_for_entity(
            entity,
            events_by_token[entity["token_address"]],
            now,
            observation_days=args.observation_days,
            followup_days=args.followup_days,
            volume_threshold_usd=volume_threshold_usd,
        )
        for entity in entities
    ]
    sensitivity_outcomes = [
        zero_activity_outcome_for_entity(
            entity,
            events_by_token[entity["token_address"]],
            now,
            followup_days=args.sensitivity_followup_days,
            observation_swaps=args.sensitivity_observation_swaps,
        )
        for entity in entities
    ]
    write_jsonl(output / "outcomes.jsonl", outcomes)
    write_jsonl(output / "sensitivity_zero_activity_outcomes.jsonl", sensitivity_outcomes)
    report = {
        "report_version": "graph-free-pilot-0.2",
        "retrieved_at": utc_now(),
        "source": {
            "name": "The Graph gateway, official Uniswap v2 and v3 subgraphs",
            "endpoint": redact_url(GRAPH_ENDPOINT.format(api_key=api_key, subgraph_id="<subgraph>"), secrets=(api_key,)),
            "api_key_env": args.api_key_env,
            "terms_status": "not_audited",
        },
        "selection": {
            "candidates_file": args.candidates,
            "selection_rule": "one lowest sampling-rank token per launch period, then lowest rank",
            "pilot_size": args.pilot_size,
            "selected_tokens": len(entities),
            "launch_periods": dict(Counter(entity["launch_period"] for entity in entities)),
        },
        "counts": {
            "pool_records": sum(len(entity["pools"]) for entity in entities),
            "activity_events": len(all_events),
            "outcomes": len(outcomes),
            "outcome_counts": dict(Counter(row["label"] for row in outcomes)),
            "sensitivity_outcome_counts": dict(Counter(row["label"] for row in sensitivity_outcomes)),
            "swap_events_with_usd": sum(
                row["event_type"] == "swap" and row.get("amount_usd") is not None for row in all_events
            ),
            "raw_request_rows": len(read_jsonl(output / "manifests" / "request_log.jsonl")),
        },
        "coverage": {
            "pool_queries_complete": all(row["complete"] for row in pool_coverage),
            "activity_queries_complete": all(row["complete"] for row in activity_coverage),
            "entities_with_complete_pool_scope": sum(row["pool_scope_complete"] for row in entities),
            "entities_with_complete_activity": sum(row["activity_collected"] for row in entities),
        },
        "labels": {
            "primary": {
                "name": "low_volume_dead",
                "observation_days": args.observation_days,
                "followup_days": args.followup_days,
                "threshold_usd": args.volume_threshold_usd,
                "volume_event_type": "swap",
                "volume_field": "Swap.amountUSD",
            },
            "sensitivity": {
                "name": "zero_activity_after_tenth_swap",
                "observation_swaps": args.sensitivity_observation_swaps,
                "followup_days": args.sensitivity_followup_days,
            },
        },
        "labels_ready": False,
        "go_no_go": False,
        "decision": "Free GraphQL pilot only; do not start modelling or publish labels until source terms, completeness, censoring, USD valuation, and support are audited.",
    }
    write_json(output / "graph_free_pilot_report.json", report)
    return report


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--candidates", default="data/week1_pilot/token_entities.jsonl")
    parser.add_argument("--output", default="data/week1_graph_free_pilot")
    parser.add_argument("--pilot-size", type=int, default=5)
    parser.add_argument("--api-key-env", default="THE_GRAPH_API_KEY")
    parser.add_argument("--max-pool-pages", type=int, default=20)
    parser.add_argument("--max-activity-pages", type=int, default=20)
    parser.add_argument("--activity-pool-group-size", type=int, default=2)
    parser.add_argument("--observation-days", type=int, default=OBSERVATION_DAYS)
    parser.add_argument("--followup-days", type=int, default=FOLLOWUP_DAYS)
    parser.add_argument("--volume-threshold-usd", default="1000")
    parser.add_argument("--sensitivity-observation-swaps", type=int, default=LEGACY_OBSERVATION_SWAPS)
    parser.add_argument("--sensitivity-followup-days", type=int, default=FOLLOWUP_DAYS)
    parser.add_argument("--request-interval", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


if __name__ == "__main__":
    parsed_args = make_parser().parse_args()
    result = run(parsed_args)
    print(json.dumps({"output": str((Path(parsed_args.project_root) / parsed_args.output).resolve()), "labels_ready": result["labels_ready"], "counts": result["counts"]}, indent=2, sort_keys=True))
