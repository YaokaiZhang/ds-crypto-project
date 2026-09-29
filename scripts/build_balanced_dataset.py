#!/usr/bin/env python3
"""Build a deterministic 50/50 primary-label dataset from collected runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


LABELS = ("low_volume_dead", "continued_activity")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")
            count += 1
    return count


def token_of(row: dict[str, Any]) -> str:
    return str(row.get("token_address") or "").lower()


def selection_key(row: dict[str, Any], label: str) -> str:
    period = str(row.get("launch_period") or "unknown")
    return hashlib.sha256(f"{label}:{period}:{token_of(row)}".encode()).hexdigest()


def proportional_quotas(counts: dict[str, int], target: int) -> dict[str, int]:
    total = sum(counts.values())
    if total < target:
        raise ValueError(f"target {target} exceeds available rows {total}")
    raw = {key: target * count / total for key, count in counts.items()}
    quotas = {key: min(counts[key], int(value)) for key, value in raw.items()}
    remaining = target - sum(quotas.values())
    order = sorted(
        counts,
        key=lambda key: (-(raw[key] - int(raw[key])), key),
    )
    while remaining:
        progressed = False
        for key in order:
            if quotas[key] < counts[key]:
                quotas[key] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            raise ValueError("could not allocate proportional quotas")
    return quotas


def select_balanced_rows(
    outcomes: list[dict[str, Any]],
    *,
    target_per_label: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    eligible = [
        row
        for row in outcomes
        if row.get("label") in LABELS and row.get("volume_complete") is True
    ]
    by_label: dict[str, list[dict[str, Any]]] = {label: [] for label in LABELS}
    for row in eligible:
        by_label[row["label"]].append(row)

    available_counts = {label: len(rows) for label, rows in by_label.items()}
    insufficient = {
        label: count for label, count in available_counts.items() if count < target_per_label
    }
    if insufficient:
        raise ValueError(f"insufficient complete labels: {insufficient}")

    selected: list[dict[str, Any]] = []
    selected_period_counts: dict[str, dict[str, int]] = {}
    for label in LABELS:
        rows = by_label[label]
        period_counts = Counter(str(row.get("launch_period") or "unknown") for row in rows)
        quotas = proportional_quotas(dict(period_counts), target_per_label)
        chosen: list[dict[str, Any]] = []
        for period, quota in quotas.items():
            period_rows = [
                row for row in rows if str(row.get("launch_period") or "unknown") == period
            ]
            period_rows.sort(key=lambda row: selection_key(row, label))
            chosen.extend(period_rows[:quota])
        chosen.sort(key=lambda row: (str(row.get("launch_period") or "unknown"), token_of(row)))
        selected.extend(chosen)
        selected_period_counts[label] = dict(Counter(str(row.get("launch_period") or "unknown") for row in chosen))

    selected.sort(key=lambda row: (row["label"], str(row.get("launch_period") or "unknown"), token_of(row)))
    manifest = {
        "target_per_label": target_per_label,
        "target_total": target_per_label * len(LABELS),
        "eligible_counts": available_counts,
        "selected_counts": dict(Counter(row["label"] for row in selected)),
        "selected_period_counts": selected_period_counts,
        "selection_rule": "proportional launch-period quotas within each label, then SHA-256 token order",
        "censored_excluded": sum(row.get("label") == "censored" for row in outcomes),
    }
    return selected, manifest


def source_rows(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    outcomes = read_jsonl(source / "outcomes.jsonl")
    entities = read_jsonl(source / "token_entities.jsonl")
    sensitivity = read_jsonl(source / "sensitivity_zero_activity_outcomes.jsonl")
    if not outcomes or not entities:
        raise ValueError(f"source is missing outcomes or token_entities: {source}")
    return outcomes, entities, sensitivity


def run(args: argparse.Namespace) -> dict[str, Any]:
    sources = [Path(value).resolve() for value in args.source]
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")

    all_outcomes: list[dict[str, Any]] = []
    seen_outcome_tokens: set[str] = set()
    all_entities: dict[str, dict[str, Any]] = {}
    all_sensitivities: dict[str, dict[str, Any]] = {}
    source_manifest: list[dict[str, Any]] = []
    for source in sources:
        outcomes, entities, sensitivities = source_rows(source)
        source_name = source.name
        for row in outcomes:
            token = token_of(row)
            if not token:
                raise ValueError(f"outcome has no token address: {source}")
            if token in seen_outcome_tokens:
                raise ValueError(f"duplicate token across source runs: {token}")
            seen_outcome_tokens.add(token)
            row = dict(row)
            row["source_dataset"] = source_name
            all_outcomes.append(row)
        for row in entities:
            token = token_of(row)
            if token:
                all_entities[token] = dict(row) | {"source_dataset": source_name}
        for row in sensitivities:
            token = token_of(row)
            if token:
                all_sensitivities[token] = dict(row) | {"source_dataset": source_name}
        source_manifest.append({"path": str(source), "outcomes": len(outcomes), "entities": len(entities)})

    selected, selection_manifest = select_balanced_rows(
        all_outcomes,
        target_per_label=args.target_per_label,
    )
    selected_tokens = {token_of(row) for row in selected}
    selected_outcomes = []
    selected_entities = []
    selected_sensitivities = []
    for outcome in selected:
        token = token_of(outcome)
        selected_outcomes.append(outcome)
        entity = all_entities.get(token)
        if entity is None:
            raise ValueError(f"selected outcome has no matching entity: {token}")
        selected_entities.append(entity | {"primary_label": outcome["label"]})
        if token in all_sensitivities:
            selected_sensitivities.append(all_sensitivities[token])

    output.mkdir(parents=True, exist_ok=True)
    event_count = 0
    event_sources: list[dict[str, Any]] = []
    with (output / "events.jsonl").open("w", encoding="utf-8") as handle:
        for source in sources:
            source_event_path = source / "events.jsonl"
            source_event_count = 0
            selected_event_count = 0
            if source_event_path.exists():
                with source_event_path.open(encoding="utf-8") as event_handle:
                    for line in event_handle:
                        if not line.strip():
                            continue
                        row = json.loads(line)
                        source_event_count += 1
                        if token_of(row) not in selected_tokens:
                            continue
                        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")
                        selected_event_count += 1
                        event_count += 1
            event_sources.append({
                "path": str(source_event_path),
                "source_events": source_event_count,
                "selected_events": selected_event_count,
            })

    write_jsonl(output / "outcomes.jsonl", selected_outcomes)
    write_jsonl(output / "token_entities.jsonl", selected_entities)
    if selected_sensitivities:
        write_jsonl(output / "sensitivity_zero_activity_outcomes.jsonl", selected_sensitivities)
    selection_manifest["sources"] = source_manifest
    selection_manifest["event_sources"] = event_sources
    selection_manifest["selected_events"] = event_count
    selection_manifest["selected_tokens"] = len(selected_tokens)
    selection_manifest["dataset_definition"] = {
        "primary_labels": list(LABELS),
        "censored_excluded": True,
        "class_balance": "1:1",
        "test_policy": "chronological metadata retained; do not interpret this balanced cohort as natural prevalence",
    }
    write_json(output / "dataset_manifest.json", selection_manifest)
    return selection_manifest


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-per-label", type=int, default=1000)
    return parser


if __name__ == "__main__":
    try:
        result = run(make_parser().parse_args())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, indent=2, sort_keys=True))
