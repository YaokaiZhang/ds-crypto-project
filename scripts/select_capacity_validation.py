#!/usr/bin/env python3
"""Select graph architecture and capacity from validation failure metrics only."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from scripts.evaluate_failure_predictions import (
    DEFAULT_REVIEW_BUDGET,
    DEFAULT_TARGET_FPRS,
    choose_failure_threshold,
    failure_labels_and_scores,
    precision_at_k,
)
from scripts.train_graphsage import average_precision, safe_auc


def parse_model_spec(value: str) -> tuple[str, str, Path]:
    label, separator, path = value.partition("=")
    if not separator or not label or not path:
        raise argparse.ArgumentTypeError("expected candidate:seed=predictions.jsonl")
    candidate, separator, seed = label.partition(":")
    if not separator or not candidate or not seed:
        raise argparse.ArgumentTypeError("expected candidate:seed=predictions.jsonl")
    return candidate, seed, Path(path)


def read_validation_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            if row.get("split") == "validation":
                rows.append(row)
    return rows


def evaluate_validation_model(
    source: Path, target_fprs: list[float], review_k: int
) -> dict[str, Any]:
    validation_rows = read_validation_rows(source)
    labels, scores = failure_labels_and_scores(validation_rows)
    result: dict[str, Any] = {
        "predictions": str(source),
        "validation_rows": len(validation_rows),
        "roc_auc_low_volume_dead": safe_auc(labels, scores),
        "average_precision_low_volume_dead": average_precision(labels, scores),
        "precision_at_k": precision_at_k(labels, scores, review_k),
        "by_target_fpr": {},
    }
    for target_fpr in sorted(set(target_fprs)):
        threshold, metrics = choose_failure_threshold(labels, scores, target_fpr)
        result["by_target_fpr"][str(target_fpr)] = {
            "threshold_score_low_volume_dead": threshold,
            "failure_positive_f1": metrics["failure_positive_f1"],
            "dead_precision": metrics["dead_precision"],
            "dead_recall": metrics["dead_recall"],
            "failure_positive_false_positive_rate": metrics[
                "failure_positive_false_positive_rate"
            ],
            "macro_f1": metrics["macro_f1"],
        }
    return result


def mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return sum(materialized) / len(materialized)


def complexity_key(candidate: str) -> int:
    hidden_width = int(candidate.split("hidden", 1)[1].split("_", 1)[0])
    layers = int(candidate.split("layers", 1)[1])
    return hidden_width * layers


def aggregate_candidate(
    candidate: str,
    models: list[tuple[str, Path]],
    target_fprs: list[float],
    review_k: int,
) -> dict[str, Any]:
    if not models:
        raise ValueError(f"candidate {candidate!r} has no models")
    per_model = [
        {"seed": seed, **evaluate_validation_model(path, target_fprs, review_k)}
        for seed, path in sorted(models)
    ]
    by_target_fpr: dict[str, dict[str, float]] = {}
    for target_fpr in sorted(set(target_fprs)):
        key = str(target_fpr)
        by_target_fpr[key] = {
            metric: mean(
                float(model["by_target_fpr"][key][metric]) for model in per_model
            )
            for metric in (
                "failure_positive_f1",
                "dead_precision",
                "dead_recall",
                "failure_positive_false_positive_rate",
                "macro_f1",
            )
        }
    mean_f1 = mean(
        value["failure_positive_f1"] for value in by_target_fpr.values()
    )
    return {
        "candidate": candidate,
        "model_count": len(per_model),
        "models": per_model,
        "validation_mean": {
            "failure_positive_f1_across_fpr_budgets": mean_f1,
            "roc_auc_low_volume_dead": mean(
                float(model["roc_auc_low_volume_dead"]) for model in per_model
            ),
            "average_precision_low_volume_dead": mean(
                float(model["average_precision_low_volume_dead"]) for model in per_model
            ),
            "precision_at_k": mean(float(model["precision_at_k"]) for model in per_model),
            "by_target_fpr": by_target_fpr,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", type=parse_model_spec, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-k", type=int, default=DEFAULT_REVIEW_BUDGET)
    parser.add_argument(
        "--target-fpr", action="append", type=float, default=list(DEFAULT_TARGET_FPRS)
    )
    args = parser.parse_args()
    if args.review_k <= 0:
        raise SystemExit("--review-k must be positive")

    grouped: defaultdict[str, list[tuple[str, Path]]] = defaultdict(list)
    for candidate, seed, path in args.model:
        grouped[candidate].append((seed, path))
    candidates = [
        aggregate_candidate(candidate, models, args.target_fpr, args.review_k)
        for candidate, models in sorted(grouped.items())
    ]
    for candidate in candidates:
        if candidate["model_count"] != 3:
            raise SystemExit(
                f"candidate {candidate['candidate']!r} has {candidate['model_count']} models; expected 3 seeds"
            )

    selected = max(
        candidates,
        key=lambda item: (
            item["validation_mean"]["failure_positive_f1_across_fpr_budgets"],
            item["validation_mean"]["average_precision_low_volume_dead"],
            item["validation_mean"]["precision_at_k"],
            -complexity_key(item["candidate"]),
        ),
    )
    output = {
        "selection": {
            "selected_candidate": selected["candidate"],
            "review_k": args.review_k,
            "target_failure_positive_fprs": sorted(set(args.target_fpr)),
            "rule": (
                "select the candidate with the highest mean validation failure-positive F1 "
                "across the 5%, 10%, and 15% FPR budgets; break ties by mean validation "
                "failure-positive average precision, then validation precision@K, then "
                "smaller parameter-width product"
            ),
            "test_rows_used": False,
        },
        "candidates": candidates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["selection"], indent=2))


if __name__ == "__main__":
    main()
