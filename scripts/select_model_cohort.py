#!/usr/bin/env python3
"""Select a deterministic balanced development cohort from a DuckDB product."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


LABELS = ("low_volume_dead", "continued_activity")


def proportional_quotas(counts: dict[str, int], target: int) -> dict[str, int]:
    total = sum(counts.values())
    if total < target:
        raise ValueError(f"target {target} exceeds available rows {total}")
    raw = {key: target * count / total for key, count in counts.items()}
    quotas = {key: min(counts[key], int(value)) for key, value in raw.items()}
    remaining = target - sum(quotas.values())
    order = sorted(counts, key=lambda key: (-(raw[key] - int(raw[key])), key))
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


def selection_key(row: dict[str, Any]) -> str:
    value = ":".join(
        str(row.get(field) or "unknown")
        for field in ("label", "partition", "launch_period", "token_address")
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def select(rows: list[dict[str, Any]], target_per_label: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_groups: dict[str, dict[str, int]] = {}
    eligible_counts = Counter(str(row["label"]) for row in rows)
    for label in LABELS:
        label_rows = [row for row in rows if row["label"] == label]
        if len(label_rows) < target_per_label:
            raise ValueError(f"insufficient complete {label} rows: {len(label_rows)}")
        groups = Counter(
            ":".join(str(row.get(field) or "unknown") for field in ("partition", "launch_period"))
            for row in label_rows
        )
        quotas = proportional_quotas(dict(groups), target_per_label)
        chosen: list[dict[str, Any]] = []
        for group, quota in quotas.items():
            group_rows = [
                row
                for row in label_rows
                if ":".join(str(row.get(field) or "unknown") for field in ("partition", "launch_period")) == group
            ]
            chosen.extend(sorted(group_rows, key=selection_key)[:quota])
        selected.extend(chosen)
        selected_groups[label] = dict(Counter(
            ":".join(str(row.get(field) or "unknown") for field in ("partition", "launch_period"))
            for row in chosen
        ))
    selected.sort(key=lambda row: (row["label"], row["partition"], row.get("launch_period") or "", row["token_address"]))
    manifest = {
        "manifest_version": "model-cohort-0.1",
        "target_per_label": target_per_label,
        "target_total": target_per_label * len(LABELS),
        "eligible_counts": dict(eligible_counts),
        "selected_counts": dict(Counter(row["label"] for row in selected)),
        "selected_partition_counts": {
            label: dict(Counter(row["partition"] for row in selected if row["label"] == label))
            for label in LABELS
        },
        "selected_partition_launch_period_groups": selected_groups,
        "selection_rule": "proportional partition/launch-period quotas within each label, then SHA-256 row order",
        "eligible_partitions": ["train", "validation"],
        "test_policy": "chronological test rows are retained separately and never selected into the development cohort",
    }
    return selected, manifest


def run(args: argparse.Namespace) -> dict[str, Any]:
    import duckdb

    database = Path(args.database).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database), read_only=True)
    query = """
        SELECT s.*, t.launch_period,
               m.selection_probability, m.inclusion_weight,
               m.case_control_weight, m.overlap_group
        FROM supervised_model_table AS s
        JOIN token_entities AS t USING (token_address, source_dataset)
        LEFT JOIN sampling_manifest AS m USING (token_address, source_dataset)
        WHERE s.partition IN ('train', 'validation')
          AND s.label IN ('low_volume_dead', 'continued_activity')
          AND s.volume_complete = TRUE
          AND s.feature_complete = TRUE
    """
    rows = [dict(zip([item[0] for item in connection.description], row)) for row in connection.execute(query).fetchall()]
    selected, manifest = select(rows, args.target_per_label)
    selected_keys = {(row["token_address"], row["source_dataset"]) for row in selected}
    holdout_query = """
        SELECT s.*, t.launch_period,
               m.selection_probability, m.inclusion_weight,
               m.case_control_weight, m.overlap_group
        FROM supervised_model_table AS s
        JOIN token_entities AS t USING (token_address, source_dataset)
        LEFT JOIN sampling_manifest AS m USING (token_address, source_dataset)
        WHERE s.partition = 'test'
          AND s.label IN ('low_volume_dead', 'continued_activity')
          AND s.volume_complete = TRUE
          AND s.feature_complete = TRUE
    """
    holdout_rows = [dict(zip([item[0] for item in connection.description], row)) for row in connection.execute(holdout_query).fetchall()]
    connection.close()
    if len(selected_keys) != args.target_per_label * len(LABELS):
        raise ValueError("selected cohort contains duplicate token/source keys")
    if any(row["partition"] == "test" for row in selected):
        raise ValueError("test row entered development cohort")
    manifest.update({
        "database": str(database),
        "selected_rows": len(selected),
        "test_holdout_rows": len(holdout_rows),
        "selected_unique_tokens": len({row["token_address"] for row in selected}),
        "test_holdout_counts": dict(Counter(row["label"] for row in holdout_rows)),
    })
    (output / "cohort.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=True, default=str) + "\n" for row in selected),
        encoding="utf-8",
    )
    (output / "test_holdout.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=True, default=str) + "\n" for row in holdout_rows),
        encoding="utf-8",
    )
    (output / "cohort_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-per-label", type=int, default=500)
    return parser


if __name__ == "__main__":
    print(json.dumps(run(make_parser().parse_args()), indent=2, sort_keys=True))
