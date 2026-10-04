#!/usr/bin/env python3
"""Collect participant-aware pre-cutoff events for a frozen balanced cohort.

Pool scope and labels are reused from the frozen analytical product. Only the
token's observation window, inclusive of ``t0`` and ``cutoff``, is queried
again so the event rows contain wallet participant fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.graph_free_pilot import (  # noqa: E402
    GraphClient,
    GraphQueryFailure,
    PAGE_SIZE,
    SUBGRAPHS,
    normalize_event,
    participant_coverage,
)
from scripts.participant_fields import PARTICIPANT_SOURCE_FIELDS  # noqa: E402
from scripts.week1_audit import (  # noqa: E402
    HttpClient,
    RawArchive,
    parse_time,
    read_jsonl,
    redact_url,
    utc_now,
    write_json,
    write_jsonl,
)


LABELS = ("continued_activity", "low_volume_dead")
EVENT_TYPES = ("swap",)
GRAPH_ENDPOINT = "https://gateway.thegraph.com/api/{api_key}/subgraphs/id/{subgraph_id}"


def token_of(row: dict[str, Any]) -> str:
    return str(row.get("token_address") or "").lower()


def target_key(row: dict[str, Any]) -> tuple[str, str]:
    return token_of(row), str(row.get("source_dataset") or "")


def selection_key(row: dict[str, Any]) -> str:
    material = "|".join(
        [token_of(row), str(row.get("source_dataset") or ""), str(row.get("label") or "")]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def select_targets(rows: Iterable[dict[str, Any]], target_per_label: int) -> list[dict[str, Any]]:
    eligible: dict[str, list[dict[str, Any]]] = {label: [] for label in LABELS}
    seen: set[tuple[str, str]] = set()
    for raw in rows:
        row = dict(raw)
        token = token_of(row)
        key = target_key(row)
        label = str(row.get("label") or "")
        if not token or not key[1] or label not in eligible:
            continue
        if key in seen:
            raise ValueError(f"duplicate target row: {key}")
        seen.add(key)
        if parse_time(str(row.get("t0") or "")) is None:
            raise ValueError(f"target has no usable t0: {key}")
        if parse_time(str(row.get("cutoff") or "")) is None:
            raise ValueError(f"target has no usable cutoff: {key}")
        eligible[label].append(row)

    selected: list[dict[str, Any]] = []
    for label in LABELS:
        ordered = sorted(eligible[label], key=selection_key)
        if len(ordered) < target_per_label:
            raise ValueError(
                f"not enough eligible {label} rows: {len(ordered)} < {target_per_label}"
            )
        selected.extend(ordered[:target_per_label])
    return sorted(selected, key=lambda row: (str(row.get("label")), token_of(row), str(row.get("source_dataset"))))


def load_pool_scope(database: Path, targets: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    try:
        import duckdb
    except ImportError as exc:
        raise SystemExit("pool scope loading requires duckdb") from exc

    wanted = {target_key(row) for row in targets}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    connection = duckdb.connect(str(database), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT token_address, source_dataset, pool_address, protocol,
                   token0, token1, token0_symbol, token1_symbol,
                   creation_block, creation_timestamp, creation_transaction_hash,
                   source, pool_scope_complete, pool_scope_reason
            FROM pool_entities
            """
        ).fetchall()
    finally:
        connection.close()

    for row in rows:
        token = str(row[0] or "").lower()
        key = (token, str(row[1] or ""))
        if key not in wanted:
            continue
        grouped[key].append(
            {
                "pool_address": str(row[2] or "").lower(),
                "protocol": str(row[3] or "").lower(),
                "token0": row[4],
                "token1": row[5],
                "token0_symbol": row[6],
                "token1_symbol": row[7],
                "creation_block": row[8],
                "creation_timestamp": row[9],
                "creation_transaction_hash": row[10],
                "source": row[11],
                "pool_scope_complete": bool(row[12]),
                "pool_scope_reason": row[13],
            }
        )

    missing = sorted(wanted - set(grouped))
    if missing:
        raise ValueError(f"missing frozen pool scope for {len(missing)} targets; first={missing[:3]}")
    incomplete = [
        key
        for key, pools in grouped.items()
        if not pools or any(not pool["pool_scope_complete"] for pool in pools)
    ]
    if incomplete:
        raise ValueError(
            f"frozen pool scope is incomplete for {len(incomplete)} targets; first={incomplete[:3]}"
        )
    for pools in grouped.values():
        pools.sort(key=lambda row: (int(row["creation_block"] or 0), row["pool_address"]))
    return dict(grouped)


def bounded_event_query(
    protocol: str,
    pools: list[str],
    start_timestamp: datetime,
    end_timestamp: datetime,
    skip: int,
) -> str:
    pool_filter = "pair_in" if protocol == "uniswap_v2" else "pool_in"
    relation = "pair" if protocol == "uniswap_v2" else "pool"
    pool_values = ", ".join(json.dumps(pool) for pool in sorted(set(pools)))
    time_filter = (
        f"{pool_filter}: [{pool_values}], "
        f"timestamp_gte: {int(start_timestamp.timestamp())}, "
        f"timestamp_lte: {int(end_timestamp.timestamp())}"
    )
    common = f"""
      id timestamp logIndex
      transaction {{ id blockNumber timestamp }}
      {relation} {{ id }}
    """
    fields = PARTICIPANT_SOURCE_FIELDS[protocol]
    return f"""
    query {{
      swaps(
        first: {PAGE_SIZE}, skip: {skip}
        orderBy: timestamp, orderDirection: asc
        where: {{ {time_filter} }}
      ) {{ {common} {fields["swap_sender"]} {fields["swap_recipient"]} {fields["transaction_from"]} amountUSD }}
    }}
    """


def fetch_group(
    client: GraphClient,
    token: str,
    protocol: str,
    pools: list[dict[str, Any]],
    *,
    start_timestamp: datetime,
    end_timestamp: datetime,
    max_pages: int,
    group_number: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events: dict[tuple[str, str], dict[str, Any]] = {}
    request_ids: list[str] = []
    complete = True
    failure: str | None = None
    page_count = 0

    for page in range(max_pages):
        page_count += 1
        try:
            data, request_id = client.query(
                protocol,
                bounded_event_query(
                    protocol,
                    [str(pool["pool_address"]).lower() for pool in pools],
                    start_timestamp,
                    end_timestamp,
                    page * PAGE_SIZE,
                ),
            )
        except GraphQueryFailure as exc:
            complete = False
            failure = str(exc)
            break
        request_ids.append(request_id)
        page_counts: list[int] = []
        for event_type in EVENT_TYPES:
            source_rows = data.get(f"{event_type}s") or []
            page_counts.append(len(source_rows))
            for source_row in source_rows:
                normalized = normalize_event(protocol, event_type, source_row, request_id, token)
                if normalized is None:
                    complete = False
                    failure = failure or "event_missing_required_field"
                    continue
                events[(event_type, normalized["event_id"])] = normalized
        if max(page_counts, default=0) < PAGE_SIZE:
            break
    else:
        complete = False
        failure = "activity_page_limit_reached"

    coverage = {
        "token_address": token,
        "protocol": protocol,
        "pool_addresses": [str(pool["pool_address"]).lower() for pool in pools],
        "group_number": group_number,
        "observation_start": start_timestamp.isoformat().replace("+00:00", "Z"),
        "observation_end": end_timestamp.isoformat().replace("+00:00", "Z"),
        "pages": page_count,
        "request_ids": request_ids,
        "event_count": len(events),
        "complete": complete,
        "failure": failure,
    }
    return sorted(events.values(), key=lambda row: (row["block_number"], row["log_index"], row["event_id"])), coverage


def target_outcome(target: dict[str, Any], pools: list[dict[str, Any]], complete: bool) -> dict[str, Any]:
    outcome = dict(target)
    outcome.setdefault("label_definition", "low_volume_dead")
    outcome.setdefault("followup_days", 90)
    outcome.setdefault("volume_threshold_usd", "1000")
    outcome.setdefault("volume_source", "frozen_label_source")
    outcome["pool_count"] = len(pools)
    outcome["pool_scope_complete"] = True
    outcome["activity_collected"] = complete
    if not complete:
        outcome["collection_quality"] = "incomplete_participant_event_collection"
    return outcome


def entity_row(target: dict[str, Any], pools: list[dict[str, Any]], complete: bool, reason: str) -> dict[str, Any]:
    return {
        "token_address": token_of(target),
        "source_dataset": target.get("source_dataset"),
        "launch_period": target.get("launch_period"),
        "sampling_rank": target.get("sampling_rank"),
        "first_observed_block": target.get("first_observed_block"),
        "first_observed_timestamp": target.get("first_observed_timestamp"),
        "t0": target.get("t0"),
        "cutoff": target.get("cutoff"),
        "followup_end": target.get("followup_end"),
        "pools": pools,
        "pool_scope_complete": True,
        "pool_scope_reason": "reused_frozen_pool_scope",
        "activity_collected": complete,
        "activity_collection_reason": reason,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    targets_path = (project_root / args.targets).resolve()
    database = (project_root / args.pool_database).resolve()
    output = (project_root / args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    targets = select_targets(read_jsonl(targets_path), args.target_per_label)
    pools_by_target = load_pool_scope(database, targets)
    archive = RawArchive(output)
    api_key = __import__("os").environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"{args.api_key_env} is not set; load only that variable before running")
    http = HttpClient(
        archive,
        user_agent="wallet-graph-participant-collector/0.1",
        interval=args.request_interval,
        timeout=args.timeout,
    )
    client = GraphClient(http, api_key)

    entities: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    all_events: dict[tuple[str, str, str], dict[str, Any]] = {}
    activity_coverage: list[dict[str, Any]] = []
    pool_coverage: list[dict[str, Any]] = []
    failure_counts: Counter[str] = Counter()

    for target in targets:
        token = token_of(target)
        key = target_key(target)
        pools = pools_by_target[key]
        start_timestamp = parse_time(str(target["t0"]))
        end_timestamp = parse_time(str(target["cutoff"]))
        if start_timestamp is None or end_timestamp is None or start_timestamp > end_timestamp:
            raise ValueError(f"invalid target window: {key}")
        pool_coverage.append(
            {
                "token_address": token,
                "source_dataset": target.get("source_dataset"),
                "pool_count": len(pools),
                "protocol_counts": dict(Counter(pool["protocol"] for pool in pools)),
                "complete": True,
                "source": "frozen_analytical_duckdb",
            }
        )
        token_complete = True
        token_failures: list[str] = []
        for protocol in SUBGRAPHS:
            protocol_pools = [pool for pool in pools if pool["protocol"] == protocol]
            for group_number, start in enumerate(range(0, len(protocol_pools), args.pool_group_size), start=1):
                events, coverage = fetch_group(
                    client,
                    token,
                    protocol,
                    protocol_pools[start : start + args.pool_group_size],
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                    max_pages=args.max_activity_pages,
                    group_number=group_number,
                )
                activity_coverage.append(coverage)
                for event in events:
                    all_events[(token, event["event_type"], event["event_id"])] = event
                if not coverage["complete"]:
                    token_complete = False
                    token_failures.append(f"{protocol}:{coverage['failure'] or 'incomplete'}")
                    failure_counts[coverage["failure"] or "incomplete"] += 1
        reason = ";".join(token_failures) if token_failures else "bounded_participant_queries_complete"
        entities.append(entity_row(target, pools, token_complete, reason))
        outcomes.append(target_outcome(target, pools, token_complete))

    events = sorted(all_events.values(), key=lambda row: (row["token_address"], row["block_number"], row["log_index"], row["event_id"]))
    graph_targets = []
    for target in targets:
        graph_target = dict(target)
        graph_target["label_source_dataset"] = graph_target.get("source_dataset")
        graph_target["source_dataset"] = output.name
        graph_targets.append(graph_target)
    write_jsonl(output / "selected_targets.jsonl", targets)
    write_jsonl(output / "graph_targets.jsonl", graph_targets)
    write_jsonl(output / "token_entities.jsonl", entities)
    write_jsonl(output / "outcomes.jsonl", outcomes)
    write_jsonl(output / "events.jsonl", events)
    write_jsonl(output / "manifests" / "pool_coverage.jsonl", pool_coverage)
    write_jsonl(output / "manifests" / "activity_coverage.jsonl", activity_coverage)
    write_jsonl(output / "sensitivity_zero_activity_outcomes.jsonl", [])

    report = {
        "report_version": "wallet-graph-participant-collection-0.1",
        "retrieved_at": utc_now(),
        "source": {
            "name": "The Graph gateway, official Uniswap v2 and v3 subgraphs",
            "endpoint": redact_url(
                GRAPH_ENDPOINT.format(api_key=api_key, subgraph_id="<subgraph>"),
                secrets=(api_key,),
            ),
            "api_key_env": args.api_key_env,
            "normalized_event_schema": "week1-events-0.2",
            "participant_field_mapping": PARTICIPANT_SOURCE_FIELDS,
            "pool_scope": "reused_frozen_analytical_duckdb",
            "event_window": "inclusive[t0,cutoff]",
            "event_types": ["swap"],
        },
        "selection": {
            "targets_file": str(targets_path),
            "graph_targets_file": str(output / "graph_targets.jsonl"),
            "selection_rule": "SHA-256 order within each frozen label, first target_per_label rows",
            "target_per_label": args.target_per_label,
            "selected_tokens": len(targets),
            "label_counts": dict(Counter(str(row["label"]) for row in targets)),
            "partition_counts": dict(Counter(str(row.get("partition") or "") for row in targets)),
        },
        "counts": {
            "tokens": len(targets),
            "pool_records": sum(len(pools_by_target[target_key(row)]) for row in targets),
            "activity_groups": len(activity_coverage),
            "activity_events": len(events),
            "raw_request_rows": len(read_jsonl(output / "manifests" / "request_log.jsonl")),
            "participant_field_coverage": participant_coverage(events),
            "complete_tokens": sum(entity["activity_collected"] for entity in entities),
            "incomplete_tokens": sum(not entity["activity_collected"] for entity in entities),
        },
        "coverage": {
            "pool_scope_reused": True,
            "activity_queries_complete": all(row["complete"] for row in activity_coverage),
            "tokens_with_complete_activity": sum(entity["activity_collected"] for entity in entities),
            "failure_counts": dict(failure_counts),
        },
        "labels": {
            "frozen_from_targets": True,
            "followup_recollected": False,
            "primary": "low_volume_dead / continued_activity",
        },
        "decision": "Participant-aware pre-cutoff source collection for graph construction; labels and split are reused from the frozen target file.",
    }
    write_json(output / "wallet_graph_collection_report.json", report)
    return report


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--targets", required=True)
    parser.add_argument("--pool-database", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-per-label", type=int, default=1000)
    parser.add_argument("--api-key-env", default="THE_GRAPH_API_KEY")
    parser.add_argument("--pool-group-size", type=int, default=2)
    parser.add_argument("--max-activity-pages", type=int, default=20)
    parser.add_argument("--request-interval", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


if __name__ == "__main__":
    result = run(make_parser().parse_args())
    print(json.dumps({"counts": result["counts"], "coverage": result["coverage"]}, indent=2, sort_keys=True))
