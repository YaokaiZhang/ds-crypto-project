#!/usr/bin/env python3
"""Merge the main Graph volume archive with a targeted retry."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.graph_free_pilot import outcome_for_entity, zero_activity_outcome_for_entity


MAIN = ROOT / "data/week1_graph_free_volume_full_20260925"
RETRY = ROOT / "data/week1_graph_free_volume_bbc_retry_20260925"
OUTPUT = ROOT / "data/week1_graph_free_volume_results_20260925"
REPLACED_TOKEN = "0xbbc2ae13b23d715c30720f079fcd9b4a74093505"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> None:
    main_entities = read_jsonl(MAIN / "token_entities.jsonl")
    retry_entities = read_jsonl(RETRY / "token_entities.jsonl")
    retry_entity = next(row for row in retry_entities if row["token_address"] == REPLACED_TOKEN)
    entities = [
        retry_entity if row["token_address"] == REPLACED_TOKEN else row
        for row in main_entities
    ]

    main_events = read_jsonl(MAIN / "events.jsonl")
    retry_events = read_jsonl(RETRY / "events.jsonl")
    events = [
        *[row for row in main_events if row["token_address"] != REPLACED_TOKEN],
        *retry_events,
    ]
    events.sort(key=lambda row: (row["token_address"], row["block_number"], row["log_index"], row["event_id"]))

    main_pool_coverage = read_jsonl(MAIN / "manifests/pool_coverage.jsonl")
    retry_pool_coverage = read_jsonl(RETRY / "manifests/pool_coverage.jsonl")
    pool_coverage = [
        *[row for row in main_pool_coverage if row["token_address"] != REPLACED_TOKEN],
        *retry_pool_coverage,
    ]
    main_activity_coverage = read_jsonl(MAIN / "manifests/activity_coverage.jsonl")
    retry_activity_coverage = read_jsonl(RETRY / "manifests/activity_coverage.jsonl")
    activity_coverage = [
        *[row for row in main_activity_coverage if row["token_address"] != REPLACED_TOKEN],
        *retry_activity_coverage,
    ]

    events_by_token = {entity["token_address"]: [] for entity in entities}
    for event in events:
        events_by_token.setdefault(event["token_address"], []).append(event)
    retrieved_at_values = [
        json.loads((MAIN / "graph_free_pilot_report.json").read_text())["retrieved_at"],
        json.loads((RETRY / "graph_free_pilot_report.json").read_text())["retrieved_at"],
    ]
    retrieved_at = max(retrieved_at_values)
    now = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00")).astimezone(UTC)
    outcomes = [
        outcome_for_entity(entity, events_by_token[entity["token_address"]], now)
        for entity in entities
    ]
    sensitivity = [
        zero_activity_outcome_for_entity(entity, events_by_token[entity["token_address"]], now)
        for entity in entities
    ]

    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUTPUT / "token_entities.jsonl", entities)
    write_jsonl(OUTPUT / "events.jsonl", events)
    write_jsonl(OUTPUT / "outcomes.jsonl", outcomes)
    write_jsonl(OUTPUT / "sensitivity_zero_activity_outcomes.jsonl", sensitivity)
    write_jsonl(OUTPUT / "manifests/pool_coverage.jsonl", pool_coverage)
    write_jsonl(OUTPUT / "manifests/activity_coverage.jsonl", activity_coverage)
    write_jsonl(
        OUTPUT / "manifests/source_archives.jsonl",
        [
            {"archive": str(MAIN.relative_to(ROOT)), "role": "main_100_token_collection"},
            {"archive": str(RETRY.relative_to(ROOT)), "role": "targeted_retry_for_transient_graph_timeout"},
        ],
    )

    report = {
        "report_version": "graph-free-volume-results-0.1",
        "retrieved_at": retrieved_at,
        "source_archives": [
            str(MAIN.relative_to(ROOT)),
            str(RETRY.relative_to(ROOT)),
        ],
        "replacement": {
            "token_address": REPLACED_TOKEN,
            "reason": "main archive had transient Graph indexer timeout; targeted one-pool retry completed",
        },
        "counts": {
            "pool_records": sum(len(entity["pools"]) for entity in entities),
            "activity_events": len(events),
            "outcomes": len(outcomes),
            "outcome_counts": dict(Counter(row["label"] for row in outcomes)),
            "sensitivity_outcome_counts": dict(Counter(row["label"] for row in sensitivity)),
            "swap_events_with_usd": sum(
                row["event_type"] == "swap" and row.get("amount_usd") is not None for row in events
            ),
            "main_raw_request_rows": len(read_jsonl(MAIN / "manifests/request_log.jsonl")),
            "retry_raw_request_rows": len(read_jsonl(RETRY / "manifests/request_log.jsonl")),
        },
        "coverage": {
            "pool_queries_complete": all(row["complete"] for row in pool_coverage),
            "activity_queries_complete": all(row["complete"] for row in activity_coverage),
            "entities_with_complete_pool_scope": sum(row["pool_scope_complete"] for row in entities),
            "entities_with_complete_activity": sum(row["activity_collected"] for row in entities),
        },
        "integrity": {
            "duplicate_event_keys": len(events) - len({(row["token_address"], row["event_id"]) for row in events}),
            "swap_events_missing_usd": sum(
                row["event_type"] == "swap" and row.get("amount_usd") is None for row in events
            ),
            "swap_events_nonpositive_usd": sum(
                row["event_type"] == "swap"
                and row.get("amount_usd") is not None
                and Decimal(row["amount_usd"]) <= 0
                for row in events
            ),
            "entities": len({row["token_address"] for row in entities}),
        },
        "labels_ready": False,
        "go_no_go": False,
        "decision": "Volume labels are reproducible for the merged cohort, but source terms, class support, and feature/data gates still require audit before modelling.",
    }
    (OUTPUT / "graph_free_volume_results_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
