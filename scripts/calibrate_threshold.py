#!/usr/bin/env python3
"""Choose validation-only thresholds under false-positive-rate budgets."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from scripts.train_graphsage import classification_metrics


VALIDATION_SPLITS = frozenset(("validation",))
TEST_SPLITS = frozenset(("test", "test_holdout"))


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


def labels_and_scores(rows: list[dict[str, Any]]) -> tuple[list[int], list[float]]:
    labels: list[int] = []
    scores: list[float] = []
    for row in rows:
        label = int(row["label_int"])
        score = float(row["score_continued_activity"])
        if label not in (0, 1) or not math.isfinite(score):
            raise ValueError(f"invalid prediction row: {row}")
        labels.append(label)
        scores.append(score)
    if not labels:
        raise ValueError("cannot calibrate without rows")
    return labels, scores


def choose_threshold(labels: list[int], scores: list[float], target_fpr: float) -> tuple[float, dict[str, Any]]:
    if not 0.0 <= target_fpr <= 1.0:
        raise ValueError("target_fpr must be between 0 and 1")
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        raise ValueError("calibration requires both labels")

    # Sweep unique score levels once.  Recomputing ranking metrics at every
    # candidate threshold is unnecessary and makes calibration quadratic.
    ordered = sorted(zip(scores, labels), reverse=True)
    best: tuple[tuple[float, float, float], float] | None = None
    true_positive = 0
    false_positive = 0
    position = 0
    while position < len(ordered):
        threshold = ordered[position][0]
        end = position
        while end < len(ordered) and ordered[end][0] == threshold:
            if ordered[end][1] == 1:
                true_positive += 1
            else:
                false_positive += 1
            end += 1
        false_negative = positives - true_positive
        false_positive_rate = false_positive / negatives
        recall = true_positive / positives
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if false_positive_rate <= target_fpr + 1.0e-12:
            key = (recall, f1, -threshold)
            if best is None or key > best[0]:
                best = (key, threshold)
        position = end

    # The threshold above the maximum score represents the all-negative choice.
    if best is None:
        best = ((0.0, 0.0, -(max(scores) + 1.0e-12)), max(scores) + 1.0e-12)
    threshold = best[1]
    return threshold, classification_metrics(labels, scores, threshold)


def calibrate(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.predictions).resolve()
    output = Path(args.output).resolve()
    rows = read_jsonl(source)
    validation_rows = [row for row in rows if row.get("split") in VALIDATION_SPLITS]
    test_rows = [row for row in rows if row.get("split") in TEST_SPLITS]
    validation_labels, validation_scores = labels_and_scores(validation_rows)
    test_labels, test_scores = labels_and_scores(test_rows)
    budgets = sorted(set(float(value) for value in args.target_fpr))
    results: list[dict[str, Any]] = []
    for budget in budgets:
        threshold, validation_metrics = choose_threshold(validation_labels, validation_scores, budget)
        test_metrics = classification_metrics(test_labels, test_scores, threshold)
        results.append(
            {
                "target_false_positive_rate": budget,
                "threshold": threshold,
                "validation": validation_metrics,
                "test": test_metrics,
            }
        )
    result = {
        "manifest_version": "validation-fpr-threshold-calibration-0.1",
        "predictions": str(source),
        "validation_rows": len(validation_rows),
        "test_rows": len(test_rows),
        "calibration_rule": "choose the validation threshold with maximum continued-activity recall subject to the target FPR; break ties by continued-activity F1",
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--predictions", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--target-fpr", type=float, action="append", default=[0.05, 0.10, 0.15])
    return result


if __name__ == "__main__":
    print(json.dumps(calibrate(parser().parse_args()), indent=2, sort_keys=True))
