#!/usr/bin/env python3
"""Train a matched tabular logistic baseline on a frozen token split.

The target manifest contains the supervised partition and the pre-cutoff
feature columns emitted by the recovered data product. This script does not
read graph features, outcomes, or post-cutoff fields. A partition override can
be supplied for the historical chronological stress test.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from packages.progress import add_progress_arguments, progress_bar

from scripts.train_graphsage import classification_metrics, select_threshold
from packages.evaluation_protocol import PARTITIONS, evaluation_policy, final_validation_report


LABEL_TO_INT = {"low_volume_dead": 0, "continued_activity": 1}
FEATURE_NAMES = [
    "event_count",
    "swap_count",
    "mint_count",
    "burn_count",
    "pre_cutoff_volume_usd",
    "pre_cutoff_missing_swap_usd_count",
    "active_day_count",
    "pool_count",
    "protocol_count",
]


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


def row_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("token_address")), str(row.get("source_dataset")))


def row_features(row: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for name in FEATURE_NAMES:
        try:
            value = float(row.get(name))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"feature {name!r} is not numeric for {row}") from exc
        if not math.isfinite(value):
            raise ValueError(f"feature {name!r} is non-finite for {row}")
        values.append(value)
    return values


def validate_rows(rows: list[dict[str, Any]]) -> None:
    keys = [row_key(row) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("target manifest contains duplicate token/source keys")
    for row in rows:
        if row.get("label") not in LABEL_TO_INT:
            raise ValueError(f"target manifest contains invalid label: {row.get('label')!r}")
        if row.get("partition") not in PARTITIONS:
            raise ValueError(f"expected a frozen 90/10 train/validation manifest, got {row.get('partition')!r}; regenerate legacy splits into a new output")
        if row.get("feature_complete") is not True:
            raise ValueError(f"target row is not feature-complete: {row}")
        row_features(row)


def apply_partition_override(rows: list[dict[str, Any]], path: Path) -> None:
    """Replace general partitions with a second, already-frozen split."""
    import pyarrow.parquet as parquet

    table = parquet.read_table(path, columns=["token_address", "source_dataset", "partition"])
    override: dict[tuple[str, str], str] = {}
    for record in table.to_pylist():
        key = (str(record["token_address"]), str(record["source_dataset"]))
        partition = record["partition"]
        if partition == "test":
            raise ValueError("legacy partition override requires a new 90/10 split")
        if partition in PARTITIONS:
            override[key] = str(partition)
    missing = [row_key(row) for row in rows if row_key(row) not in override]
    if missing:
        raise ValueError(f"partition override is missing {len(missing)} target rows")
    for row in rows:
        row["partition"] = override[row_key(row)]


def split_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result = {partition: [row for row in rows if row["partition"] == partition] for partition in PARTITIONS}
    if any(not result[partition] for partition in PARTITIONS):
        raise ValueError("target manifest must contain train and validation rows")
    if any({row['label'] for row in subset} != set(LABEL_TO_INT) for subset in result.values()):
        raise ValueError("train and validation splits must both contain both labels")
    return result


def feature_matrix(rows: list[dict[str, Any]], *, progress: str = "auto", description: str = "Features") -> np.ndarray:
    with progress_bar(rows, mode=progress, desc=description, unit="row", position=1, leave=False) as samples:
        return np.asarray([row_features(row) for row in samples], dtype=np.float64)


def labels_for(rows: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray([LABEL_TO_INT[row["label"]] for row in rows], dtype=np.int64)


def evaluate(
    model: LogisticRegression,
    rows: list[dict[str, Any]],
    features: np.ndarray,
    split: str,
    threshold: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    labels = labels_for(rows).tolist()
    scores = model.predict_proba(features)[:, 1].astype(float).tolist()
    predictions: list[dict[str, Any]] = []
    for row, label, score in zip(rows, labels, scores):
        predicted = int(score >= threshold)
        predictions.append(
            {
                "token_address": row["token_address"],
                "source_dataset": row["source_dataset"],
                "partition": row["partition"],
                "label": row["label"],
                "label_int": label,
                "score_continued_activity": score,
                "score_low_volume_dead": 1.0 - score,
                "prediction_int": predicted,
                "predicted_label": "continued_activity" if predicted else "low_volume_dead",
                "split": split,
            }
        )
    metrics = classification_metrics(labels, scores, threshold)
    metrics["split"] = split
    return metrics, predictions


def train(args: argparse.Namespace) -> dict[str, Any]:
    if args.max_iter <= 0:
        raise ValueError("max_iter must be positive")
    if args.C <= 0:
        raise ValueError("C must be positive")
    targets = Path(args.targets).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")

    rows = read_jsonl(targets)
    partition_override = Path(args.partition_override).resolve() if args.partition_override else None
    if partition_override is not None:
        apply_partition_override(rows, partition_override)
    validate_rows(rows)
    partitions = split_rows(rows)
    train_rows = partitions["train"]
    validation_rows = partitions["validation"]

    progress = getattr(args, "progress", "auto")
    with progress_bar(mode=progress, total=5, desc="Tabular: features and scaling", unit="stage") as stages:
        raw_train_x = feature_matrix(train_rows, progress=progress, description="Features: train")
        scaler = StandardScaler().fit(raw_train_x)
        train_x = scaler.transform(raw_train_x)
        validation_x = scaler.transform(feature_matrix(validation_rows, progress=progress, description="Features: validation"))
        train_y = labels_for(train_rows)
        positive_count = int(train_y.sum())
        negative_count = len(train_rows) - positive_count
        if positive_count == 0 or negative_count == 0:
            raise ValueError("training split must contain both labels for class weighting")
        positive_class_weight = negative_count / positive_count
        stages.update(1)

        stages.set_description("Tabular: logistic fit")
        model = LogisticRegression(
            C=args.C,
            class_weight={0: 1.0, 1: positive_class_weight},
            max_iter=args.max_iter,
            random_state=args.seed,
            solver=args.solver,
        )
        model.fit(train_x, train_y)
        stages.update(1)

        stages.set_description("Tabular: validation threshold")
        validation_labels = labels_for(validation_rows).tolist()
        validation_scores = model.predict_proba(validation_x)[:, 1].astype(float).tolist()
        decision_threshold = select_threshold(validation_labels, validation_scores)
        stages.update(1)
        stages.set_description("Tabular: evaluate train")
        train_metrics, train_predictions = evaluate(model, train_rows, train_x, "train", decision_threshold)
        stages.update(1)
        stages.set_description("Tabular: evaluate validation")
        validation_metrics, validation_predictions = evaluate(
            model, validation_rows, validation_x, "validation", decision_threshold
        )
        stages.update(1)

    output.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "scaler": scaler,
            "feature_names": FEATURE_NAMES,
            "seed": args.seed,
            "positive_class_weight": positive_class_weight,
            "decision_threshold_continued_activity": decision_threshold,
        },
        output / "model.joblib",
    )
    predictions = train_predictions + validation_predictions
    with (output / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")
    metrics = {
        "manifest_version": "tabular-logistic-general-stratified-0.3",
        "evaluation": evaluation_policy(),
        "final_report": final_validation_report(validation_metrics),
        "split_name": args.split_name,
        "targets": str(targets),
        "partition_override": str(partition_override) if partition_override else None,
        "output": str(output),
        "seed": args.seed,
        "model": "sklearn.linear_model.LogisticRegression over pre-cutoff token features",
        "feature_names": FEATURE_NAMES,
        "training": {
            "solver": args.solver,
            "C": args.C,
            "max_iter": args.max_iter,
            "feature_normalization": "StandardScaler fit on train rows only",
            "positive_label": "continued_activity",
            "positive_class_weight": positive_class_weight,
            "train_label_counts": {
                "continued_activity": positive_count,
                "low_volume_dead": negative_count,
            },
            "decision_threshold_selection": "validation balanced accuracy, then macro-F1",
            "decision_threshold_continued_activity": decision_threshold,
        },
        "split_counts": {partition: len(partitions[partition]) for partition in PARTITIONS},
        "metrics": {
            "train": train_metrics,
            "validation": validation_metrics,
        },
    }
    (output / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (output / "feature_normalization.json").write_text(
        json.dumps(
            {"feature_names": FEATURE_NAMES, "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist()},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return metrics


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--targets", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--partition-override")
    result.add_argument("--split-name", default="general_stratified_primary")
    result.add_argument("--seed", type=int, default=20261001)
    result.add_argument("--solver", choices=("lbfgs", "liblinear"), default="lbfgs")
    result.add_argument("--C", type=float, default=1.0)
    result.add_argument("--max-iter", type=int, default=1000)
    add_progress_arguments(result)
    return result


if __name__ == "__main__":
    print(json.dumps(train(parser().parse_args()), indent=2, sort_keys=True))
