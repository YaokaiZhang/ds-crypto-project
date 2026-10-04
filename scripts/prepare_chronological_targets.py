#!/usr/bin/env python3
"""Apply the frozen historical partitions to the current supervised targets."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


LABELS = frozenset(("low_volume_dead", "continued_activity"))
PARTITIONS = ("train", "validation", "test")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def canonical_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("token_address") or "").lower(), str(row.get("source_dataset") or ""))


def read_partition_map(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise SystemExit("pyarrow is required to read the historical split") from exc

    table = parquet.read_table(
        path,
        columns=["token_address", "source_dataset", "partition", "label", "t0", "cutoff", "followup_end"],
    )
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for record in table.to_pylist():
        partition = str(record.get("partition") or "")
        if partition not in PARTITIONS:
            continue
        key = canonical_key(record)
        if not key[0] or not key[1]:
            raise ValueError(f"historical split row has no canonical key: {record}")
        if key in result:
            raise ValueError(f"historical split contains duplicate key: {key}")
        result[key] = record
    return result


def apply_partitions(
    rows: list[dict[str, Any]],
    historical_partitions: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    keys = [canonical_key(row) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("target manifest contains duplicate token/source keys")
    reassigned: list[dict[str, Any]] = []
    for row in rows:
        key = canonical_key(row)
        source = historical_partitions.get(key)
        if source is None:
            raise ValueError(f"historical split is missing target key: {key}")
        if row.get("label") not in LABELS:
            raise ValueError(f"target has non-supervised label: {row.get('label')!r}")
        if source.get("label") != row.get("label"):
            raise ValueError(f"label mismatch for {key}: target={row.get('label')!r}, split={source.get('label')!r}")
        copied = dict(row)
        copied["partition"] = str(source["partition"])
        copied["graph_role"] = "test_holdout" if copied["partition"] == "test" else "development"
        copied["chronological_source_t0"] = source.get("t0")
        copied["chronological_source_cutoff"] = source.get("cutoff")
        copied["chronological_source_followup_end"] = source.get("followup_end")
        reassigned.append(copied)

    groups: dict[str, set[str]] = defaultdict(set)
    for row in reassigned:
        group = str(row.get("overlap_group") or row["token_address"])
        groups[group].add(str(row["partition"]))
    crossing = sorted(group for group, partitions in groups.items() if len(partitions) > 1)
    if crossing:
        raise ValueError(f"overlap groups cross chronological partitions: {crossing[:5]}")
    reassigned.sort(
        key=lambda row: (
            PARTITIONS.index(str(row["partition"])),
            str(row.get("t0") or ""),
            str(row["token_address"]),
            str(row["source_dataset"]),
        )
    )
    return reassigned


def counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "label_counts": dict(sorted(Counter(str(row["label"]) for row in rows).items())),
        "partition_counts": dict(sorted(Counter(str(row["partition"]) for row in rows).items())),
        "partition_label_counts": {
            partition: dict(
                sorted(
                    Counter(str(row["label"]) for row in rows if row["partition"] == partition).items()
                )
            )
            for partition in PARTITIONS
        },
        "overlap_groups": len({str(row.get("overlap_group") or row["token_address"]) for row in rows}),
    }


def chronology(rows: list[dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for partition in PARTITIONS:
        values = sorted(str(row.get("t0") or "") for row in rows if row["partition"] == partition)
        result[partition] = {"min_t0": values[0] if values else None, "max_t0": values[-1] if values else None}
    return result


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise SystemExit("pyarrow is required to write the chronological split") from exc
    parquet.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


def build(args: argparse.Namespace) -> dict[str, Any]:
    targets_path = Path(args.targets).resolve()
    historical_path = Path(args.historical_splits).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    rows = apply_partitions(read_jsonl(targets_path), read_partition_map(historical_path))
    quality = counts(rows)
    if any(not quality["partition_label_counts"][partition] for partition in PARTITIONS):
        raise ValueError("chronological target manifest must contain all partitions")
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "targets.jsonl", rows)
    write_parquet(output / "splits.parquet", rows)
    manifest = {
        "manifest_version": "historical-chronological-token-split-0.1",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_targets": str(targets_path),
        "source_historical_splits": str(historical_path),
        "unit": ["token_address", "source_dataset"],
        "partition_rule": "reuse the historical split partition for each complete supervised target",
        "test_policy": "test partition is the newest time period and is scored once after validation selection",
        "quality": quality,
        "chronology": chronology(rows),
        "outputs": {
            "targets": str(output / "targets.jsonl"),
            "splits": str(output / "splits.parquet"),
        },
        "source_sha256": {
            "targets": hashlib.sha256(targets_path.read_bytes()).hexdigest(),
            "historical_splits": hashlib.sha256(historical_path.read_bytes()).hexdigest(),
        },
    }
    (output / "split_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--targets", required=True)
    result.add_argument("--historical-splits", required=True)
    result.add_argument("--output", required=True)
    return result


if __name__ == "__main__":
    print(json.dumps(build(parser().parse_args()), indent=2, sort_keys=True))
