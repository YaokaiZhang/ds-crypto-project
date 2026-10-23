#!/usr/bin/env python3
"""Evaluate native prediction artifacts with low-volume failure as positive."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.train_graphsage import average_precision, safe_auc


VALIDATION_SPLITS = frozenset(("validation",))
TEST_SPLITS = frozenset(("test", "test_holdout"))
DEFAULT_TARGET_FPRS = (0.05, 0.10, 0.15)
DEFAULT_REVIEW_BUDGET = 20


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            rows.append(row)
    return rows


def _validate_labels_and_scores(labels: list[int], scores: list[float]) -> None:
    if len(labels) != len(scores):
        raise ValueError("labels and scores must have the same length")
    if not labels:
        raise ValueError("cannot evaluate without rows")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("labels must contain only 0 and 1")
    if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in scores):
        raise ValueError("scores must be finite probabilities between 0 and 1")


def failure_labels_and_scores(rows: list[dict[str, Any]]) -> tuple[list[int], list[float]]:
    """Invert native continued-positive rows for the failure objective."""
    labels: list[int] = []
    scores: list[float] = []
    for row in rows:
        try:
            native_label = int(row["label_int"])
            native_score = float(row["score_continued_activity"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid prediction row: {row}") from exc
        if native_label not in (0, 1) or not math.isfinite(native_score) or not 0.0 <= native_score <= 1.0:
            raise ValueError(f"invalid prediction row: {row}")
        labels.append(1 - native_label)
        scores.append(1.0 - native_score)
    _validate_labels_and_scores(labels, scores)
    return labels, scores


def _top_k_metrics(labels: list[int], scores: list[float], k: int) -> dict[str, float | int]:
    _validate_labels_and_scores(labels, scores)
    if not 1 <= k <= len(labels):
        raise ValueError(f"k must be between 1 and {len(labels)}")
    ranked_indices = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    dead_hits = sum(labels[index] for index in ranked_indices[:k])
    dead_support = sum(labels)
    precision = dead_hits / k
    recall = dead_hits / dead_support if dead_support else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "k": k,
        "dead_hits": dead_hits,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def precision_at_k(labels: list[int], scores: list[float], k: int) -> float:
    """Return dead-token precision among the top-k failure scores."""
    return float(_top_k_metrics(labels, scores, k)["precision"])


def choose_review_k(
    validation_sets: list[tuple[list[int], list[float]]], review_budget: int
) -> tuple[int, dict[str, Any]]:
    """Choose one review K from validation F1 across all supplied models."""
    if review_budget <= 0:
        raise ValueError("review_budget must be positive")
    if not validation_sets:
        raise ValueError("at least one validation set is required")
    for labels, scores in validation_sets:
        _validate_labels_and_scores(labels, scores)

    maximum_k = min(review_budget, *(len(labels) for labels, _ in validation_sets))
    candidates: list[dict[str, Any]] = []
    for k in range(1, maximum_k + 1):
        per_model = [_top_k_metrics(labels, scores, k) for labels, scores in validation_sets]
        mean_precision = sum(float(item["precision"]) for item in per_model) / len(per_model)
        mean_recall = sum(float(item["recall"]) for item in per_model) / len(per_model)
        mean_f1 = sum(float(item["f1"]) for item in per_model) / len(per_model)
        candidates.append(
            {
                "k": k,
                "mean_precision": mean_precision,
                "mean_recall": mean_recall,
                "mean_f1": mean_f1,
            }
        )
    selected = max(
        candidates,
        key=lambda item: (float(item["mean_f1"]), float(item["mean_precision"]), -int(item["k"])),
    )
    return int(selected["k"]), {
        "review_budget": review_budget,
        "selected_k": int(selected["k"]),
        "selection_rule": (
            "select K from 1 through the analyst review budget by maximum mean "
            "validation failure-positive F1 across models; break ties by mean precision, "
            "then choose the smaller K"
        ),
        "candidates": candidates,
    }


def failure_metrics(
    labels: list[int],
    scores: list[float],
    threshold: float,
    review_k: int | None = None,
) -> dict[str, Any]:
    """Calculate metrics where low_volume_dead (label 1) is the positive class."""
    _validate_labels_and_scores(labels, scores)
    if not math.isfinite(threshold):
        raise ValueError("threshold must be finite")

    true_dead = sum(label == 1 and score >= threshold for label, score in zip(labels, scores))
    continued_flagged_dead = sum(label == 0 and score >= threshold for label, score in zip(labels, scores))
    dead_called_active = sum(label == 1 and score < threshold for label, score in zip(labels, scores))
    true_continued = sum(label == 0 and score < threshold for label, score in zip(labels, scores))
    dead_support = true_dead + dead_called_active
    continued_support = true_continued + continued_flagged_dead

    dead_precision = true_dead / (true_dead + continued_flagged_dead) if true_dead + continued_flagged_dead else 0.0
    dead_recall = true_dead / dead_support if dead_support else 0.0
    continued_precision = true_continued / (true_continued + dead_called_active) if true_continued + dead_called_active else 0.0
    continued_recall = true_continued / continued_support if continued_support else 0.0
    failure_positive_f1 = (
        2 * dead_precision * dead_recall / (dead_precision + dead_recall)
        if dead_precision + dead_recall else 0.0
    )
    continued_f1 = (
        2 * continued_precision * continued_recall / (continued_precision + continued_recall)
        if continued_precision + continued_recall else 0.0
    )

    metrics: dict[str, Any] = {
        "rows": len(labels),
        "support": {
            "low_volume_dead": dead_support,
            "continued_activity": continued_support,
        },
        "label_counts": dict(Counter("low_volume_dead" if label else "continued_activity" for label in labels)),
        "accuracy": (true_dead + true_continued) / len(labels),
        "balanced_accuracy": (dead_recall + continued_recall) / 2,
        "roc_auc_low_volume_dead": safe_auc(labels, scores),
        "average_precision_low_volume_dead": average_precision(labels, scores),
        "dead_precision": dead_precision,
        "dead_recall": dead_recall,
        "failure_positive_f1": failure_positive_f1,
        "continued_precision": continued_precision,
        "continued_recall": continued_recall,
        "continued_f1": continued_f1,
        "macro_f1": (failure_positive_f1 + continued_f1) / 2,
        "failure_positive_false_positive_rate": (
            continued_flagged_dead / continued_support if continued_support else None
        ),
        "false_active_rate": dead_called_active / dead_support if dead_support else None,
        "decision_threshold_low_volume_dead": threshold,
        "confusion_matrix": {
            "true_dead": true_dead,
            "continued_flagged_dead": continued_flagged_dead,
            "dead_called_active": dead_called_active,
            "true_continued": true_continued,
        },
    }
    if review_k is not None:
        metrics["review_k"] = review_k
        metrics["precision_at_k"] = precision_at_k(labels, scores, review_k)
    return metrics


def choose_failure_threshold(
    labels: list[int], scores: list[float], target_fpr: float
) -> tuple[float, dict[str, Any]]:
    """Choose a validation threshold under a dead-positive FPR budget."""
    _validate_labels_and_scores(labels, scores)
    if not 0.0 <= target_fpr <= 1.0:
        raise ValueError("target_fpr must be between 0 and 1")
    dead_count = sum(labels)
    continued_count = len(labels) - dead_count
    if dead_count == 0 or continued_count == 0:
        raise ValueError("threshold selection requires both labels")

    ordered = sorted(zip(scores, labels), reverse=True)
    best: tuple[tuple[float, float, float], float] | None = None
    true_dead = 0
    continued_flagged_dead = 0
    position = 0
    while position < len(ordered):
        threshold = ordered[position][0]
        end = position
        while end < len(ordered) and ordered[end][0] == threshold:
            if ordered[end][1] == 1:
                true_dead += 1
            else:
                continued_flagged_dead += 1
            end += 1
        dead_recall = true_dead / dead_count
        failure_positive_fpr = continued_flagged_dead / continued_count
        dead_precision = true_dead / (true_dead + continued_flagged_dead) if true_dead + continued_flagged_dead else 0.0
        failure_positive_f1 = (
            2 * dead_precision * dead_recall / (dead_precision + dead_recall)
            if dead_precision + dead_recall else 0.0
        )
        if failure_positive_fpr <= target_fpr + 1.0e-12:
            key = (dead_recall, failure_positive_f1, -threshold)
            if best is None or key > best[0]:
                best = (key, threshold)
        position = end

    if best is None:
        best = ((0.0, 0.0, -(max(scores) + 1.0e-12)), max(scores) + 1.0e-12)
    threshold = best[1]
    return threshold, failure_metrics(labels, scores, threshold)


def evaluate_model(
    source: Path,
    target_fprs: list[float],
    review_k: int,
) -> dict[str, Any]:
    rows = read_jsonl(source)
    validation_rows = [row for row in rows if row.get("split") in VALIDATION_SPLITS]
    test_rows = [row for row in rows if row.get("split") in TEST_SPLITS]
    validation_labels, validation_scores = failure_labels_and_scores(validation_rows)
    test_labels, test_scores = failure_labels_and_scores(test_rows)
    results: list[dict[str, Any]] = []
    for target_fpr in sorted(set(target_fprs)):
        threshold, validation_metrics = choose_failure_threshold(
            validation_labels, validation_scores, target_fpr
        )
        validation_metrics["review_k"] = review_k
        validation_metrics["precision_at_k"] = precision_at_k(
            validation_labels, validation_scores, review_k
        )
        test_metrics = failure_metrics(test_labels, test_scores, threshold, review_k)
        results.append(
            {
                "target_failure_positive_fpr": target_fpr,
                "threshold_score_low_volume_dead": threshold,
                "validation": validation_metrics,
                "test": test_metrics,
            }
        )
    return {
        "predictions": str(source),
        "validation_rows": len(validation_rows),
        "test_rows": len(test_rows),
        "results": results,
    }


def parse_model_spec(value: str) -> tuple[str, Path]:
    name, separator, path = value.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("model must use NAME=PATH")
    return name, Path(path).resolve()


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output).resolve()
    validation_sets = []
    for _, source in args.model:
        rows = read_jsonl(source)
        validation_rows = [row for row in rows if row.get("split") in VALIDATION_SPLITS]
        validation_sets.append(failure_labels_and_scores(validation_rows))
    review_k, review_k_selection = choose_review_k(validation_sets, args.review_budget)
    model_results = []
    for name, source in args.model:
        result = evaluate_model(source, args.target_fpr, review_k)
        result["model"] = name
        model_results.append(result)
    result = {
        "manifest_version": "failure-positive-evaluation-0.1",
        "objective": {
            "positive_label": "low_volume_dead",
            "failure_label_rule": "failure_label = 1 - label_int",
            "failure_score_rule": "score_low_volume_dead = 1 - score_continued_activity",
        },
        "threshold_rule": (
            "choose the validation threshold with maximum low-volume-dead recall "
            "subject to the target failure-positive FPR; break ties by failure-positive F1"
        ),
        "review_budget": {
            **review_k_selection,
        },
        "target_failure_positive_fprs": sorted(set(args.target_fpr)),
        "models": model_results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--model", action="append", type=parse_model_spec, required=True, metavar="NAME=PATH")
    result.add_argument("--output", required=True)
    result.add_argument("--review-budget", type=int, default=DEFAULT_REVIEW_BUDGET)
    result.add_argument("--target-fpr", type=float, action="append", default=list(DEFAULT_TARGET_FPRS))
    return result


if __name__ == "__main__":
    print(json.dumps(evaluate(parser().parse_args()), indent=2, sort_keys=True))
