#!/usr/bin/env python3
"""Collect only the primary 90-day follow-up for already-screened tokens.

This collector deliberately reuses the stored pool scope and the cutoff
timestamps from a label-blind screening run. It never queries pool discovery,
so a renewed Graph quota can be spent on the missing follow-up window. Every
token has a durable checkpoint; failed requests remain censored and are
retried on the next invocation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.graph_free_pilot import (  # noqa: E402
    GraphClient,
    GraphQueryFailure,
    HttpClient,
    PAGE_SIZE,
    RawArchive,
    SUBGRAPHS,
    as_decimal,
    normalize_event,
    read_jsonl,
    redact_url,
    utc_now,
    write_json,
    write_jsonl,
)


FOLLOWUP_DAYS = 90
VOLUME_THRESHOLD_USD = Decimal("1000")
EVENT_TYPES = ("swap", "mint", "burn")


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def token_of(row: dict[str, Any]) -> str:
    return str(row.get("token_address") or "").lower()


def event_key(row: dict[str, Any]) -> tuple[str, str, int]:
    token = token_of(row)
    transaction_hash = str(row.get("transaction_hash") or row.get("event_id") or "").lower()
    try:
        log_index = int(row.get("log_index") or 0)
    except (TypeError, ValueError):
        log_index = 0
    return token, transaction_hash, log_index


def scope_fingerprint(entity: dict[str, Any]) -> str:
    values = [
        f"{str(pool.get('protocol') or '').lower()}:{str(pool.get('pool_address') or '').lower()}"
        for pool in entity.get("pools") or []
    ]
    return hashlib.sha256("|".join(sorted(values)).encode("utf-8")).hexdigest()


def followup_event_query(
    protocol: str,
    pools: list[str],
    start_timestamp: datetime,
    end_timestamp: datetime,
    skip: int,
) -> str:
    """Build a Graph query bounded strictly to the follow-up interval."""
    pool_filter = "pair_in" if protocol == "uniswap_v2" else "pool_in"
    relation = "pair" if protocol == "uniswap_v2" else "pool"
    pool_values = ", ".join(json.dumps(pool) for pool in sorted(set(pools)))
    start_epoch = int(start_timestamp.timestamp()) + 1
    end_epoch = int(end_timestamp.timestamp())
    time_filter = (
        f"{pool_filter}: [{pool_values}], "
        f"timestamp_gte: {start_epoch}, timestamp_lte: {end_epoch}"
    )
    common = f"""
      id timestamp logIndex
      transaction {{ id blockNumber timestamp }}
      {relation} {{ id }}
    """
    return f"""
    query {{
      swaps(
        first: {PAGE_SIZE}, skip: {skip}
        orderBy: timestamp, orderDirection: asc
        where: {{ {time_filter} }}
      ) {{ {common} amountUSD }}
      mints(
        first: {PAGE_SIZE}, skip: {skip}
        orderBy: timestamp, orderDirection: asc
        where: {{ {time_filter} }}
      ) {{ {common} }}
      burns(
        first: {PAGE_SIZE}, skip: {skip}
        orderBy: timestamp, orderDirection: asc
        where: {{ {time_filter} }}
      ) {{ {common} }}
    }}
    """


def fetch_followup_activity(
    client: GraphClient,
    token: str,
    protocol: str,
    pools: list[dict[str, Any]],
    *,
    start_timestamp: datetime,
    end_timestamp: datetime,
    max_pages: int,
    pool_group_size: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, str | None]:
    """Fetch one protocol's follow-up interval without pool discovery."""
    if not pools:
        return [], [], True, None

    all_events: dict[tuple[str, str], dict[str, Any]] = {}
    all_coverage: list[dict[str, Any]] = []
    failures: list[str] = []
    complete = True

    for start in range(0, len(pools), pool_group_size):
        group = pools[start : start + pool_group_size]
        pool_addresses = [str(row["pool_address"]).lower() for row in group]
        request_ids: list[str] = []
        page_count = 0
        group_complete = True
        group_failure: str | None = None
        skip = 0
        while True:
            page_count += 1
            if page_count > max_pages:
                group_complete = False
                group_failure = "followup_page_limit_reached"
                break
            try:
                data, request_id = client.query(
                    protocol,
                    followup_event_query(
                        protocol,
                        pool_addresses,
                        start_timestamp,
                        end_timestamp,
                        skip,
                    ),
                )
            except GraphQueryFailure as exc:
                group_complete = False
                group_failure = str(exc)
                break
            request_ids.append(request_id)
            page_counts: list[int] = []
            for event_type in EVENT_TYPES:
                source_rows = data.get(f"{event_type}s") or []
                page_counts.append(len(source_rows))
                for row in source_rows:
                    normalized = normalize_event(protocol, event_type, row, request_id, token)
                    if normalized:
                        all_events[(event_type, normalized["event_id"])] = normalized
                    else:
                        group_complete = False
                        group_failure = group_failure or "event_missing_required_field"
            if max(page_counts, default=0) < PAGE_SIZE:
                break
            skip += PAGE_SIZE

        for pool in group:
            pool_address = str(pool["pool_address"]).lower()
            pool_events = [
                row for row in all_events.values() if row["pool_address"] == pool_address
            ]
            all_coverage.append(
                {
                    "token_address": token,
                    "pool_address": pool_address,
                    "protocol": protocol,
                    "followup_start": iso_time(start_timestamp),
                    "followup_end": iso_time(end_timestamp),
                    "pages": page_count,
                    "request_ids": request_ids,
                    "event_count": len(pool_events),
                    "complete": group_complete,
                    "failure": group_failure,
                }
            )
        complete = complete and group_complete
        if group_failure:
            failures.append(group_failure)

    events = sorted(
        all_events.values(),
        key=lambda row: (
            row["block_number"],
            row["log_index"],
            row["event_type"],
            row["event_id"],
        ),
    )
    return events, all_coverage, complete, ";".join(failures) if failures else None


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")


def load_last_checkpoints(path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return latest
    for row in read_jsonl(path):
        token = token_of(row)
        if token:
            latest[token] = row
    return latest


def load_existing_events(
    path: Path,
    windows: dict[str, tuple[datetime | None, datetime | None]],
) -> tuple[set[tuple[str, str, int]], dict[str, dict[str, Any]]]:
    seen: set[tuple[str, str, int]] = set()
    aggregates: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return seen, aggregates
    for row in read_jsonl(path):
        token = token_of(row)
        start, end = windows.get(token, (None, None))
        timestamp = parse_time(row.get("block_timestamp"))
        if not token or timestamp is None or start is None or end is None:
            continue
        if not start < timestamp <= end:
            continue
        key = event_key(row)
        if key in seen:
            continue
        seen.add(key)
        add_to_aggregate(aggregates, row)
    return seen, aggregates


def add_to_aggregate(aggregates: dict[str, dict[str, Any]], row: dict[str, Any]) -> None:
    token = token_of(row)
    current = aggregates.setdefault(
        token,
        {
            "event_count": 0,
            "swap_count": 0,
            "volume_usd": Decimal("0"),
            "missing_volume_event_ids": [],
            "evidence_event_ids": [],
        },
    )
    current["event_count"] += 1
    event_id = str(row.get("event_id") or "")
    if event_id and len(current["evidence_event_ids"]) < 50:
        current["evidence_event_ids"].append(event_id)
    if row.get("event_type") != "swap":
        return
    current["swap_count"] += 1
    amount = as_decimal(row.get("amount_usd"))
    if amount is None or amount <= 0:
        if event_id and len(current["missing_volume_event_ids"]) < 50:
            current["missing_volume_event_ids"].append(event_id)
        return
    current["volume_usd"] += amount


def windows_for_entities(
    entities: list[dict[str, Any]],
    existing_outcomes: dict[str, dict[str, Any]],
    followup_days: int,
) -> dict[str, tuple[datetime | None, datetime | None]]:
    windows: dict[str, tuple[datetime | None, datetime | None]] = {}
    for entity in entities:
        token = token_of(entity)
        outcome = existing_outcomes.get(token, {})
        cutoff = parse_time(outcome.get("cutoff")) or parse_time(entity.get("screen_end"))
        followup_end = parse_time(outcome.get("followup_end"))
        if followup_end is None and cutoff is not None:
            followup_end = cutoff + timedelta(days=followup_days)
        windows[token] = cutoff, followup_end
    return windows


def outcome_for_entity(
    entity: dict[str, Any],
    aggregate: dict[str, Any],
    status: dict[str, Any],
    *,
    now: datetime,
    followup_days: int,
    volume_threshold_usd: Decimal,
    existing_outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    token = token_of(entity)
    existing_outcome = existing_outcome or {}
    cutoff = parse_time(existing_outcome.get("cutoff")) or parse_time(entity.get("screen_end"))
    t0 = (
        parse_time(existing_outcome.get("t0"))
        or parse_time(entity.get("screen_start"))
        or parse_time(entity.get("first_observed_timestamp"))
    )
    followup_end = parse_time(existing_outcome.get("followup_end"))
    if followup_end is None and cutoff is not None:
        followup_end = cutoff + timedelta(days=followup_days)

    result: dict[str, Any] = {
        "token_address": token,
        "label_definition": "low_volume_dead",
        "t0": iso_time(t0) if t0 else None,
        "cutoff": iso_time(cutoff) if cutoff else None,
        "followup_days": followup_days,
        "followup_end": iso_time(followup_end) if followup_end else None,
        "volume_threshold_usd": format(volume_threshold_usd, "f"),
        "volume_source": "the_graph_swap_amountUSD",
        "pool_count": len(entity.get("pools") or []),
        "pool_scope_complete": entity.get("pool_scope_complete") is True,
        "activity_collected": status.get("status") == "complete",
        "followup_event_count": aggregate.get("event_count", 0),
        "followup_swap_count": aggregate.get("swap_count", 0),
        "followup_evidence_event_ids": aggregate.get("evidence_event_ids", []),
        "censoring_reason": None,
        "exclusion_reason": None,
    }
    if not result["pool_scope_complete"]:
        result["label"] = "censored"
        result["censoring_reason"] = f"pool_scope_incomplete:{entity.get('pool_scope_reason')}"
        return result
    if not entity.get("pools"):
        result["label"] = "censored"
        result["censoring_reason"] = "no_selected_pools"
        return result
    if entity.get("screen_activity_complete") is False:
        result["label"] = "censored"
        result["censoring_reason"] = (
            f"pre_cutoff_activity_incomplete:{entity.get('screen_activity_reason')}"
        )
        return result
    if cutoff is None:
        result["label"] = "censored"
        result["censoring_reason"] = "missing_cutoff_timestamp"
        return result
    if followup_end is None:
        result["label"] = "censored"
        result["censoring_reason"] = "missing_followup_end"
        return result
    if followup_end > now:
        result["label"] = "censored"
        result["censoring_reason"] = "followup_not_complete_at_retrieval"
        return result
    if status.get("status") != "complete":
        result["label"] = "censored"
        result["censoring_reason"] = f"activity_retrieval_incomplete:{status.get('failure') or status.get('status')}"
        return result
    missing = aggregate.get("missing_volume_event_ids") or []
    if missing:
        result["label"] = "censored"
        result["censoring_reason"] = "missing_or_nonpositive_swap_usd"
        result["missing_volume_event_ids"] = missing
        result["volume_complete"] = False
        return result

    volume_usd = aggregate.get("volume_usd", Decimal("0"))
    result["followup_volume_usd"] = format(volume_usd, "f")
    result["volume_complete"] = True
    result["label"] = (
        "low_volume_dead" if volume_usd < volume_threshold_usd else "continued_activity"
    )
    return result


def read_outcomes(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    return {token_of(row): row for row in read_jsonl(path) if token_of(row)}


def select_entities(
    entities: list[dict[str, Any]],
    outcomes: dict[str, dict[str, Any]],
    label: str | None,
) -> list[dict[str, Any]]:
    if label is None:
        return entities
    return [entity for entity in entities if outcomes.get(token_of(entity), {}).get("label") == label]


def read_coverage(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in read_jsonl(path) if path.exists() else []:
        key = (
            token_of(row),
            str(row.get("protocol") or ""),
            str(row.get("pool_address") or "").lower(),
        )
        if key[0] and key[2]:
            latest[key] = row
    return latest


def run(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    entities_path = (project_root / args.entities).resolve()
    output = (project_root / args.output).resolve()
    entities = read_jsonl(entities_path)
    existing_outcomes = read_outcomes(
        (project_root / args.outcomes).resolve() if args.outcomes else None
    )
    if args.only_label and not args.outcomes:
        raise SystemExit("--only-label requires --outcomes")
    entities = select_entities(entities, existing_outcomes, args.only_label)
    if not entities:
        raise SystemExit(f"no entities selected from: {entities_path}")
    windows = windows_for_entities(entities, existing_outcomes, args.followup_days)
    checkpoint_path = output / "checkpoint.jsonl"
    status_by_token = load_last_checkpoints(checkpoint_path)
    event_path = output / "followup_events.jsonl"
    seen_events, aggregates = load_existing_events(event_path, windows)
    coverage_by_key = read_coverage(output / "followup_coverage.jsonl")

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"{args.api_key_env} is not set; load only that variable before running")
    archive = RawArchive(output)
    http = HttpClient(
        archive,
        user_agent="week1-graph-followup/0.1",
        interval=args.request_interval,
        timeout=args.timeout,
    )
    client = GraphClient(http, api_key)

    now = datetime.now(UTC)
    for entity in sorted(entities, key=lambda row: token_of(row)):
        token = token_of(entity)
        if not token:
            continue
        cutoff, followup_end = windows[token]
        signature = {
            "cutoff": iso_time(cutoff) if cutoff else None,
            "followup_end": iso_time(followup_end) if followup_end else None,
            "followup_days": args.followup_days,
            "scope_fingerprint": scope_fingerprint(entity),
        }
        previous = status_by_token.get(token, {})
        if (
            previous.get("status") == "complete"
            and previous.get("query_signature") == signature
            and int(previous.get("event_count") or 0) == int(
                (aggregates.get(token) or {}).get("event_count", 0)
            )
        ):
            continue

        status: dict[str, Any] = {
            "token_address": token,
            "status": "pending",
            "query_signature": signature,
            "updated_at": utc_now(),
            "event_count": (aggregates.get(token) or {}).get("event_count", 0),
            "request_ids": [],
            "failure": None,
        }
        if entity.get("pool_scope_complete") is not True:
            status["status"] = "skipped_incomplete_scope"
            status["failure"] = entity.get("pool_scope_reason") or "pool_scope_incomplete"
            status_by_token[token] = status
            append_jsonl(checkpoint_path, [status])
            continue
        if not entity.get("pools"):
            status["status"] = "skipped_no_pools"
            status["failure"] = "no_selected_pools"
            status_by_token[token] = status
            append_jsonl(checkpoint_path, [status])
            continue
        if entity.get("screen_activity_complete") is False:
            status["status"] = "skipped_incomplete_screen"
            status["failure"] = entity.get("screen_activity_reason") or "screen_activity_incomplete"
            status_by_token[token] = status
            append_jsonl(checkpoint_path, [status])
            continue
        if cutoff is None or followup_end is None:
            status["status"] = "skipped_missing_cutoff"
            status["failure"] = "missing_cutoff_or_followup_end"
            status_by_token[token] = status
            append_jsonl(checkpoint_path, [status])
            continue
        if followup_end > now:
            status["status"] = "waiting_for_complete_followup"
            status["failure"] = "followup_not_complete_at_retrieval"
            status_by_token[token] = status
            append_jsonl(checkpoint_path, [status])
            continue

        token_events: list[dict[str, Any]] = []
        token_coverage: list[dict[str, Any]] = []
        failures: list[str] = []
        request_ids: list[str] = []
        complete = True
        for protocol in SUBGRAPHS:
            protocol_pools = [
                pool
                for pool in entity.get("pools") or []
                if str(pool.get("protocol") or "") == protocol
            ]
            events, coverage, protocol_complete, failure = fetch_followup_activity(
                client,
                token,
                protocol,
                protocol_pools,
                start_timestamp=cutoff,
                end_timestamp=followup_end,
                max_pages=args.max_pages,
                pool_group_size=args.pool_group_size,
            )
            token_events.extend(events)
            token_coverage.extend(coverage)
            complete = complete and protocol_complete
            if failure:
                failures.append(f"{protocol}:{failure}")
            for row in coverage:
                request_ids.extend(str(value) for value in row.get("request_ids") or [])

        new_events = []
        for row in token_events:
            key = event_key(row)
            if key in seen_events:
                continue
            seen_events.add(key)
            new_events.append(row)
            add_to_aggregate(aggregates, row)
        append_jsonl(event_path, new_events)
        for row in token_coverage:
            key = (
                token_of(row),
                str(row.get("protocol") or ""),
                str(row.get("pool_address") or "").lower(),
            )
            coverage_by_key[key] = row

        status.update(
            {
                "status": "complete" if complete else "failed",
                "updated_at": utc_now(),
                "event_count": (aggregates.get(token) or {}).get("event_count", 0),
                "new_event_count": len(new_events),
                "request_ids": sorted(set(request_ids)),
                "failure": ";".join(failures) if failures else None,
            }
        )
        status_by_token[token] = status
        append_jsonl(checkpoint_path, [status])

    outcomes = []
    for entity in sorted(entities, key=lambda row: token_of(row)):
        token = token_of(entity)
        if not token:
            continue
        outcomes.append(
            outcome_for_entity(
                entity,
                aggregates.get(token, {}),
                status_by_token.get(
                    token,
                    {"status": "missing_checkpoint", "failure": "missing_checkpoint"},
                ),
                now=now,
                followup_days=args.followup_days,
                volume_threshold_usd=Decimal(args.volume_threshold_usd),
                existing_outcome=existing_outcomes.get(token),
            )
        )

    write_jsonl(output / "outcomes.jsonl", outcomes)
    write_jsonl(output / "followup_status.jsonl", sorted(status_by_token.values(), key=token_of))
    write_jsonl(
        output / "followup_coverage.jsonl",
        sorted(
            coverage_by_key.values(),
            key=lambda row: (
                token_of(row),
                str(row.get("protocol") or ""),
                str(row.get("pool_address") or ""),
            ),
        ),
    )
    report = {
        "report_version": "graph-followup-0.1",
        "retrieved_at": utc_now(),
        "source": {
            "name": "The Graph gateway, official Uniswap v2 and v3 subgraphs",
            "endpoint": redact_url(
                "https://gateway.thegraph.com/api/REDACTED/subgraphs/id/<subgraph>",
                secrets=(api_key,),
            ),
            "api_key_env": args.api_key_env,
            "terms_status": "not_audited",
        },
        "inputs": {
            "entities": str(entities_path),
            "outcomes": str((project_root / args.outcomes).resolve()) if args.outcomes else None,
            "only_label": args.only_label,
            "pool_scope_reused": True,
            "pool_discovery_performed": False,
            "checkpoint": str(checkpoint_path),
        },
        "counts": {
            "entities": len(entities),
            "status_counts": dict(Counter(row.get("status") for row in status_by_token.values())),
            "outcome_counts": dict(Counter(row.get("label") for row in outcomes)),
            "followup_events": sum(int(row.get("followup_event_count") or 0) for row in outcomes),
            "complete_labels": sum(
                row.get("label") in {"low_volume_dead", "continued_activity"} for row in outcomes
            ),
        },
        "labels": {
            "primary": {
                "name": "low_volume_dead",
                "followup_days": args.followup_days,
                "threshold_usd": args.volume_threshold_usd,
                "volume_event_type": "swap",
                "volume_field": "Swap.amountUSD",
            }
        },
        "labels_ready": False,
        "decision": (
            "Follow-up retrieval only; audit pool scope, retrieval completeness, "
            "historical USD coverage, and source terms before modelling."
        ),
    }
    write_json(output / "graph_followup_report.json", report)
    return report


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--entities", required=True)
    parser.add_argument("--outcomes")
    parser.add_argument("--only-label", choices=("censored", "low_volume_dead", "continued_activity"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--api-key-env", default="THE_GRAPH_API_KEY")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--pool-group-size", type=int, default=2)
    parser.add_argument("--followup-days", type=int, default=FOLLOWUP_DAYS)
    parser.add_argument("--volume-threshold-usd", default="1000")
    parser.add_argument("--request-interval", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


if __name__ == "__main__":
    result = run(make_parser().parse_args())
    print(
        json.dumps(
            {
                "output": str(Path(result["inputs"]["checkpoint"]).parent),
                "labels_ready": result["labels_ready"],
                "counts": result["counts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
