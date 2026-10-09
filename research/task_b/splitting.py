"""Deterministic, entity/group-separated Task B research partitions.

P/U experiment targets are copies of frozen supervision; the canonical label
status and eligibility are never rewritten into benign labels.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import math
import random
from typing import Any, Iterable, Sequence

from chainrisk.tasks import canonical_task

PARTITIONS = ("train", "validation", "test")


def task_name(value: str) -> str:
    return canonical_task(value)


def _verified_group(row: dict[str, Any]) -> str | None:
    if row.get("group_verified") is not True or not row.get("group_id"):
        return None
    if not (row.get("group_ref") or row.get("group_evidence_ref")):
        raise ValueError(f"verified group requires an evidence reference: {row.get('sample_id')}")
    return str(row["group_id"])


def _unix(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a timestamp")
    if isinstance(value, (int, float)):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("label timestamp must be finite")
        return result
    try:
        result = float(value)
    except (ValueError, TypeError):
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("label timestamp requires a timezone")
        result = parsed.timestamp()
    if not math.isfinite(result):
        raise ValueError("label timestamp must be finite")
    return result


def experiment_record(record: dict[str, Any], mode: str) -> dict[str, Any]:
    """Create experiment eligibility without changing canonical supervision."""
    result = dict(record)
    result["task_id"] = task_name(str(record["task_id"]))
    status = record.get("label_status")
    positive = status == "supported_positive" and record.get("eligible") is True
    negative = status == "supported_negative" and record.get("eligible") is True
    if mode in {"supervised", "supervised_binary"}:
        accepted = positive or negative
        target = int(positive) if accepted else None
    elif mode == "known_positive_vs_unlabeled":
        background = (
            status == "unlabeled" and record.get("data_eligible") is True
            and record.get("background_selected") is True and bool(record.get("cohort_id"))
        )
        accepted = positive or background
        target = int(positive) if accepted else None
    elif mode == "nnpu":
        raise NotImplementedError("nnPU is a future extension requiring a separate audited population/sampling protocol")
    else:
        raise ValueError(f"unsupported experiment mode: {mode}")
    existing = record.get("observed_target")
    if (positive or negative) and existing is not None and existing != int(positive):
        raise ValueError(f"label status/target conflict: {record.get('sample_id')}")
    result.update(experiment_mode=mode, experiment_eligible=accepted, observed_target=target)
    return result


def assert_partition_isolation(records: Iterable[dict[str, Any]]) -> None:
    """No target entity or verified group may occupy multiple partitions."""
    seen_samples: set[str] = set()
    entity_partitions: dict[tuple[Any, str], set[str]] = defaultdict(set)
    group_partitions: dict[str, set[str]] = defaultdict(set)
    for row in records:
        if not (row.get("experiment_eligible") or row.get("eligible")):
            continue
        sample = str(row["sample_id"])
        if sample in seen_samples:
            raise ValueError(f"duplicate sample_id: {sample}")
        seen_samples.add(sample)
        partition = row.get("partition")
        if partition not in PARTITIONS:
            raise ValueError(f"missing/invalid partition: {sample}")
        entity = str(row.get("entity_id") or row.get("target") or "").lower()
        if not entity:
            raise ValueError(f"missing target entity: {sample}")
        entity_partitions[(row.get("chain_id", 1), entity)].add(partition)
        group = _verified_group(row)
        if group:
            group_partitions[group].add(partition)
    if any(len(parts) > 1 for parts in entity_partitions.values()):
        raise ValueError("target entity leakage across partitions")
    if any(len(parts) > 1 for parts in group_partitions.values()):
        raise ValueError("verified group leakage across partitions")


def split_records(
    supervision: Sequence[dict[str, Any]],
    ratios: Sequence[float] = (0.8, 0.1, 0.1),
    seed: int = 20261008,
    mode: str = "supervised",
    training_as_of: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Allocate connected entity/groups once, using class-support deficits.

    The greedy allocator never observes model performance. Large groups may
    make exact ratios impossible; achieved ratios are reported, and inadequate
    per-partition class support fails rather than searching another seed.
    """
    if len(ratios) != 3 or any(r <= 0 for r in ratios) or abs(sum(ratios) - 1) > 1e-8:
        raise ValueError("ratios must contain three positive values summing to one")
    rows = [experiment_record(row, mode) for row in supervision]
    if len({str(row["sample_id"]) for row in rows}) != len(rows):
        raise ValueError("duplicate sample_id in supervision")
    tasks = {row["task_id"] for row in rows}
    if len(tasks) != 1:
        raise ValueError("split one task at a time")
    cohort_ids = {str(row["cohort_id"]) for row in rows if row.get("experiment_eligible") and row.get("label_status") == "unlabeled"}
    if len(cohort_ids) > 1:
        raise ValueError("P/U background must belong to one explicitly frozen cohort")
    selected = [row for row in rows if row["experiment_eligible"]]
    for row in rows:
        row["partition"] = None
    counts = Counter(int(row["observed_target"]) for row in selected)
    if set(counts) != {0, 1} or any(counts[label] * min(ratios) < 1 for label in (0, 1)):
        raise ValueError("insufficient two-class support for the frozen 80/10/10 protocol")
    parent = list(range(len(selected)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def join(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    entities: dict[tuple[Any, str], int] = {}
    groups: dict[str, int] = {}
    for index, row in enumerate(selected):
        entity = str(row.get("entity_id") or row.get("target") or "").lower()
        if not entity:
            raise ValueError(f"missing entity_id: {row['sample_id']}")
        key = (row.get("chain_id", 1), entity)
        if key in entities:
            join(index, entities[key])
        entities[key] = index
        group = _verified_group(row)
        if group:
            if group in groups:
                join(index, groups[group])
            groups[group] = index
    components: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(selected):
        components[find(index)].append(row)
    group_rows = list(components.values())
    if any(sum(any(row["observed_target"] == label for row in group) for group in group_rows) < 3 for label in (0, 1)):
        raise ValueError("each class requires at least three independent entity/groups")
    # Canonical order makes permutation of input rows harmless; a seeded
    # tie-breaker is applied only to groups of equal size.
    group_rows.sort(key=lambda group: min(str(row["sample_id"]) for row in group))
    rng = random.Random(seed)
    rng.shuffle(group_rows)
    group_rows.sort(key=len, reverse=True)
    assigned = {partition: Counter() for partition in PARTITIONS}
    targets = {partition: {label: counts[label] * ratios[i] for label in (0, 1)} for i, partition in enumerate(PARTITIONS)}
    for group in group_rows:
        histogram = Counter(int(row["observed_target"]) for row in group)

        def marginal(partition: str) -> float:
            return sum(
                ((assigned[partition][label] + histogram[label] - targets[partition][label]) ** 2
                 - (assigned[partition][label] - targets[partition][label]) ** 2)
                / targets[partition][label]
                for label in (0, 1)
            )

        partition = min(PARTITIONS, key=marginal)
        connected_id = hashlib.sha256("\n".join(sorted(str(row["sample_id"]) for row in group)).encode()).hexdigest()[:16]
        for row in group:
            row.update(partition=partition, split_group_id=f"connected:{connected_id}")
        assigned[partition].update(histogram)
    if any(any(assigned[partition][label] == 0 for label in (0, 1)) for partition in PARTITIONS):
        raise ValueError("fixed grouped allocation lacks class support; use a separately registered protocol")
    if training_as_of is not None:
        for row in selected:
            if row["partition"] != "train" or row["label_status"] == "unlabeled":
                continue
            available = _unix(row.get("label_available_at"))
            if available is None or available > training_as_of:
                raise ValueError(f"training label unavailable at training_as_of: {row['sample_id']}")
    assert_partition_isolation(rows)
    manifest = {
        "schema_version": "task-b-split-1", "task_id": next(iter(tasks)),
        "seed": seed, "mode": mode, "ratios": dict(zip(PARTITIONS, ratios)),
        "training_as_of": training_as_of, "background_cohort_id": next(iter(cohort_ids), None),
        "eligible_samples": len(selected), "excluded_samples": len(rows) - len(selected),
        "independent_groups": len(group_rows),
        "class_counts": {str(label): counts[label] for label in (0, 1)},
        "partition_class_counts": {partition: {str(label): assigned[partition][label] for label in (0, 1)} for partition in PARTITIONS},
        "allocation": "one deterministic greedy class-stratified connected-group allocation; no seed search",
        "negative_meaning": "frozen unlabeled background; not verified benign" if mode in {"known_positive_vs_unlabeled", "nnpu"} else "task-specific admitted negative",
    }
    return rows, manifest
