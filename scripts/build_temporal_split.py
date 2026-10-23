#!/usr/bin/env python3
"""Build a label-independent chronological split for frozen token targets."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


LABELS = ("low_volume_dead", "continued_activity")
PARTITIONS = ("train", "validation", "test")
PARTITION_ORDER = {partition: index for index, partition in enumerate(PARTITIONS)}


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


def parse_time(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("token_address") or "").lower(), str(row.get("source_dataset") or ""))


def temporal_partition(
    t0: datetime,
    *,
    train_end: datetime,
    validation_end: datetime,
    test_end: datetime,
) -> str | None:
    """Assign by t0 only; labels and the existing random partition are ignored."""
    if t0 < train_end:
        return "train"
    if t0 < validation_end:
        return "validation"
    if t0 <= test_end:
        return "test"
    return None


def _discard_row(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "token_address": row.get("token_address"),
        "source_dataset": row.get("source_dataset"),
        "t0": row.get("t0"),
        "label": row.get("label"),
        "censoring_status": row.get("censoring_status"),
        "feature_complete": row.get("feature_complete"),
        "feature_status": row.get("feature_status"),
        "source_partition": row.get("partition"),
        "discard_reason": reason,
    }


def _eligibility_reason(row: dict[str, Any], test_end: datetime) -> tuple[str | None, datetime | None]:
    if row.get("label") not in LABELS:
        return "non_supervised_label", None
    if row.get("censoring_status") is not False:
        return "censored_or_unknown", None
    if row.get("feature_complete") is not True:
        return "feature_incomplete", None
    if "feature_status" in row and row.get("feature_status") not in (None, "complete"):
        return "feature_status_not_complete", None
    if "pool_scope_complete" in row and row.get("pool_scope_complete") is not True:
        return "pool_scope_incomplete", None
    if "activity_collected" in row and row.get("activity_collected") is not True:
        return "activity_collection_incomplete", None
    try:
        t0 = parse_time(row.get("t0"))
    except ValueError:
        return "invalid_t0", None
    if t0 is None:
        return "missing_t0", None
    if t0 > test_end:
        return "after_test_cutoff", t0
    return None, t0


def _validate_boundaries(train_end: datetime, validation_end: datetime, test_end: datetime) -> None:
    if not train_end < validation_end <= test_end:
        raise ValueError("temporal boundaries must satisfy train_end < validation_end <= test_end")


def _validate_no_overlap(rows: list[dict[str, Any]]) -> None:
    groups: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        group = str(row.get("overlap_group") or row.get("token_address") or "")
        groups[group].add(str(row["partition"]))
    crossing = sorted(group for group, partitions in groups.items() if len(partitions) > 1)
    if crossing:
        raise ValueError(f"overlap groups cross temporal partitions: {crossing[:5]}")


def partition_rows(
    rows: list[dict[str, Any]],
    *,
    train_end: datetime,
    validation_end: datetime,
    test_end: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return eligible reassigned rows and explicit discard records."""
    _validate_boundaries(train_end, validation_end, test_end)
    keys = [canonical_key(row) for row in rows]
    if any(not key[0] or not key[1] for key in keys):
        raise ValueError("every target needs token_address and source_dataset")
    if len(keys) != len(set(keys)):
        raise ValueError("target manifest contains duplicate token/source keys")

    eligible: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    for row in rows:
        reason, t0 = _eligibility_reason(row, test_end)
        if reason is not None:
            discarded.append(_discard_row(row, reason))
            continue
        assert t0 is not None
        partition = temporal_partition(
            t0,
            train_end=train_end,
            validation_end=validation_end,
            test_end=test_end,
        )
        if partition is None:
            discarded.append(_discard_row(row, "after_test_cutoff"))
            continue
        reassigned = dict(row)
        reassigned["source_partition"] = row.get("partition")
        reassigned["partition"] = partition
        reassigned["graph_role"] = "test_holdout" if partition == "test" else "development"
        reassigned["temporal_bucket"] = partition
        reassigned["temporal_split_rule"] = "t0_boundaries_from_label_blind_collection_config"
        reassigned["temporal_split_label_independent"] = True
        eligible.append(reassigned)

    _validate_no_overlap(eligible)
    eligible.sort(
        key=lambda row: (
            PARTITION_ORDER[str(row["partition"])],
            str(row.get("t0") or ""),
            str(row["token_address"]),
            str(row["source_dataset"]),
        )
    )
    return eligible, discarded


def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    partition_label_counts = {
        partition: dict(
            sorted(
                Counter(str(row["label"]) for row in rows if row["partition"] == partition).items()
            )
        )
        for partition in PARTITIONS
    }
    return {
        "rows": len(rows),
        "tokens": len({canonical_key(row) for row in rows}),
        "label_counts": dict(sorted(Counter(str(row["label"]) for row in rows).items())),
        "partition_counts": dict(sorted(Counter(str(row["partition"]) for row in rows).items())),
        "partition_label_counts": partition_label_counts,
        "overlap_groups": len({str(row.get("overlap_group") or row["token_address"]) for row in rows}),
    }


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for field in (
        "label",
        "censoring_status",
        "feature_complete",
        "feature_status",
        "pool_scope_complete",
        "activity_collected",
    ):
        if not any(field in row for row in rows):
            continue
        values = ("null" if row.get(field) is None else str(row.get(field)) for row in rows)
        result[field] = dict(sorted(Counter(values).items()))
    return result


def _chronology(rows: list[dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for partition in PARTITIONS:
        values = sorted(str(row.get("t0") or "") for row in rows if row["partition"] == partition)
        result[partition] = {
            "min_t0": values[0] if values else None,
            "max_t0": values[-1] if values else None,
        }
    return result


def _write_splits(path: Path, rows: list[dict[str, Any]]) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise SystemExit("pyarrow is required to write the temporal split") from exc
    fields = (
        "token_address",
        "source_dataset",
        "t0",
        "cutoff",
        "followup_end",
        "label",
        "censoring_status",
        "overlap_group",
        "partition",
        "graph_role",
        "source_partition",
        "temporal_bucket",
    )
    records = [{field: row.get(field) for field in fields} for row in rows]
    parquet.write_table(pa.Table.from_pylist(records), path, compression="zstd")


def _load_boundaries(args: argparse.Namespace) -> tuple[datetime, datetime, datetime, Path | None]:
    config_path = Path(args.config).resolve() if args.config else None
    config: dict[str, Any] = {}
    if config_path is not None:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    split = config.get("split") or {}
    raw = (
        args.train_end or split.get("train_end"),
        args.validation_end or split.get("validation_end"),
        args.test_end or split.get("test_end"),
    )
    if any(value is None for value in raw):
        raise ValueError("all temporal boundaries must be supplied directly or by --config")
    boundaries = tuple(parse_time(value) for value in raw)
    if any(value is None for value in boundaries):
        raise ValueError("temporal boundaries must be valid timestamps")
    train_end, validation_end, test_end = boundaries
    assert train_end is not None and validation_end is not None and test_end is not None
    _validate_boundaries(train_end, validation_end, test_end)
    return train_end, validation_end, test_end, config_path


def build(args: argparse.Namespace) -> dict[str, Any]:
    targets_path = Path(args.targets).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    train_end, validation_end, test_end, config_path = _load_boundaries(args)
    source_rows = read_jsonl(targets_path)
    rows, discarded = partition_rows(
        source_rows,
        train_end=train_end,
        validation_end=validation_end,
        test_end=test_end,
    )
    quality = _counts(rows)
    missing_support = [partition for partition in PARTITIONS if not quality["partition_label_counts"][partition]]
    if missing_support:
        raise ValueError(f"temporal split lacks label support in partition(s): {missing_support}")

    output.mkdir(parents=True, exist_ok=True)
    targets_output = output / "targets.jsonl"
    splits_output = output / "splits.parquet"
    discarded_output = output / "discarded_rows.jsonl"
    write_jsonl(targets_output, rows)
    _write_splits(splits_output, rows)
    write_jsonl(discarded_output, discarded)

    duplicate_input_keys = len(source_rows) - len({canonical_key(row) for row in source_rows})
    manifest = {
        "manifest_version": "temporal-token-split-0.1",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "split_name": args.split_name,
        "source_targets": str(targets_path),
        "source_config": str(config_path) if config_path else None,
        "unit": ["token_address", "source_dataset"],
        "partition_rule": {
            "timestamp_field": "t0",
            "train": f"t0 < {iso_time(train_end)}",
            "validation": f"{iso_time(train_end)} <= t0 < {iso_time(validation_end)}",
            "test": f"{iso_time(validation_end)} <= t0 <= {iso_time(test_end)}",
            "discard_after_test": f"t0 > {iso_time(test_end)}",
            "labels_used_for_assignment": False,
        },
        "boundaries": {
            "train_end": iso_time(train_end),
            "validation_end": iso_time(validation_end),
            "test_end": iso_time(test_end),
        },
        "quality": {
            "input_rows": len(source_rows),
            "eligible_rows": len(rows),
            "discarded_rows": len(discarded),
            "discarded_reason_counts": dict(sorted(Counter(row["discard_reason"] for row in discarded).items())),
            "input_status_counts": _status_counts(source_rows),
            "eligible_status_counts": _status_counts(rows),
            "duplicate_input_keys": duplicate_input_keys,
            **quality,
            "chronology": _chronology(rows),
            "overlap_group_crossings": 0,
            "censoring_access_status": {
                "censored_input_rows": sum(row.get("censoring_status") is True for row in source_rows),
                "unknown_censoring_input_rows": sum(row.get("censoring_status") is None for row in source_rows),
                "eligible_rows_with_censoring": sum(row.get("censoring_status") is not False for row in rows),
            },
        },
        "test_policy": "newest temporal partition, observed class prevalence, scored once after validation-only selection",
        "test_locked": True,
        "outputs": {
            "targets": str(targets_output),
            "splits": str(splits_output),
            "discarded_rows": str(discarded_output),
        },
        "source_sha256": {
            "targets": hashlib.sha256(targets_path.read_bytes()).hexdigest(),
            "config": hashlib.sha256(config_path.read_bytes()).hexdigest() if config_path else None,
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
    result.add_argument("--output", required=True)
    result.add_argument("--config", default="config/week1_candidate_collection_2000.json")
    result.add_argument("--split-name", default="wallet_graph_temporal_20261005_v1")
    result.add_argument("--train-end")
    result.add_argument("--validation-end")
    result.add_argument("--test-end")
    return result


if __name__ == "__main__":
    print(json.dumps(build(parser().parse_args()), indent=2, sort_keys=True))
