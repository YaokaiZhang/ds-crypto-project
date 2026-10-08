#!/usr/bin/env python3
"""Render static figures from temporal-prediction analysis.json."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np


FAMILY_ORDER = ("edge_gcn", "topology_sage", "tabular_logistic")
FAMILY_LABELS = {
    "edge_gcn": "Edge GCN",
    "topology_sage": "Topology GraphSAGE",
    "tabular_logistic": "Tabular logistic",
}
LABEL_COLORS = {
    "continued_activity": "#246b73",
    "low_volume_dead": "#c65d35",
}
FAMILY_COLORS = {
    "edge_gcn": "#246b73",
    "topology_sage": "#8c6d31",
    "tabular_logistic": "#6f4e7c",
}


def read_analysis(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("analysis JSON must be an object")
    return payload


def families_in_order(analysis: dict[str, Any]) -> list[str]:
    return [family for family in FAMILY_ORDER if family in analysis["families"]]


def save_pair(fig: Any, output_dir: Path, stem: str) -> None:
    fig.savefig(output_dir / f"{stem}.png", dpi=180, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def _utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _partition_data(analysis: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    split = analysis["split"]
    quality = split["quality"]
    return quality, split["boundaries"]


def render_cohort_timeline(analysis: dict[str, Any], output_dir: Path) -> None:
    """Show the temporal windows and the observed active/inactive composition."""
    quality, boundaries = _partition_data(analysis)
    chronology = quality["chronology"]
    partition_counts = quality["partition_counts"]
    label_counts = quality["partition_label_counts"]
    partitions = ("train", "validation", "test")
    partition_colors = {
        "train": "#6f4e7c",
        "validation": "#8c6d31",
        "test": "#246b73",
    }
    active_color = LABEL_COLORS["continued_activity"]
    inactive_color = LABEL_COLORS["low_volume_dead"]

    figure, (timeline, composition) = plt.subplots(
        2,
        1,
        figsize=(12.0, 7.2),
        gridspec_kw={"height_ratios": (1.45, 1.0)},
    )
    boundary_dates = {
        "train_end": _utc_datetime(boundaries["train_end"]),
        "validation_end": _utc_datetime(boundaries["validation_end"]),
        "test_end": _utc_datetime(boundaries["test_end"]),
    }
    start_date = _utc_datetime(chronology["train"]["min_t0"])
    end_date = boundary_dates["test_end"]

    for name in partitions:
        start = _utc_datetime(chronology[name]["min_t0"])
        end = _utc_datetime(chronology[name]["max_t0"])
        left = mdates.date2num(start)
        width = mdates.date2num(end) - left
        position = len(partitions) - 1 - partitions.index(name)
        timeline.barh(
            position,
            width,
            left=left,
            height=0.46,
            color=partition_colors[name],
            alpha=0.9,
        )
        if name == "validation":
            timeline.text(
                left + width + 14,
                position,
                f"Validation  n={partition_counts[name]:,}",
                ha="left",
                va="center",
                color="#444444",
                fontsize=9,
                fontweight="bold",
            )
        else:
            timeline.text(
                left + width / 2,
                position,
                f"{name.title()}  n={partition_counts[name]:,}",
                ha="center",
                va="center",
                color="white",
                fontsize=10,
                fontweight="bold",
            )

    for date, label in (
        (boundary_dates["train_end"], "train / validation"),
        (boundary_dates["validation_end"], "validation / test"),
    ):
        timeline.axvline(mdates.date2num(date), color="#444444", linestyle="--", linewidth=1.0)
        timeline.text(
            mdates.date2num(date),
            2.72,
            label,
            rotation=90,
            va="top",
            ha="right",
            fontsize=8,
            color="#444444",
        )
    timeline.set_xlim(mdates.date2num(start_date), mdates.date2num(end_date))
    timeline.set_ylim(-0.6, 2.8)
    timeline.set_yticks((0, 1, 2), labels=("Test", "Validation", "Train"))
    timeline.xaxis_date()
    timeline.xaxis.set_major_locator(mdates.YearLocator())
    timeline.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    timeline.set_xlabel("Token start time, t0 (UTC)")
    timeline.grid(axis="x", alpha=0.22)
    timeline.set_title("Chronological cohort windows and observed token ranges", loc="left", fontweight="bold")

    positions = np.arange(len(partitions))
    active_values = [label_counts[name]["continued_activity"] for name in partitions]
    inactive_values = [label_counts[name]["low_volume_dead"] for name in partitions]
    composition.barh(
        positions,
        active_values,
        color=active_color,
        label="Active: continued_activity",
    )
    composition.barh(
        positions,
        inactive_values,
        left=active_values,
        color=inactive_color,
        label="Inactive: low_volume_dead",
    )
    for position, active, inactive in zip(positions, active_values, inactive_values):
        composition.text(active / 2, position, f"{active:,}", ha="center", va="center", color="white", fontsize=9)
        composition.text(active + inactive / 2, position, f"{inactive:,}", ha="center", va="center", color="white", fontsize=9)
    composition.set_yticks(positions, labels=("Train", "Validation", "Test"))
    composition.set_xlabel("Tokens")
    composition.set_xlim(0, max(partition_counts.values()) * 1.08)
    composition.grid(axis="x", alpha=0.22)
    composition.text(
        0.99,
        1.03,
        "Teal = active   Coral = inactive",
        transform=composition.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        color="#444444",
    )
    composition.set_title("The newest test period is failure-heavy", loc="left", fontweight="bold")

    figure.suptitle("Temporal split: older tokens train the model; newer tokens test it", y=0.98, fontsize=15, fontweight="bold")
    figure.tight_layout(rect=(0, 0, 1, 0.95))
    save_pair(figure, output_dir, "cohort_timeline")


def render_score_distributions(analysis: dict[str, Any], output_dir: Path) -> None:
    families = families_in_order(analysis)
    fig, axes = plt.subplots(2, len(families), figsize=(4.2 * len(families), 7.0), squeeze=False)
    bins = np.linspace(0.0, 1.0, 21)
    for column, family in enumerate(families):
        family_data = analysis["families"][family]
        for row_index, split in enumerate(("validation", "test")):
            axis = axes[row_index, column]
            points = family_data["score_data"][split]
            for label in ("continued_activity", "low_volume_dead"):
                values = [point["score"] for point in points if point["label"] == label]
                axis.hist(
                    values,
                    bins=bins,
                    alpha=0.62,
                    color=LABEL_COLORS[label],
                    label=label.replace("_", " "),
                    edgecolor="white",
                    linewidth=0.4,
                )
            axis.set_xlim(0.0, 1.0)
            axis.set_ylim(bottom=0)
            axis.set_xlabel("Mean failure score")
            axis.set_ylabel("Count")
            axis.grid(axis="y", alpha=0.22)
            if row_index == 0:
                axis.set_title(FAMILY_LABELS[family])
            if column == 0:
                axis.text(
                    -0.28,
                    0.5,
                    split.title(),
                    transform=axis.transAxes,
                    rotation=90,
                    va="center",
                    ha="center",
                    fontsize=10,
                    fontweight="bold",
                )
            if row_index == 0 and column == 0:
                axis.legend(frameon=False, fontsize=8)
    fig.suptitle("Temporal failure-score distributions", y=1.02, fontsize=14, fontweight="bold")
    fig.tight_layout()
    save_pair(fig, output_dir, "score_distributions")


def result_at(results: list[dict[str, Any]], target_fpr: float) -> dict[str, Any]:
    return next(
        result
        for result in results
        if abs(float(result["target_failure_positive_fpr"]) - target_fpr) < 1.0e-9
    )


def render_threshold_tradeoffs(analysis: dict[str, Any], output_dir: Path) -> None:
    families = families_in_order(analysis)
    target_fprs = [float(value) for value in analysis["target_fprs"]]
    metrics = (
        ("failure_positive_f1", "Failure F1"),
        ("dead_recall", "Failure recall"),
        ("dead_precision", "Failure precision"),
        ("failure_positive_false_positive_rate", "Actual test FPR"),
    )
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 7.4), squeeze=False)
    for axis, (metric, title) in zip(axes.flat, metrics):
        for family in families:
            results = analysis["families"][family]["ensemble"]["results"]
            values = [float(result_at(results, target)["test"][metric]) for target in target_fprs]
            axis.plot(
                target_fprs,
                values,
                marker="o",
                linewidth=2,
                color=FAMILY_COLORS[family],
                label=FAMILY_LABELS[family],
            )
        axis.set_title(title)
        axis.set_xlabel("Validation target FPR")
        axis.set_xticks(target_fprs)
        axis.set_ylim(0.0, 1.0)
        axis.grid(alpha=0.22)
    axes[0, 0].legend(frameon=False, fontsize=8, loc="lower right")
    fig.suptitle("Frozen-threshold operating points on the temporal test set", y=1.02, fontsize=14, fontweight="bold")
    fig.tight_layout()
    save_pair(fig, output_dir, "threshold_tradeoffs")


def render_model_summary(analysis: dict[str, Any], output_dir: Path) -> None:
    families = families_in_order(analysis)
    values_by_metric = {
        "ROC-AUC (dead)": [],
        "AP (dead)": [],
    }
    for family in families:
        result = result_at(analysis["families"][family]["ensemble"]["results"], 0.10)
        test = result["test"]
        values_by_metric["ROC-AUC (dead)"].append(float(test["roc_auc_low_volume_dead"]))
        values_by_metric["AP (dead)"].append(float(test["average_precision_low_volume_dead"]))
    x = np.arange(len(families))
    width = 0.36
    fig, axis = plt.subplots(figsize=(9.2, 5.2))
    axis.bar(
        x - width / 2,
        values_by_metric["ROC-AUC (dead)"],
        width,
        label="ROC-AUC",
        color="#246b73",
    )
    axis.bar(
        x + width / 2,
        values_by_metric["AP (dead)"],
        width,
        label="Average precision",
        color="#c65d35",
    )
    axis.set_xticks(x)
    axis.set_xticklabels([FAMILY_LABELS[family] for family in families])
    axis.set_ylim(0.0, 1.0)
    axis.set_ylabel("Score")
    axis.set_title("Temporal test ranking quality at the family mean")
    axis.grid(axis="y", alpha=0.22)
    axis.legend(frameon=False)
    for index, value in enumerate(values_by_metric["ROC-AUC (dead)"]):
        axis.text(index - width / 2, value + 0.018, f"{value:.3f}", ha="center", fontsize=8)
    for index, value in enumerate(values_by_metric["AP (dead)"]):
        axis.text(index + width / 2, value + 0.018, f"{value:.3f}", ha="center", fontsize=8)
    fig.tight_layout()
    save_pair(fig, output_dir, "model_summary")


def render_case_scores(analysis: dict[str, Any], output_dir: Path) -> None:
    cases = analysis["cases"]
    labels = [f"{case['case_id']} {case['token_fingerprint'][:8]}" for case in cases]
    scores = [float(case["score_low_volume_dead"]) for case in cases]
    colors = {"TP": "#246b73", "FP": "#c65d35", "FN": "#8c6d31", "TN": "#6f4e7c"}
    fig, axis = plt.subplots(figsize=(9.2, 4.9))
    positions = np.arange(len(cases))
    axis.barh(positions, scores, color=[colors[case["case_type"]] for case in cases])
    axis.axvline(
        float(cases[0]["decision_threshold_low_volume_dead"]),
        color="#333333",
        linestyle="--",
        linewidth=1.5,
        label="Frozen threshold",
    )
    axis.set_yticks(positions)
    axis.set_yticklabels(labels)
    axis.set_xlim(0.0, 1.0)
    axis.set_xlabel("Mean failure score")
    axis.set_title("Representative temporal test cases")
    axis.grid(axis="x", alpha=0.22)
    axis.legend(frameon=False)
    fig.tight_layout()
    save_pair(fig, output_dir, "case_scores")


def render_result_story(analysis: dict[str, Any], output_dir: Path) -> None:
    """Combine ranking quality, the selected confusion matrix, and FPR drift."""
    families = families_in_order(analysis)
    target_fprs = [float(value) for value in analysis["target_fprs"]]
    figure = plt.figure(figsize=(12.0, 7.7))
    grid = figure.add_gridspec(2, 2, height_ratios=(1.0, 1.0), hspace=0.42, wspace=0.28)
    ranking = figure.add_subplot(grid[0, 0])
    confusion = figure.add_subplot(grid[0, 1])
    drift = figure.add_subplot(grid[1, :])

    for family in families:
        result = result_at(analysis["families"][family]["ensemble"]["results"], 0.10)
        test = result["test"]
        x = float(test["roc_auc_low_volume_dead"])
        y = float(test["average_precision_low_volume_dead"])
        ranking.scatter(x, y, s=110, color=FAMILY_COLORS[family], zorder=3)
        ranking.annotate(
            FAMILY_LABELS[family],
            (x, y),
            xytext=(7, 5),
            textcoords="offset points",
            fontsize=9,
        )
    ranking.set_xlim(0.86, 1.0)
    ranking.set_ylim(0.90, 1.0)
    ranking.set_xlabel("ROC-AUC for inactive tokens")
    ranking.set_ylabel("Average precision for inactive tokens")
    ranking.set_title("All models rank failures well", loc="left", fontweight="bold")
    ranking.grid(alpha=0.22)

    edge_result = result_at(analysis["families"]["edge_gcn"]["ensemble"]["results"], 0.10)
    matrix = edge_result["test"]["confusion_matrix"]
    matrix_values = np.array(
        [
            [matrix["true_dead"], matrix["dead_called_active"]],
            [matrix["continued_flagged_dead"], matrix["true_continued"]],
        ]
    )
    confusion.imshow(matrix_values, cmap="BrBG", vmin=0, vmax=max(matrix_values.flatten()) * 1.1)
    for row in range(2):
        for column in range(2):
            confusion.text(column, row, f"{matrix_values[row, column]:,}", ha="center", va="center", fontsize=16, fontweight="bold")
    confusion.set_xticks((0, 1), labels=("Flag failure", "Do not flag"))
    confusion.set_yticks((0, 1), labels=("Inactive", "Active"))
    confusion.set_xlabel("Model decision")
    confusion.set_ylabel("Observed outcome")
    confusion.set_title("Edge GCN at validation target FPR 0.10", loc="left", fontweight="bold")
    confusion.text(
        0.5,
        -0.23,
        "123 caught | 22 missed | 8 false alerts | 32 correctly unflagged",
        transform=confusion.transAxes,
        ha="center",
        fontsize=9,
    )

    actual_values = [
        float(result_at(analysis["families"]["edge_gcn"]["ensemble"]["results"], target)["test"]["failure_positive_false_positive_rate"])
        for target in target_fprs
    ]
    x = np.arange(len(target_fprs))
    drift.bar(x, actual_values, color=FAMILY_COLORS["edge_gcn"], width=0.55, label="Actual test FPR")
    drift.plot(x, target_fprs, color="#555555", marker="o", linestyle="--", linewidth=1.5, label="Validation target FPR")
    for position, actual in zip(x, actual_values):
        drift.text(position, actual + 0.012, f"{actual:.3f}", ha="center", fontsize=9)
    drift.set_xticks(x, labels=[f"{target:.2f}" for target in target_fprs])
    drift.set_ylim(0.0, 0.30)
    drift.set_xlabel("Validation target FPR")
    drift.set_ylabel("False-positive rate")
    drift.set_title("The later period is less predictable at the same threshold rule", loc="left", fontweight="bold")
    drift.grid(axis="y", alpha=0.22)
    drift.legend(frameon=False, loc="upper left")

    figure.suptitle("What the temporal result means", y=0.99, fontsize=15, fontweight="bold")
    figure.subplots_adjust(left=0.08, right=0.98, bottom=0.09, top=0.90, hspace=0.42)
    save_pair(figure, output_dir, "result_story")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analysis = read_analysis(args.analysis)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    render_cohort_timeline(analysis, args.output_dir)
    render_score_distributions(analysis, args.output_dir)
    render_threshold_tradeoffs(analysis, args.output_dir)
    render_model_summary(analysis, args.output_dir)
    render_case_scores(analysis, args.output_dir)
    render_result_story(analysis, args.output_dir)
    for path in sorted(args.output_dir.glob("*.png")):
        print(path)


if __name__ == "__main__":
    main()
