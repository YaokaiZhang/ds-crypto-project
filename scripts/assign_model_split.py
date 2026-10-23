#!/usr/bin/env python3
"""Assign complete labelled tokens to the frozen general 90/10 split.

The source data product keeps the historical chronology-based split for audit
purposes. This module reads its complete labelled population and writes a
separate, deterministic token-level split manifest plus graph target rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from packages.evaluation_protocol import PARTITIONS, evaluation_policy


PRIMARY_LABELS = frozenset({"low_volume_dead", "continued_activity"})
DEFAULT_SEED = 20261001


def stable_hash(seed: int, label: str, launch_period: str, group: str) -> str:
    value = "\0".join((str(seed), label, launch_period, group))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def proportional_counts(total: int, ratios: dict[str, float]) -> dict[str, int]:
    """Return integer targets using largest-remainder rounding."""
    if total < 0:
        raise ValueError("total must be non-negative")
    if set(ratios) != set(PARTITIONS):
        raise ValueError(f"ratios must contain exactly {PARTITIONS}")
    if any(not math.isfinite(value) or value <= 0 for value in ratios.values()):
        raise ValueError("train/validation ratios must be positive and finite")
    scale = sum(ratios.values())
    exact = {partition: total * ratios[partition] / scale for partition in PARTITIONS}
    counts = {partition: int(exact[partition]) for partition in PARTITIONS}
    remainder = total - sum(counts.values())
    order = sorted(
        PARTITIONS,
        key=lambda partition: (-(exact[partition] - counts[partition]), PARTITIONS.index(partition)),
    )
    for partition in order[:remainder]:
        counts[partition] += 1
    return counts


def assign_partitions(
    rows: list[dict[str, Any]],
    ratios: dict[str, float],
    seed: int,
) -> list[dict[str, Any]]:
    """Assign rows by label/launch stratum while keeping overlap groups intact."""
    strata: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    group_strata: dict[str, tuple[str, str]] = {}
    for row in rows:
        label = str(row.get("label") or "")
        launch_period = str(row.get("launch_period") or "unknown")
        group = str(row.get("overlap_group") or row.get("token_address") or "")
        if label not in PRIMARY_LABELS:
            raise ValueError(f"supervised split row has invalid label: {label!r}")
        if not group:
            raise ValueError(f"supervised split row has no overlap group: {row}")
        stratum = (label, launch_period)
        previous = group_strata.setdefault(group, stratum)
        if previous != stratum:
            raise ValueError(
                f"overlap group {group!r} crosses label/launch strata: {previous} and {stratum}"
            )
        strata[stratum][group].append(row)

    assigned_rows: list[dict[str, Any]] = []
    for (label, launch_period) in sorted(strata):
        groups = strata[(label, launch_period)]
        total = sum(len(members) for members in groups.values())
        targets = proportional_counts(total, ratios)
        assigned_counts = {partition: 0 for partition in PARTITIONS}
        ordered_groups = sorted(
            groups,
            key=lambda group: stable_hash(seed, label, launch_period, group),
        )
        for group in ordered_groups:
            members = groups[group]
            size = len(members)
            remaining = {
                partition: targets[partition] - assigned_counts[partition]
                for partition in PARTITIONS
            }

            def choice_key(partition: str) -> tuple[int, int, int, int]:
                proposed = assigned_counts[partition] + size
                overage = max(proposed - targets[partition], 0)
                fits = 0 if remaining[partition] >= size else 1
                return (fits, overage, -remaining[partition], PARTITIONS.index(partition))

            partition = min(PARTITIONS, key=choice_key)
            assigned_counts[partition] += size
            for member in members:
                copied = dict(member)
                copied["partition"] = partition
                copied["graph_role"] = "development"
                copied["assignment_hash"] = stable_hash(seed, label, launch_period, group)
                assigned_rows.append(copied)

    assigned_rows.sort(
        key=lambda row: (
            PARTITIONS.index(row["partition"]),
            str(row["label"]),
            str(row.get("launch_period") or "unknown"),
            str(row["token_address"]),
            str(row["source_dataset"]),
        )
    )
    return assigned_rows


def validate_assignments(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = [(row["token_address"], row["source_dataset"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("split manifest contains duplicate token/source keys")
    groups: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("label") not in PRIMARY_LABELS:
            raise ValueError("split manifest contains a non-supervised label")
        if row.get("partition") not in PARTITIONS:
            raise ValueError("split manifest contains an invalid partition")
        groups[str(row["overlap_group"])].add(str(row["partition"]))
    crossing_groups = sorted(group for group, partitions in groups.items() if len(partitions) > 1)
    if crossing_groups:
        raise ValueError(f"overlap groups cross partitions: {crossing_groups[:5]}")
    return {
        "rows": len(rows),
        "label_counts": dict(sorted(Counter(str(row["label"]) for row in rows).items())),
        "partition_counts": dict(
            sorted(Counter(str(row["partition"]) for row in rows).items())
        ),
        "partition_label_counts": {
            partition: dict(
                sorted(
                    Counter(
                        str(row["label"])
                        for row in rows
                        if row["partition"] == partition
                    ).items()
                )
            )
            for partition in PARTITIONS
        },
        "overlap_groups": len(groups),
        "overlap_groups_crossing_partitions": len(crossing_groups),
    }


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def load_rows(data_product: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    try:
        import duckdb
    except ImportError as exc:
        raise SystemExit("duckdb is required to read the data product") from exc

    outcomes = sql_path(data_product / "outcomes.parquet")
    features = sql_path(data_product / "features.parquet")
    sampling = sql_path(data_product / "sampling.parquet")
    tokens = sql_path(data_product / "tokens.parquet")
    connection = duckdb.connect()
    try:
        population = connection.execute(
            f"SELECT label, COUNT(*) AS row_count FROM read_parquet('{outcomes}') GROUP BY label"
        ).fetchall()
        population_counts = {str(label): int(count) for label, count in population}
        result = connection.execute(
            f"""
            SELECT
              lower(t.token_address) AS token_address,
              t.source_dataset,
              COALESCE(NULLIF(t.launch_period, ''), 'unknown') AS launch_period,
              o.label,
              o.t0,
              o.cutoff,
              o.followup_end,
              f.observation_days,
              f.event_count,
              f.swap_count,
              f.mint_count,
              f.burn_count,
              CAST(f.pre_cutoff_volume_usd AS VARCHAR) AS pre_cutoff_volume_usd,
              f.pre_cutoff_missing_swap_usd_count,
              f.active_day_count,
              f.pool_count,
              f.protocol_count,
              f.first_event_timestamp,
              f.last_event_timestamp,
              f.feature_complete,
              f.feature_status,
              COALESCE(NULLIF(s.overlap_group, ''), lower(t.token_address)) AS overlap_group,
              CAST(s.selection_probability AS VARCHAR) AS selection_probability,
              s.selection_stratum,
              CAST(s.inclusion_weight AS VARCHAR) AS inclusion_weight,
              CAST(s.case_control_weight AS VARCHAR) AS case_control_weight
            FROM read_parquet('{outcomes}') AS o
            JOIN read_parquet('{features}') AS f USING (token_address, source_dataset)
            JOIN read_parquet('{tokens}') AS t USING (token_address, source_dataset)
            JOIN read_parquet('{sampling}') AS s USING (token_address, source_dataset)
            WHERE o.label IN ('low_volume_dead', 'continued_activity')
              AND o.volume_complete = TRUE
              AND f.feature_complete = TRUE
            ORDER BY o.label, launch_period, token_address, t.source_dataset
            """
        )
        columns = [item[0] for item in result.description]
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
    finally:
        connection.close()
    return rows, population_counts


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit("pyarrow is required to write the split manifest") from exc
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


def build(args: argparse.Namespace) -> dict[str, Any]:
    data_product = Path(args.data_product).resolve()
    config_path = Path(args.config).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    ratios = {partition: float(config["ratios"][partition]) for partition in PARTITIONS}
    seed = int(args.seed if args.seed is not None else config.get("seed", DEFAULT_SEED))
    rows, population_counts = load_rows(data_product)
    assigned = assign_partitions(rows, ratios, seed)
    quality = validate_assignments(assigned)
    if quality["rows"] != len(rows):
        raise ValueError("assignment dropped rows")
    for row in assigned:
        row["censoring_status"] = False
        row["exclusion_reason"] = None
        row["split_frozen_before_model_selection"] = True
        row["split_freeze_evidence"] = "general-stratified-token-split-0.2"

    output.mkdir(parents=True, exist_ok=True)
    write_parquet(output / "splits.parquet", assigned)
    write_jsonl(output / "targets.jsonl", assigned)
    manifest = {
        "manifest_version": "general-stratified-token-split-0.2",
        "evaluation": evaluation_policy(),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "data_product": str(data_product),
        "config": str(config_path),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "seed": seed,
        "ratios": ratios,
        "unit": ["token_address", "source_dataset"],
        "stratify_within": ["label", "launch_period"],
        "group_boundary": "overlap_group",
        "population_counts": population_counts,
        "excluded_from_supervised_split": {
            "censored": population_counts.get("censored", 0),
            "other_labels": sum(
                count for label, count in population_counts.items()
                if label not in PRIMARY_LABELS and label != "censored"
            ),
        },
        "assignment": quality,
        "partition_label_stratum_counts": {
            partition: {
                f"{label}|{period}": sum(
                    row["partition"] == partition
                    and row["label"] == label
                    and row.get("launch_period") == period
                    for row in assigned
                )
                for label, period in sorted(
                    {(str(row["label"]), str(row.get("launch_period") or "unknown")) for row in assigned}
                )
            }
            for partition in PARTITIONS
        },
        "validation_policy": "90/10 train/validation; validation selects models and is the final reported partition",
        "censored_policy": "censored rows remain in the source data product and are absent here",
        "outputs": {
            "splits": str(output / "splits.parquet"),
            "targets": str(output / "targets.jsonl"),
        },
    }
    (output / "split_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--data-product", required=True)
    result.add_argument("--config", default="config/model_split.json")
    result.add_argument("--output", required=True)
    result.add_argument("--seed", type=int)
    return result


if __name__ == "__main__":
    print(json.dumps(build(parser().parse_args()), indent=2, sort_keys=True))
