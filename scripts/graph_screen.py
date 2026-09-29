#!/usr/bin/env python3
"""Screen unused token candidates using only the first seven days of activity.

The screen is deliberately label-blind: it never reads the 90-day follow-up
window. It discovers the complete selected-pool scope, queries only the
candidate's first seven calendar days, records pre-cutoff features, and then
selects a development-enrichment batch by early swap volume strata.
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
from typing import Any, Iterable

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
    event_time,
    fetch_pools,
    normalize_event,
    read_jsonl,
    utc_now,
    write_json,
    write_jsonl,
)


PRIMARY_OBSERVATION_DAYS = 7
VOLUME_QUOTAS = {
    ">=1000": Decimal("0.60"),
    "100-999.99": Decimal("0.30"),
    "<100": Decimal("0.10"),
}


def epoch_seconds(value: datetime) -> int:
    return int(value.timestamp())


def screen_event_query(
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
        f"timestamp_gte: {epoch_seconds(start_timestamp)}, "
        f"timestamp_lte: {epoch_seconds(end_timestamp)}"
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


def fetch_screen_activity(
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
    """Fetch only events in the pre-cutoff screen window."""
    if not pools:
        return [], [], True, None

    all_events: dict[tuple[str, str], dict[str, Any]] = {}
    all_coverage: list[dict[str, Any]] = []
    failures: list[str] = []
    complete = True

    for start in range(0, len(pools), pool_group_size):
        group = pools[start : start + pool_group_size]
        pool_addresses = [row["pool_address"] for row in group]
        request_ids: list[str] = []
        page_count = 0
        group_complete = True
        group_failure: str | None = None
        skip = 0
        while True:
            page_count += 1
            if page_count > max_pages:
                group_complete = False
                group_failure = "screen_page_limit_reached"
                break
            try:
                data, request_id = client.query(
                    protocol,
                    screen_event_query(
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
            for event_type in ("swap", "mint", "burn"):
                source_rows = data.get(f"{event_type}s") or []
                page_counts.append(len(source_rows))
                for row in source_rows:
                    normalized = normalize_event(protocol, event_type, row, request_id, token)
                    if normalized:
                        all_events[(event_type, normalized["event_id"])] = normalized
            if max(page_counts, default=0) < PAGE_SIZE:
                break
            skip += PAGE_SIZE

        for pool in group:
            pool_events = [
                row for row in all_events.values() if row["pool_address"] == pool["pool_address"]
            ]
            all_coverage.append(
                {
                    "token_address": token,
                    "pool_address": pool["pool_address"],
                    "protocol": protocol,
                    "screen_start": start_timestamp.isoformat().replace("+00:00", "Z"),
                    "screen_end": end_timestamp.isoformat().replace("+00:00", "Z"),
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

    return (
        sorted(
            all_events.values(),
            key=lambda row: (row["block_number"], row["log_index"], row["event_type"], row["event_id"]),
        ),
        all_coverage,
        complete,
        ";".join(failures) if failures else None,
    )


def launch_band(period: str | None) -> str:
    if period in {"2020", "2021", "2022"}:
        return "2020-2022"
    if period in {"2023", "2024"}:
        return "2023-2024"
    return "2025-2026"


def volume_stratum(value: Decimal) -> str:
    if value >= Decimal("1000"):
        return ">=1000"
    if value >= Decimal("100"):
        return "100-999.99"
    return "<100"


def deterministic_key(row: dict[str, Any], salt: str) -> str:
    return hashlib.sha256(f"{salt}:{row['token_address'].lower()}".encode()).hexdigest()


def allocate_targets(eligible_counts: dict[str, int], target: int) -> dict[str, int]:
    targets = {
        key: min(count, int((VOLUME_QUOTAS[key] * target).to_integral_value()))
        for key, count in eligible_counts.items()
    }
    remaining = target - sum(targets.values())
    order = sorted(
        eligible_counts,
        key=lambda key: (-(eligible_counts[key] - targets.get(key, 0)), key),
    )
    while remaining > 0 and order:
        progressed = False
        for key in order:
            if targets.get(key, 0) < eligible_counts.get(key, 0):
                targets[key] = targets.get(key, 0) + 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            break
    return targets


def select_enriched_candidates(
    rows: list[dict[str, Any]],
    target: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    eligible = [row for row in rows if row.get("screen_eligible")]
    eligible_counts = Counter(row["early_volume_stratum"] for row in eligible)
    targets = allocate_targets(dict(eligible_counts), target)
    selected: list[dict[str, Any]] = []
    for stratum in (">=1000", "100-999.99", "<100"):
        bucket = [row for row in eligible if row["early_volume_stratum"] == stratum]
        bucket.sort(key=lambda row: deterministic_key(row, f"screen-{stratum}"))
        selected.extend(bucket[: targets.get(stratum, 0)])

    selected_counts = Counter(row["early_volume_stratum"] for row in selected)
    eligible_by_stratum = dict(eligible_counts)
    selected_by_stratum = dict(selected_counts)
    for rank, row in enumerate(
        sorted(selected, key=lambda row: deterministic_key(row, "selected")),
        start=1,
    ):
        stratum = row["early_volume_stratum"]
        row["selection_rank"] = rank
        row["sampling_rank"] = rank
        row["selection_stratum"] = stratum
        row["eligible_in_stratum"] = eligible_by_stratum[stratum]
        row["selected_in_stratum"] = selected_by_stratum[stratum]
        probability = Decimal(selected_by_stratum[stratum]) / Decimal(eligible_by_stratum[stratum])
        row["inclusion_probability"] = format(probability, "f")
        row["sampling_weight"] = format(Decimal("1") / probability, "f")

    manifest = {
        "sampling_rule": (
            "screen unused candidates with pre-cutoff features only; select deterministically "
            "within early-volume strata"
        ),
        "target_tokens": target,
        "eligible_tokens": len(eligible),
        "selected_tokens": len(selected),
        "eligible_counts": eligible_by_stratum,
        "requested_counts": targets,
        "selected_counts": selected_by_stratum,
        "inclusion_probabilities": {
            key: format(Decimal(selected_by_stratum[key]) / Decimal(eligible_by_stratum[key]), "f")
            for key in selected_by_stratum
        },
        "sampling_weights": {
            key: format(Decimal(eligible_by_stratum[key]) / Decimal(selected_by_stratum[key]), "f")
            for key in selected_by_stratum
        },
        "quota_definition": {
            "early_volume_usd >= 1000": "60%",
            "early_volume_usd 100-999.99": "30%",
            "early_volume_usd < 100": "10%",
        },
    }
    return selected, manifest


def append_rows(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")


def screen_candidate(
    client: GraphClient,
    candidate: dict[str, Any],
    *,
    max_pool_pages: int,
    max_activity_pages: int,
    activity_pool_group_size: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    token = candidate["token_address"].lower()
    pools_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    pool_coverage: list[dict[str, Any]] = []
    scope_complete = True
    scope_failures: list[str] = []
    for protocol in SUBGRAPHS:
        pools, coverage = fetch_pools(client, token, protocol, max_pages=max_pool_pages)
        pool_coverage.append(coverage)
        scope_complete = scope_complete and coverage["complete"]
        if coverage["failure"]:
            scope_failures.append(f"{protocol}:{coverage['failure']}")
        for pool in pools:
            pools_by_key[(protocol, pool["pool_address"])] = pool
    pools = sorted(pools_by_key.values(), key=lambda row: (row["creation_block"] or 0, row["pool_address"]))
    creation_times = [
        datetime.fromisoformat(pool["creation_timestamp"].replace("Z", "+00:00"))
        for pool in pools
        if pool.get("creation_timestamp")
    ]
    t0 = min(creation_times) if creation_times else None
    screen_end = t0 + timedelta(days=PRIMARY_OBSERVATION_DAYS) if t0 else None
    activity_coverage: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    activity_complete = False
    activity_failure: str | None = None
    if t0 and scope_complete:
        activity_complete = True
        failures: list[str] = []
        for protocol in SUBGRAPHS:
            protocol_pools = [pool for pool in pools if pool["protocol"] == protocol]
            screen_events, coverage, complete, failure = fetch_screen_activity(
                client,
                token,
                protocol,
                protocol_pools,
                start_timestamp=t0,
                end_timestamp=screen_end,
                max_pages=max_activity_pages,
                pool_group_size=activity_pool_group_size,
            )
            events.extend(screen_events)
            activity_coverage.extend(coverage)
            activity_complete = activity_complete and complete
            if failure:
                failures.append(f"{protocol}:{failure}")
        activity_failure = ";".join(failures) if failures else None

    early_swaps = [row for row in events if row["event_type"] == "swap"]
    early_mints = sum(row["event_type"] == "mint" for row in events)
    early_burns = sum(row["event_type"] == "burn" for row in events)
    valid_amounts: list[Decimal] = []
    missing_volume_events: list[str] = []
    for row in early_swaps:
        amount = as_decimal(row.get("amount_usd"))
        if amount is None or amount <= 0:
            missing_volume_events.append(row["event_id"])
        else:
            valid_amounts.append(amount)
    early_volume = sum(valid_amounts, Decimal("0"))
    active_days = {
        event_time(row).date().isoformat()
        for row in events
        if event_time(row) is not None
    }
    eligible = scope_complete and activity_complete and not missing_volume_events
    reason = None
    if not scope_complete:
        reason = "pool_scope_incomplete"
    elif not activity_complete:
        reason = "screen_activity_incomplete"
    elif missing_volume_events:
        reason = "missing_or_nonpositive_screen_swap_usd"
    result = {
        "token_address": token,
        "launch_period": candidate.get("launch_period"),
        "launch_band": launch_band(candidate.get("launch_period")),
        "sampling_rank": candidate.get("sampling_rank"),
        "first_observed_block": candidate.get("first_observed_block"),
        "first_observed_timestamp": candidate.get("first_observed_timestamp"),
        "pool_count": len(pools),
        "pool_count_stratum": "1" if len(pools) == 1 else "2-4" if len(pools) <= 4 else "5+",
        "pools": pools,
        "pool_scope_complete": scope_complete,
        "pool_scope_reason": ";".join(scope_failures) if scope_failures else "graph_pool_queries_complete",
        "screen_start": t0.isoformat().replace("+00:00", "Z") if t0 else None,
        "screen_end": screen_end.isoformat().replace("+00:00", "Z") if screen_end else None,
        "early_swap_count": len(early_swaps),
        "early_mint_count": early_mints,
        "early_burn_count": early_burns,
        "early_active_days": len(active_days),
        "early_volume_usd": format(early_volume, "f"),
        "early_volume_stratum": volume_stratum(early_volume) if not missing_volume_events else "unknown_usd",
        "missing_screen_volume_count": len(missing_volume_events),
        "screen_activity_complete": activity_complete,
        "screen_activity_reason": activity_failure or "screen_activity_queries_complete",
        "screen_eligible": eligible,
        "screen_exclusion_reason": reason,
    }
    return result, events, pool_coverage, activity_coverage


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--exclude-candidates", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--api-key-env", default="THE_GRAPH_API_KEY")
    parser.add_argument("--max-pool-pages", type=int, default=20)
    parser.add_argument("--max-activity-pages", type=int, default=20)
    parser.add_argument("--activity-pool-group-size", type=int, default=2)
    parser.add_argument("--request-interval", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    output = (project_root / args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"{args.api_key_env} is not set; load only that variable before running")

    excluded = {
        row["token_address"].lower()
        for row in read_jsonl(project_root / args.exclude_candidates)
    }
    candidates = []
    seen: set[str] = set()
    for row in read_jsonl(project_root / args.candidates):
        token = row["token_address"].lower()
        if token in excluded or token in seen:
            continue
        seen.add(token)
        candidates.append(row)
    candidates.sort(key=lambda row: deterministic_key(row, "screen-input"))

    archive = RawArchive(output)
    http = HttpClient(
        archive,
        user_agent="week1-graph-screen/0.1",
        interval=args.request_interval,
        timeout=args.timeout,
    )
    client = GraphClient(http, api_key)
    screening_path = output / "screening_candidates.jsonl"
    event_path = output / "screening_events.jsonl"
    pool_coverage_path = output / "manifests" / "pool_coverage.jsonl"
    activity_coverage_path = output / "manifests" / "activity_coverage.jsonl"
    screened: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        result, events, pool_coverage, activity_coverage = screen_candidate(
            client,
            candidate,
            max_pool_pages=args.max_pool_pages,
            max_activity_pages=args.max_activity_pages,
            activity_pool_group_size=args.activity_pool_group_size,
        )
        screened.append(result)
        append_rows(screening_path, [result])
        append_rows(event_path, events)
        append_rows(pool_coverage_path, pool_coverage)
        append_rows(activity_coverage_path, activity_coverage)
        if index % 25 == 0 or index == len(candidates):
            write_json(
                output / "screening_progress.json",
                {"processed": index, "total": len(candidates), "updated_at": utc_now()},
            )

    selected, selection_manifest = select_enriched_candidates(screened, args.batch_size)
    write_jsonl(output / "selected_candidates.jsonl", selected)
    write_json(output / "selection_manifest.json", selection_manifest)
    report = {
        "report_version": "graph-screen-0.1",
        "retrieved_at": utc_now(),
        "source": {
            "name": "The Graph gateway, official Uniswap v2 and v3 subgraphs",
            "api_key_env": args.api_key_env,
            "terms_status": "not_audited",
        },
        "selection": {
            "candidates_file": args.candidates,
            "excluded_candidates_file": args.exclude_candidates,
            "candidate_count_after_exclusion": len(candidates),
            "screened_count": len(screened),
            "selected_count": len(selected),
            "label_blind": True,
            "selection_features_cutoff": "t0 plus 7 calendar days",
        },
        "counts": {
            "screen_eligible": sum(row["screen_eligible"] for row in screened),
            "screen_excluded": sum(not row["screen_eligible"] for row in screened),
            "screen_exclusion_reasons": dict(
                Counter(row["screen_exclusion_reason"] for row in screened if row["screen_exclusion_reason"])
            ),
            "early_volume_strata": dict(
                Counter(row["early_volume_stratum"] for row in screened if row["screen_eligible"])
            ),
            "selected_early_volume_strata": dict(
                Counter(row["early_volume_stratum"] for row in selected)
            ),
            "screen_events": sum(1 for _ in event_path.open()) if event_path.exists() else 0,
            "raw_request_rows": len(read_jsonl(output / "manifests" / "request_log.jsonl")),
        },
        "selection_manifest": "selection_manifest.json",
        "next_step": "run graph_free_pilot.py on selected_candidates.jsonl for complete 90-day labels",
    }
    write_json(output / "screening_report.json", report)
    return report


if __name__ == "__main__":
    result = run(make_parser().parse_args())
    print(json.dumps(result, indent=2, sort_keys=True))
