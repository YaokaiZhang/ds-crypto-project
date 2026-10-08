#!/usr/bin/env python3
"""Render the result-analysis figures, report, and token case demo.

This phase runs in the remote base Conda environment, which has pandas,
matplotlib, and scikit-learn. It consumes the reproducible JSON emitted by
prepare_result_analysis.py and does not fit a new model or tune a threshold.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import textwrap
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch


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

FEATURE_LABELS = {
    "event_count": "Event count",
    "swap_count": "Swap count",
    "mint_count": "Mint count",
    "burn_count": "Burn count",
    "pre_cutoff_volume_usd": "Pre-cutoff volume",
    "pre_cutoff_missing_swap_usd_count": "Missing swap USD",
    "active_day_count": "Active days",
    "pool_count": "Pool count",
    "protocol_count": "Protocol count",
}

COLORS = {
    "ink": "#24323A",
    "muted": "#66757C",
    "grid": "#D9E0DE",
    "paper": "#FBFAF7",
    "active": "#287D8E",
    "dead": "#D6614B",
    "green": "#5D9A78",
    "gold": "#D9A441",
    "purple": "#8064A2",
    "red": "#B84C5A",
}

MODEL_COLORS = {
    "Edge GCN": COLORS["red"],
    "Topology GraphSAGE": COLORS["active"],
    "Tabular logistic": COLORS["gold"],
}

MODEL_ORDER = ["Edge GCN", "Topology GraphSAGE", "Tabular logistic"]
SPLIT_ORDER = ["general_stratified", "temporal"]
SPLIT_LABELS = {
    "general_stratified": "General stratified",
    "temporal": "Temporal holdout",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tabular-model", type=Path, required=True)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def save_figure(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=190, bbox_inches="tight", facecolor=COLORS["paper"])
    plt.close(fig)


def configure_plot() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "axes.edgecolor": COLORS["grid"],
            "axes.labelcolor": COLORS["ink"],
            "axes.titlecolor": COLORS["ink"],
            "xtick.color": COLORS["muted"],
            "ytick.color": COLORS["muted"],
            "text.color": COLORS["ink"],
            "axes.facecolor": COLORS["paper"],
            "figure.facecolor": COLORS["paper"],
            "axes.grid": True,
            "grid.color": COLORS["grid"],
            "grid.linewidth": 0.7,
            "grid.alpha": 0.75,
            "legend.frameon": False,
            "figure.constrained_layout.use": True,
        }
    )


def compact(value: float | int, digits: int = 1) -> str:
    if isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
        return "NA"
    number = float(value)
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.{digits}f}M"
    if abs(number) >= 1_000:
        return f"{number / 1_000:.{digits}f}k"
    if number.is_integer():
        return str(int(number))
    return f"{number:.{digits}f}"


def pct(value: float, digits: int = 1) -> str:
    return f"{100 * float(value):.{digits}f}%"


def as_dataframes(data: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = pd.DataFrame(data["rows"])
    for feature in FEATURE_NAMES:
        rows[feature] = pd.to_numeric(rows[feature], errors="coerce")
    evaluation = pd.DataFrame(data["evaluation_rows"])
    scores = pd.DataFrame(data["score_rows"])
    return rows, evaluation, scores


def feature_statistics(rows: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for feature in FEATURE_NAMES:
        values = rows[feature]
        for label in ["continued_activity", "low_volume_dead"]:
            group = values[rows["label"] == label]
            records.append(
                {
                    "feature": feature,
                    "label": label,
                    "n": int(group.count()),
                    "median": float(group.median()),
                    "q1": float(group.quantile(0.25)),
                    "q3": float(group.quantile(0.75)),
                    "zero_share": float((group == 0).mean()),
                    "missing_share": float(group.isna().mean()),
                }
            )
    return pd.DataFrame(records)


def unique_metric_rows(evaluation: pd.DataFrame) -> pd.DataFrame:
    evaluation = preferred_evaluation(evaluation)
    columns = ["analysis_split", "model", "model_run", "test_roc_auc", "test_average_precision"]
    return evaluation[columns].drop_duplicates(["analysis_split", "model", "model_run"])


def preferred_evaluation(evaluation: pd.DataFrame) -> pd.DataFrame:
    """Prefer saved ensemble metrics where the project computed them."""
    if "evaluation_level" not in evaluation:
        return evaluation
    pieces = []
    for _, group in evaluation.groupby(["analysis_split", "model"], sort=False):
        if (group["evaluation_level"] == "ensemble").any():
            pieces.append(group[group["evaluation_level"] == "ensemble"])
        else:
            pieces.append(group)
    return pd.concat(pieces, ignore_index=True) if pieces else evaluation.iloc[0:0]


def model_summary(evaluation: pd.DataFrame) -> pd.DataFrame:
    unique = unique_metric_rows(evaluation)
    grouped = (
        unique.groupby(["analysis_split", "model"], as_index=False)
        .agg(
            roc_auc_mean=("test_roc_auc", "mean"),
            roc_auc_sd=("test_roc_auc", "std"),
            average_precision_mean=("test_average_precision", "mean"),
            average_precision_sd=("test_average_precision", "std"),
            seed_count=("model_run", "nunique"),
        )
        .fillna(0.0)
    )
    return grouped


def operating_summary(evaluation: pd.DataFrame) -> pd.DataFrame:
    evaluation = preferred_evaluation(evaluation)
    columns = [
        "analysis_split",
        "model",
        "model_run",
        "target_failure_positive_fpr",
        "test_fpr",
        "test_failure_recall",
        "test_failure_precision",
        "test_failure_f1",
        "test_alerts",
        "precision_at_k",
    ]
    return evaluation[columns].groupby(
        ["analysis_split", "model", "target_failure_positive_fpr"], as_index=False
    ).agg(
        test_fpr=("test_fpr", "mean"),
        test_fpr_sd=("test_fpr", "std"),
        failure_recall=("test_failure_recall", "mean"),
        failure_precision=("test_failure_precision", "mean"),
        failure_f1=("test_failure_f1", "mean"),
        alerts=("test_alerts", "mean"),
        precision_at_k=("precision_at_k", "mean"),
        seed_count=("model_run", "nunique"),
    ).fillna(0.0)


def render_cohort_balance(rows: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 5.0))
    for axis, column, title, order in [
        (axes[0], "general_partition", "General stratified split", ["train", "validation", "test"]),
        (axes[1], "temporal_partition", "Chronological stress test", ["train", "validation", "test"]),
    ]:
        table = rows.groupby([column, "label"]).size().unstack(fill_value=0).reindex(order)
        active = table.get("continued_activity", pd.Series(index=order, data=0))
        dead = table.get("low_volume_dead", pd.Series(index=order, data=0))
        axis.bar(order, active, color=COLORS["active"], label="continued activity")
        axis.bar(order, dead, bottom=active, color=COLORS["dead"], label="low-volume dead")
        axis.set_title(title)
        axis.set_ylabel("Tokens")
        axis.tick_params(axis="x", rotation=18)
        for index, total in enumerate((active + dead).tolist()):
            axis.text(index, total + max(total * 0.02, 5), str(int(total)), ha="center", va="bottom", fontsize=9)
        axis.spines[["top", "right"]].set_visible(False)
    year_table = rows.groupby(["launch_period", "label"]).size().unstack(fill_value=0).sort_index()
    dead_share = year_table.get("low_volume_dead", 0) / year_table.sum(axis=1)
    axes[2].plot(year_table.index.astype(str), dead_share, marker="o", color=COLORS["dead"], linewidth=2.4)
    axes[2].axhline(0.5, color=COLORS["muted"], linestyle="--", linewidth=1)
    axes[2].set_ylim(0, 1)
    axes[2].set_title("Low-volume prevalence by launch period")
    axes[2].set_ylabel("Share low-volume dead")
    axes[2].set_xlabel("Launch period")
    axes[2].tick_params(axis="x", rotation=25)
    axes[2].spines[["top", "right"]].set_visible(False)
    handles = [Patch(facecolor=COLORS["active"], label="continued activity"), Patch(facecolor=COLORS["dead"], label="low-volume dead")]
    fig.legend(handles=handles, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Cohort composition and time drift", x=0.03, ha="left", fontsize=16, fontweight="bold")
    save_figure(fig, path)


def render_feature_distributions(rows: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(3, 3, figsize=(14, 11))
    for axis, feature in zip(axes.flat, FEATURE_NAMES):
        active = np.log1p(rows.loc[rows["label"] == "continued_activity", feature].dropna())
        dead = np.log1p(rows.loc[rows["label"] == "low_volume_dead", feature].dropna())
        result = axis.boxplot(
            [active, dead],
            positions=[1, 2],
            widths=0.58,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": COLORS["ink"], "linewidth": 1.5},
            whiskerprops={"color": COLORS["muted"]},
            capprops={"color": COLORS["muted"]},
        )
        result["boxes"][0].set_facecolor(COLORS["active"])
        result["boxes"][0].set_alpha(0.72)
        result["boxes"][1].set_facecolor(COLORS["dead"])
        result["boxes"][1].set_alpha(0.72)
        axis.set_title(FEATURE_LABELS[feature])
        axis.set_xticks([1, 2], ["active", "dead"])
        axis.set_ylabel("log1p(value)")
        axis.spines[["top", "right"]].set_visible(False)
        if float(rows[feature].max()) == 0:
            axis.text(1.5, 0.05, "all values are zero", ha="center", va="bottom", fontsize=8, color=COLORS["muted"])
    fig.suptitle("Early feature distributions by observed 90-day outcome", x=0.03, ha="left", fontsize=16, fontweight="bold")
    save_figure(fig, path)


def render_feature_quality(rows: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), sharey=True)
    labels = [FEATURE_LABELS[feature] for feature in FEATURE_NAMES]
    zero_share = [(rows[feature] == 0).mean() for feature in FEATURE_NAMES]
    missing_share = [rows[feature].isna().mean() for feature in FEATURE_NAMES]
    positions = np.arange(len(FEATURE_NAMES))
    axes[0].barh(positions, zero_share, color=COLORS["gold"])
    axes[0].set_title("Zero-valued share")
    axes[0].set_xlabel("Share of 2,000 rows")
    axes[0].set_yticks(positions, labels)
    axes[0].invert_yaxis()
    axes[1].barh(positions, missing_share, color=COLORS["purple"])
    axes[1].set_title("Missing-value share")
    axes[1].set_xlabel("Share of 2,000 rows")
    axes[1].set_yticks(positions, [])
    for axis, values in zip(axes, [zero_share, missing_share]):
        axis.set_xlim(0, max(1.0, max(values) * 1.14))
        for position, value in zip(positions, values):
            axis.text(value + 0.015, position, pct(value), va="center", fontsize=8)
        axis.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Feature quality is complete, but several channels are sparse", x=0.03, ha="left", fontsize=16, fontweight="bold")
    save_figure(fig, path)


def render_correlation(rows: pd.DataFrame, path: Path) -> None:
    matrix = rows[FEATURE_NAMES].corr(method="spearman")
    display_labels = [FEATURE_LABELS[feature].replace("Pre-cutoff ", "").replace("Missing swap USD", "Missing USD") for feature in FEATURE_NAMES]
    cmap = LinearSegmentedColormap.from_list("result_analysis_corr", [COLORS["active"], COLORS["paper"], COLORS["dead"]])
    fig, axis = plt.subplots(figsize=(11, 9))
    image = axis.imshow(matrix.to_numpy(dtype=float), vmin=-1, vmax=1, cmap=cmap)
    axis.set_xticks(range(len(FEATURE_NAMES)), display_labels, rotation=45, ha="right")
    axis.set_yticks(range(len(FEATURE_NAMES)), display_labels)
    for row_index in range(len(FEATURE_NAMES)):
        for column_index in range(len(FEATURE_NAMES)):
            value = matrix.iloc[row_index, column_index]
            if pd.notna(value):
                axis.text(column_index, row_index, f"{value:.2f}", ha="center", va="center", fontsize=8, color=COLORS["ink"])
    axis.set_title("Spearman redundancy view across the full cohort", loc="left", pad=14)
    colorbar = fig.colorbar(image, ax=axis, fraction=0.035, pad=0.04)
    colorbar.set_label("Spearman correlation")
    save_figure(fig, path)


def render_model_comparison(evaluation: pd.DataFrame, path: Path) -> None:
    summary = model_summary(evaluation)
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharey="row")
    metrics = [("roc_auc_mean", "roc_auc_sd", "ROC-AUC"), ("average_precision_mean", "average_precision_sd", "Average precision")]
    for row_index, split in enumerate(SPLIT_ORDER):
        subset = summary[summary["analysis_split"] == split].set_index("model").reindex(MODEL_ORDER)
        for column_index, (mean_name, sd_name, title) in enumerate(metrics):
            axis = axes[row_index, column_index]
            values = subset[mean_name].to_numpy(dtype=float)
            errors = subset[sd_name].to_numpy(dtype=float)
            axis.bar(np.arange(len(MODEL_ORDER)), values, yerr=errors, capsize=4, color=[MODEL_COLORS[name] for name in MODEL_ORDER], alpha=0.88)
            axis.set_xticks(np.arange(len(MODEL_ORDER)), ["Edge GCN", "GraphSAGE", "Tabular"], rotation=18)
            axis.set_ylim(0.84 if title == "ROC-AUC" else 0.88, 1.0)
            axis.set_title(f"{SPLIT_LABELS[split]}: {title}")
            axis.set_ylabel(title)
            axis.spines[["top", "right"]].set_visible(False)
            for position, value in enumerate(values):
                axis.text(position, value + 0.006, f"{value:.3f}", ha="center", va="bottom", fontsize=8)
    fig.suptitle("Ranking quality is strong, but the temporal comparison changes the ordering", x=0.03, ha="left", fontsize=16, fontweight="bold")
    save_figure(fig, path)


def render_operating_tradeoffs(evaluation: pd.DataFrame, path: Path) -> None:
    operating = operating_summary(evaluation)
    dimensions = [
        ("failure_recall", "Failure recall", (0.55, 1.0)),
        ("failure_precision", "Failure precision", (0.75, 1.0)),
        ("failure_f1", "Failure F1", (0.65, 0.98)),
        ("test_fpr", "Realized test FPR", (0.0, 0.30)),
    ]
    fig, axes = plt.subplots(2, 4, figsize=(17, 8), sharex=True)
    for row_index, split in enumerate(SPLIT_ORDER):
        for column_index, (metric, title, limits) in enumerate(dimensions):
            axis = axes[row_index, column_index]
            for model in MODEL_ORDER:
                subset = operating[(operating["analysis_split"] == split) & (operating["model"] == model)].sort_values("target_failure_positive_fpr")
                if subset.empty:
                    continue
                axis.plot(
                    subset["target_failure_positive_fpr"],
                    subset[metric],
                    marker="o",
                    linewidth=2.0,
                    color=MODEL_COLORS[model],
                    label=model,
                )
            axis.set_title(f"{SPLIT_LABELS[split]}: {title}")
            axis.set_ylim(*limits)
            axis.set_xticks([0.05, 0.10, 0.15], ["5%", "10%", "15%"])
            axis.set_xlabel("Validation FPR budget")
            axis.set_ylabel(title)
            axis.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    axes[0, 0].legend(handles, labels, loc="lower right", fontsize=8)
    fig.suptitle("Validation operating budgets do not guarantee the same temporal test FPR", x=0.03, ha="left", fontsize=16, fontweight="bold")
    save_figure(fig, path)


def render_score_distributions(scores: pd.DataFrame, evaluation: pd.DataFrame, path: Path) -> None:
    evaluation = preferred_evaluation(evaluation)
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), sharey=True)
    for row_index, split in enumerate(SPLIT_ORDER):
        for column_index, model in enumerate(MODEL_ORDER):
            axis = axes[row_index, column_index]
            subset = scores[(scores["analysis_split"] == split) & (scores["partition"] == "test") & (scores["model"] == model)]
            active = subset.loc[subset["label"] == "continued_activity", "score_low_volume_dead"]
            dead = subset.loc[subset["label"] == "low_volume_dead", "score_low_volume_dead"]
            if len(active) and len(dead):
                result = axis.boxplot(
                    [active, dead],
                    positions=[1, 2],
                    widths=0.58,
                    patch_artist=True,
                    showfliers=False,
                    medianprops={"color": COLORS["ink"], "linewidth": 1.5},
                    whiskerprops={"color": COLORS["muted"]},
                    capprops={"color": COLORS["muted"]},
                )
                result["boxes"][0].set_facecolor(COLORS["active"])
                result["boxes"][1].set_facecolor(COLORS["dead"])
                for box in result["boxes"]:
                    box.set_alpha(0.72)
            threshold = evaluation[
                (evaluation["analysis_split"] == split)
                & (evaluation["model"] == model)
                & np.isclose(evaluation["target_failure_positive_fpr"], 0.10)
            ]["threshold"].mean()
            axis.axhline(threshold, color=COLORS["gold"], linestyle="--", linewidth=1.5)
            axis.set_title(f"{SPLIT_LABELS[split]}: {model}")
            axis.set_xticks([1, 2], ["continued", "dead"])
            axis.set_ylim(0, 1.02)
            axis.set_ylabel("Failure score")
            axis.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Locked-test failure scores by observed outcome", x=0.03, ha="left", fontsize=16, fontweight="bold")
    save_figure(fig, path)


def render_cases(cases: list[dict[str, Any]], path: Path) -> None:
    fig, axes = plt.subplots(1, len(cases), figsize=(16, 4.8), sharey=True, layout="none")
    for axis, case in zip(axes, cases):
        score = float(case["score_low_volume_dead"])
        threshold = float(case["decision_threshold_low_volume_dead"])
        token_symbol = case.get("token_symbol") or case.get("token_fingerprint") or "Symbol unavailable"
        is_dead = case["observed_label"] == "low_volume_dead"
        color = COLORS["dead"] if is_dead else COLORS["active"]
        axis.bar([0], [score], width=0.52, color=color, alpha=0.88)
        axis.axhline(threshold, color=COLORS["gold"], linestyle="--", linewidth=2)
        axis.set_ylim(0, 1.05)
        axis.set_xlim(-0.6, 0.6)
        axis.set_xticks([0], [token_symbol])
        axis.set_ylabel("Failure score")
        axis.set_title(f"{case['case_id']} / {token_symbol}\n{case['case_type']}")
        graph = case["graph_context"]
        context = (
            f"score {score:.3f}\n"
            f"swaps {compact(case['transaction_context']['swap_count'])} | "
            f"volume ${compact(case['transaction_context']['pre_cutoff_volume_usd'])}\n"
            f"active days {case['transaction_context']['active_day_count']} | "
            f"nodes {graph['node_count']} | wallets {graph['wallet_count']}"
        )
        axis.text(0, -0.22, context, ha="center", va="top", fontsize=8, color=COLORS["muted"], transform=axis.transAxes)
        axis.spines[["top", "right"]].set_visible(False)
    fig.subplots_adjust(bottom=0.24, top=0.76, wspace=0.18)
    fig.suptitle(
        "Temporal holdout cases at the 10% validation budget",
        x=0.03,
        y=0.98,
        ha="left",
        fontsize=16,
        fontweight="bold",
    )
    save_figure(fig, path)


def coefficient_data(model_path: Path) -> pd.DataFrame:
    artifact = joblib.load(model_path)
    model = artifact["model"]
    feature_names = artifact["feature_names"]
    coefficients = model.coef_[0].tolist()
    records = []
    for feature, coefficient in zip(feature_names, coefficients):
        records.append(
            {
                "feature": feature,
                "label": FEATURE_LABELS.get(feature, feature),
                "coefficient_continued_activity": float(coefficient),
                "odds_ratio_per_train_sd": float(math.exp(coefficient)),
                "direction": "higher continued-activity score" if coefficient > 0 else "higher low-volume-dead score" if coefficient < 0 else "no fitted direction",
            }
        )
    return pd.DataFrame(records)


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, float_format="%.8g")


def markdown_feature_table(stats: pd.DataFrame) -> str:
    lines = ["| Feature | Active median [IQR] | Low-volume median [IQR] | Zero share |", "| --- | ---: | ---: | ---: |"]
    for feature in FEATURE_NAMES:
        active = stats[(stats["feature"] == feature) & (stats["label"] == "continued_activity")].iloc[0]
        dead = stats[(stats["feature"] == feature) & (stats["label"] == "low_volume_dead")].iloc[0]
        active_text = f"{compact(active['median'])} [{compact(active['q1'])}, {compact(active['q3'])}]"
        dead_text = f"{compact(dead['median'])} [{compact(dead['q1'])}, {compact(dead['q3'])}]"
        zero_text = f"{pct((active['zero_share'] + dead['zero_share']) / 2)}"
        lines.append(f"| {FEATURE_LABELS[feature]} | {active_text} | {dead_text} | {zero_text} |")
    return "\n".join(lines)


def markdown_cohort_table(rows: pd.DataFrame, column: str) -> str:
    table = rows.groupby([column, "label"]).size().unstack(fill_value=0)
    order = ["train", "validation", "test"]
    lines = ["| Partition | Continued activity | Low-volume dead | Total |", "| --- | ---: | ---: | ---: |"]
    for partition in order:
        active = int(table.loc[partition].get("continued_activity", 0))
        dead = int(table.loc[partition].get("low_volume_dead", 0))
        lines.append(f"| {partition} | {active} | {dead} | {active + dead} |")
    return "\n".join(lines)


def markdown_ranking_table(summary: pd.DataFrame) -> str:
    lines = ["| Evaluation | Model | ROC-AUC | Average precision | Seeds |", "| --- | --- | ---: | ---: | ---: |"]
    for split in SPLIT_ORDER:
        subset = summary[summary["analysis_split"] == split].set_index("model").reindex(MODEL_ORDER)
        for model in MODEL_ORDER:
            row = subset.loc[model]
            lines.append(
                f"| {SPLIT_LABELS[split]} | {model} | {row['roc_auc_mean']:.3f} +/- {row['roc_auc_sd']:.3f} | {row['average_precision_mean']:.3f} +/- {row['average_precision_sd']:.3f} | {int(row['seed_count'])} |"
            )
    return "\n".join(lines)


def markdown_operating_table(operating: pd.DataFrame) -> str:
    lines = ["| Evaluation | Model | Test FPR | Failure recall | Failure precision | Failure F1 | Alerts |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for split in SPLIT_ORDER:
        subset = operating[(operating["analysis_split"] == split) & np.isclose(operating["target_failure_positive_fpr"], 0.10)]
        for model in MODEL_ORDER:
            row = subset[subset["model"] == model].iloc[0]
            lines.append(
                f"| {SPLIT_LABELS[split]} (10% validation FPR) | {model} | {pct(row['test_fpr'])} | {pct(row['failure_recall'])} | {pct(row['failure_precision'])} | {row['failure_f1']:.3f} | {row['alerts']:.0f} |"
            )
    return "\n".join(lines)


def case_table(cases: list[dict[str, Any]]) -> str:
    lines = ["| Case | Token | Decision | Observed label | Failure score | Threshold | Seven-day context |", "| --- | --- | --- | --- | ---: | ---: | --- |"]
    for case in cases:
        context = case["transaction_context"]
        graph = case["graph_context"]
        token_symbol = case.get("token_symbol") or case.get("token_fingerprint") or "Symbol unavailable"
        lines.append(
            f"| {case['case_id']} | {token_symbol} | {case['model_decision']} | {case['observed_label']} | {case['score_low_volume_dead']:.3f} | {case['decision_threshold_low_volume_dead']:.3f} | {context['swap_count']} swaps, ${compact(context['pre_cutoff_volume_usd'])} early volume, {context['active_day_count']} active days, {graph['node_count']} nodes / {graph['wallet_pool_edge_count']} wallet-pool edges |"
        )
    return "\n".join(lines)


def render_case_demo(cases: list[dict[str, Any]], output_path: Path) -> None:
    cases_json = json.dumps(cases, ensure_ascii=True, separators=(",", ":"))
    html = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ethereum token result analysis | case review</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #24323a;
      --muted: #66757c;
      --paper: #f7f5ef;
      --surface: #fffefa;
      --line: #d8dfdc;
      --teal: #287d8e;
      --coral: #d6614b;
      --gold: #d9a441;
      --green: #5d9a78;
      --shadow: 0 12px 32px rgba(36, 50, 58, .08);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink); font-family: "Avenir Next", "Helvetica Neue", Arial, sans-serif; line-height: 1.45; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 24px 48px; }}
    .topline {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-bottom: 18px; border-bottom: 1px solid var(--line); }}
    .brand {{ font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }}
    .status {{ color: var(--green); font-size: 12px; font-weight: 700; }}
    header {{ padding: 34px 0 24px; max-width: 760px; }}
    h1 {{ font-size: clamp(30px, 5vw, 52px); line-height: 1.02; letter-spacing: -.025em; margin: 0 0 12px; }}
    .lede {{ color: var(--muted); max-width: 68ch; margin: 0; }}
    .review-bar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 14px 18px; padding: 16px 0 22px; border-bottom: 1px solid var(--line); }}
    label {{ font-size: 12px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }}
    select {{ min-height: 42px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); padding: 0 40px 0 12px; font: inherit; font-size: 15px; box-shadow: 0 2px 7px rgba(36, 50, 58, .04); }}
    select:focus-visible {{ outline: 3px solid rgba(40, 125, 142, .28); outline-offset: 2px; }}
    .review-count {{ margin-left: auto; color: var(--muted); font-size: 13px; }}
    .decision {{ display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(260px, .6fr); gap: 24px; align-items: stretch; padding: 24px 0; }}
    .decision-main, .outcome {{ background: var(--surface); border: 1px solid var(--line); border-radius: 10px; box-shadow: var(--shadow); padding: 24px; }}
    .case-heading {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }}
    .case-heading h2 {{ margin: 0; font-size: 24px; letter-spacing: -.01em; }}
    .case-type {{ display: inline-flex; align-items: center; min-height: 28px; border-radius: 999px; padding: 0 10px; background: rgba(217, 164, 65, .16); color: #815e12; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; }}
    .decision-copy {{ color: var(--muted); margin: 10px 0 22px; max-width: 58ch; }}
    .score-line {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 8px; }}
    .score-label {{ color: var(--muted); font-size: 13px; }}
    .score-value {{ font-size: 34px; line-height: 1; font-weight: 700; font-variant-numeric: tabular-nums; }}
    .score-track {{ position: relative; height: 12px; background: #e8ece9; border-radius: 999px; overflow: visible; }}
    .score-fill {{ position: absolute; inset: 0 auto 0 0; width: 0; border-radius: inherit; background: var(--coral); transition: width 260ms ease-out; }}
    .threshold {{ position: absolute; top: -8px; bottom: -8px; width: 2px; background: var(--gold); transition: left 260ms ease-out; }}
    .threshold-label {{ margin-top: 9px; color: var(--muted); font-size: 12px; }}
    .context-title, .outcome-title {{ margin: 26px 0 12px; font-size: 12px; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .07em; }}
    .context-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); }}
    .context-item {{ min-width: 0; padding: 13px 14px; background: var(--surface); }}
    .context-item span {{ display: block; color: var(--muted); font-size: 12px; }}
    .context-item strong {{ display: block; margin-top: 3px; font-size: 17px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
    .outcome {{ display: flex; flex-direction: column; justify-content: space-between; }}
    .outcome .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .07em; font-weight: 700; }}
    .outcome-value {{ margin: 10px 0; font-size: 22px; font-weight: 700; }}
    .outcome-note {{ color: var(--muted); font-size: 14px; margin: 0; }}
    .detail-band {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; padding-top: 4px; }}
    .detail-band section {{ padding: 20px 0 0; border-top: 1px solid var(--line); }}
    .detail-band h3 {{ margin: 0 0 8px; font-size: 16px; }}
    .detail-band p {{ margin: 0; color: var(--muted); font-size: 14px; }}
    .footer-note {{ margin-top: 30px; color: var(--muted); font-size: 12px; max-width: 78ch; }}
    @media (max-width: 760px) {{
      main {{ padding: 20px 16px 36px; }}
      .topline {{ align-items: flex-start; flex-direction: column; gap: 7px; }}
      header {{ padding-top: 26px; }}
      .decision, .detail-band {{ grid-template-columns: 1fr; gap: 16px; }}
      .review-count {{ margin-left: 0; width: 100%; }}
      .context-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      *, *::before, *::after {{ transition-duration: .01ms !important; }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="topline">
      <div class="brand">Ethereum token result analysis</div>
      <div class="status">Historical holdout / token symbols retained</div>
    </div>
    <header>
      <h1>Case review</h1>
      <p class="lede">Inspect how a validation-selected failure-screening threshold behaves on four temporal-holdout examples. The score and seven-day context were available at prediction time; the observed outcome is shown only as later evaluation evidence.</p>
    </header>
    <div class="review-bar">
      <label for="case-select">Select a case</label>
      <select id="case-select" aria-label="Select a historical token case"></select>
      <div class="review-count" id="review-count" aria-live="polite"></div>
    </div>
    <section class="decision" aria-live="polite">
      <div class="decision-main">
        <div class="case-heading"><h2 id="case-title"></h2><span class="case-type" id="case-type"></span></div>
        <p class="decision-copy" id="case-copy"></p>
        <div class="score-line"><span class="score-label">Estimated low-volume-dead score</span><strong class="score-value" id="score-value"></strong></div>
        <div class="score-track" aria-hidden="true"><div class="score-fill" id="score-fill"></div><div class="threshold" id="threshold"></div></div>
        <div class="threshold-label" id="threshold-label"></div>
        <div class="context-title">Available at the seven-day cutoff</div>
        <div class="context-grid" id="context-grid"></div>
      </div>
      <aside class="outcome">
        <div><div class="label">Observed later for evaluation</div><div class="outcome-value" id="outcome-value"></div><p class="outcome-note" id="outcome-note"></p></div>
        <div><div class="outcome-title">Reading the case</div><p class="outcome-note">Transaction and graph context describe the evidence available for this token. Feature attribution requires a separate analysis.</p></div>
      </aside>
    </section>
    <div class="detail-band">
      <section><h3>Prediction-time view</h3><p>Early swaps, activity days, pools, protocols, and wallet-pool structure are the available evidence. No follow-up events or outcome fields enter this view.</p></section>
      <section><h3>Review action</h3><p id="review-action"></p></section>
    </div>
    <p class="footer-note">The threshold is the Edge GCN family mean selected from validation at a 10% target false-positive-rate budget. This historical demonstration shows how the ranking behaves across four cases and supports research triage and monitoring design.</p>
  </main>
  <script>
    const cases = {cases_json};
    const select = document.getElementById("case-select");
    const title = document.getElementById("case-title");
    const type = document.getElementById("case-type");
    const copy = document.getElementById("case-copy");
    const scoreValue = document.getElementById("score-value");
    const scoreFill = document.getElementById("score-fill");
    const threshold = document.getElementById("threshold");
    const thresholdLabel = document.getElementById("threshold-label");
    const contextGrid = document.getElementById("context-grid");
    const outcomeValue = document.getElementById("outcome-value");
    const outcomeNote = document.getElementById("outcome-note");
    const reviewAction = document.getElementById("review-action");
    const reviewCount = document.getElementById("review-count");
    const fmt = new Intl.NumberFormat("en-US", {{ maximumFractionDigits: 2 }});
    const money = new Intl.NumberFormat("en-US", {{ style: "currency", currency: "USD", maximumFractionDigits: 2 }});
    function item(label, value) {{
      const node = document.createElement("div");
      node.className = "context-item";
      node.innerHTML = `<span>${{label}}</span><strong>${{value}}</strong>`;
      return node;
    }}
    function render(index) {{
      const itemData = cases[index];
      const context = itemData.transaction_context;
      const graph = itemData.graph_context;
      const score = Number(itemData.score_low_volume_dead);
      const cutoff = Number(itemData.decision_threshold_low_volume_dead);
      const flagged = itemData.model_decision === "flag_failure";
      select.value = String(index);
      title.textContent = `${{itemData.case_id}} / ${{itemData.token_symbol || itemData.token_fingerprint}}`;
      type.textContent = `${{itemData.case_type}} / ${{flagged ? "flagged" : "not flagged"}}`;
      copy.textContent = itemData.interpretation;
      scoreValue.textContent = score.toFixed(3);
      scoreFill.style.width = `${{Math.max(0, Math.min(100, score * 100))}}%`;
      threshold.style.left = `${{Math.max(0, Math.min(100, cutoff * 100))}}%`;
      thresholdLabel.textContent = `Decision threshold ${{cutoff.toFixed(3)}} / validation-selected 10% false-positive-rate budget`;
      contextGrid.replaceChildren(
        item("Observation volume", money.format(context.pre_cutoff_volume_usd)),
        item("Swaps", fmt.format(context.swap_count)),
        item("Active days", fmt.format(context.active_day_count)),
        item("Pools / protocols", `${{context.pool_count}} / ${{context.protocol_count}}`),
        item("Graph nodes", fmt.format(graph.node_count)),
        item("Wallet-pool edges", fmt.format(graph.wallet_pool_edge_count)),
      );
      outcomeValue.textContent = itemData.observed_label === "low_volume_dead" ? "Low-volume dead" : "Continued activity";
      outcomeNote.textContent = itemData.observed_label === "low_volume_dead" ? "The later 90-day follow-up fell below the project's USD 1,000 swap-volume threshold." : "The later 90-day follow-up reached at least the project's USD 1,000 swap-volume threshold.";
      reviewAction.textContent = flagged ? "Open this token for analyst review, then inspect the transaction and graph context before recording a research decision." : "Keep this token lower in the review queue and compare its context with other low-scored cases.";
      reviewCount.textContent = `Case ${{Number(index) + 1}} of ${{cases.length}}`;
    }}
    cases.forEach((itemData, index) => {{
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = `${{itemData.case_id}} / ${{itemData.token_symbol || itemData.case_type}}`;
      select.appendChild(option);
    }});
    select.addEventListener("change", (event) => render(Number(event.target.value)));
    render(0);
  </script>
</body>
</html>
'''
    output_path.write_text(html, encoding="utf-8")


def write_report(
    project_root: Path,
    output: Path,
    data: dict[str, Any],
    rows: pd.DataFrame,
    evaluation: pd.DataFrame,
    scores: pd.DataFrame,
    stats: pd.DataFrame,
    summary: pd.DataFrame,
    operating: pd.DataFrame,
    coefficients: pd.DataFrame,
) -> None:
    general_dead = int((rows["label"] == "low_volume_dead").sum())
    general_active = int((rows["label"] == "continued_activity").sum())
    temporal_test = rows[rows["temporal_partition"] == "test"]
    temporal_dead = int((temporal_test["label"] == "low_volume_dead").sum())
    temporal_active = int((temporal_test["label"] == "continued_activity").sum())
    graph_summary = pd.DataFrame(data["graph_summary"])
    event_count_equal = bool((rows["event_count"] == rows["swap_count"]).all())
    mint_zero = bool((rows["mint_count"] == 0).all())
    burn_zero = bool((rows["burn_count"] == 0).all())
    missing_any = int(rows[FEATURE_NAMES].isna().any(axis=1).sum())
    general_k = operating[(operating["analysis_split"] == "general_stratified") & np.isclose(operating["target_failure_positive_fpr"], 0.10)]
    temporal_k = operating[(operating["analysis_split"] == "temporal") & np.isclose(operating["target_failure_positive_fpr"], 0.10)]
    general_k_text = ", ".join(f"{model}: {pct(float(general_k[general_k['model'] == model]['precision_at_k'].iloc[0]))}" for model in MODEL_ORDER)
    temporal_k_text = ", ".join(f"{model}: {pct(float(temporal_k[temporal_k['model'] == model]['precision_at_k'].iloc[0]))}" for model in MODEL_ORDER)
    coefficients_lines = ["| Feature | Coefficient toward continued activity | Odds ratio per one train SD | Interpretation |", "| --- | ---: | ---: | --- |"]
    for _, row in coefficients.iterrows():
        coefficients_lines.append(
            f"| {row['label']} | {row['coefficient_continued_activity']:.3f} | {row['odds_ratio_per_train_sd']:.3f} | {row['direction']} |"
        )
    corr = rows[FEATURE_NAMES].corr(method="spearman")
    top_correlations: list[tuple[str, str, float]] = []
    for index, left in enumerate(FEATURE_NAMES):
        for right in FEATURE_NAMES[index + 1 :]:
            value = corr.loc[left, right]
            if pd.notna(value):
                top_correlations.append((left, right, abs(float(value))))
    top_correlations.sort(key=lambda item: item[2], reverse=True)
    correlation_sentence = ", ".join(
        f"{FEATURE_LABELS[left]} with {FEATURE_LABELS[right]} ({value:.2f})" for left, right, value in top_correlations[:4]
    )
    report_path = project_root / "reports" / "wallet_graph_project_result_analysis_20261005_v1.md"
    figure_prefix = "../data/result_analysis_wallet_graph_20261005_v1/figures"
    demo_link = "../data/result_analysis_wallet_graph_20261005_v1/case_demo.html"
    general_edge_operating = operating[
        (operating["analysis_split"] == "general_stratified")
        & (operating["model"] == "Edge GCN")
        & np.isclose(operating["target_failure_positive_fpr"], 0.10)
    ].iloc[0]
    temporal_edge_operating = operating[
        (operating["analysis_split"] == "temporal")
        & (operating["model"] == "Edge GCN")
        & np.isclose(operating["target_failure_positive_fpr"], 0.10)
    ].iloc[0]
    report = f'''# Ethereum token project result analysis

Version: `wallet_graph_project_result_analysis_20261005_v1`  
Project revision observed during analysis: `{data.get("git_head") or "working tree"}`

## Abstract

This report evaluates whether the first seven days of selected Ethereum DEX activity can rank token projects by their subsequent 90-day activity. The target is a volume-based outcome: `low_volume_dead` means less than USD 1,000 in selected-pool swap volume during the complete follow-up, while `continued_activity` means at least USD 1,000.

The study uses a matched cohort of 2,000 tokens and compares a tabular logistic baseline with topology-only GraphSAGE and an edge-aware GCN. On the general stratified test, the validation-selected edge GCN produced failure F1 {general_edge_operating["failure_f1"]:.3f}, failure recall {pct(general_edge_operating["failure_recall"])}, and realized test FPR {pct(general_edge_operating["test_fpr"])} at the 10% validation FPR budget. General-test `Precision@20` was 100% for all three model families ({general_k_text}).

The chronological holdout separates ranking quality from operating-point stability. Topology-only GraphSAGE ranked slightly better than edge GCN, while edge GCN had the higher failure F1 at the selected budget. Its realized test FPR was {pct(temporal_edge_operating["test_fpr"])}. The results support an analyst workflow that ranks cases, allocates a review budget, and examines transaction and wallet-pool context. Graph structure improves on the compact tabular baseline in this experiment, while the value of edge features changes across splits.

## 1. Study question and use case

The study addresses early review of newly launched or obscure Ethereum token projects. A researcher or review operator needs a way to prioritize cases before the 90-day outcome is known. The model therefore uses information available by a fixed seven-day cutoff and ranks tokens by their estimated probability of the low-volume outcome.

The intended workflow is analyst-led. A ranked list determines which cases receive attention first; the reviewer can then inspect transactions, wallet-pool structure, and later outcomes. This keeps the prediction task connected to a concrete review process and makes false alerts and missed failures part of the evaluation.

## 2. Data and method

```mermaid
flowchart LR
    A[Label-blind candidate frame] --> B[Fixed selected pools and sources]
    B --> C[t0 and first 7 days]
    C --> D[Point-in-time features]
    C --> E[Wallet-pool-token graphs]
    B --> F[Complete 90-day follow-up]
    F --> G[low_volume_dead or continued_activity]
    D --> H[Tabular logistic]
    E --> I[Topology GraphSAGE]
    E --> J[Edge-aware GCN]
    G --> K[General split + temporal stress test]
    H --> K
    I --> K
    J --> K
    K --> L[Validation threshold and review budget]
    L --> M[Locked test and analyst case review]
```

The prediction unit is one token contract. `t0` is the earliest selected-pool creation timestamp, with the documented activity fallback. Features use the inclusive seven-day interval from `t0` through the cutoff. The label uses the following complete 90 days. Swaps count toward volume; mints and burns remain feature channels but are not added to the volume outcome.

The tabular baseline uses nine raw pre-cutoff values: event count, swap count, mint count, burn count, pre-cutoff USD volume, missing swap-USD count, active-day count, pool count, and protocol count. The saved logistic baseline fits `StandardScaler` on training rows only and then fits logistic regression; it does not log-transform the values for model fitting. The EDA log1p views below are display transforms only.

The graph representation is one local graph per target token: wallet -> swap activity -> pool -> contains -> target token. Wallet nodes represent observed blockchain addresses. The graph includes wallet-pool relationship features such as swap count, positive historical USD volume, active-day fraction, time offsets, role counts, and missing-amount flags. Learned wallet state is not shared between token graphs or partitions.

The primary evaluation is the frozen general token-level split. The secondary temporal split assigns rows by `t0`: before 2024 to train, 2024 to validation, and 2025 onward through 2026-06-24 to test. Thresholds, architecture selection, and `K=20` review-budget selection use validation data only; test rows are scored after that checkpoint.

## 3. Cohort and exploratory analysis

The matched cohort contains {len(rows):,} complete labels: {general_active:,} continued-activity and {general_dead:,} low-volume-dead tokens. The general test prevalence is {pct((rows["general_partition"] == "test").mul(rows["label"] == "low_volume_dead").sum() / (rows["general_partition"] == "test").sum())} low-volume dead ({int((rows["general_partition"] == "test").sum())} rows). The chronological test contains {temporal_test.shape[0]} rows: {temporal_dead} low-volume dead and {temporal_active} continued activity ({pct(temporal_dead / len(temporal_test))} low-volume dead).

### Partition support

General stratified:

{markdown_cohort_table(rows, "general_partition")}

Chronological stress test:

{markdown_cohort_table(rows, "temporal_partition")}

The general split is close to balanced because the selected cohort was frozen at 1,000 rows per label. The temporal test has 78.4% low-volume-dead prevalence. That shift changes the interpretation of average precision, so the ranking results should be read alongside the partition counts.

![Cohort composition and launch-period drift]({figure_prefix}/cohort_balance_and_drift.png)

### Nine-feature view

{markdown_feature_table(stats)}

The clearest separation is activity intensity: continued-activity tokens have higher median early volume, swap count, and active days. `event_count` and `swap_count` are identical for all 2,000 rows (`{event_count_equal}`), so they form one redundant signal. Mint and burn counts are constant zero (`mint_count={mint_zero}`, `burn_count={burn_zero}`); their fitted coefficients are zero and they provide no variation in this cohort. Pool count is concentrated at one and contributes little variation. The tabular baseline therefore relies mainly on early activity intensity and active days.

![Early feature distributions]({figure_prefix}/feature_distributions.png)

![Feature zeros and missingness]({figure_prefix}/feature_quality_and_zeros.png)

All joined feature rows are complete (`{missing_any}` rows with any missing value), and the frozen feature audit reports no pre-`t0`, post-cutoff, or missing-timestamp violations. The missing swap-USD count is zero for almost every row, so it records data quality while contributing little variation to prediction.

The largest non-constant redundancy pairs in a Spearman view are {correlation_sentence}. These correlations explain why the logistic coefficients are best read as model behavior across the feature set, not as isolated effects of individual variables.

![Feature redundancy]({figure_prefix}/feature_correlation.png)

Launch-period composition also drifts: the low-volume share is low in the earliest rows and rises in the 2023-2026 rows. This cohort structure motivates the chronological stress test.

## 4. Model results

### Ranking quality

{markdown_ranking_table(summary)}

![Ranking comparison]({figure_prefix}/model_ranking_comparison.png)

In the general matched test, the selected edge GCN improves both ROC-AUC and average precision over the topology-only width-64 GraphSAGE control and the tabular logistic baseline. In the temporal test, topology-only GraphSAGE has slightly higher ranking metrics than edge GCN, while the tabular baseline is lower on both. Graph structure adds predictive signal relative to the compact tabular baseline; the edge features provide an advantage on the general split but not on temporal ranking metrics.

### Analyst operating points

{markdown_operating_table(operating)}

![Operating tradeoffs]({figure_prefix}/operating_tradeoffs.png)

At the general 10% validation budget, edge GCN has the strongest failure recall/F1 tradeoff, while tabular logistic is more conservative and has higher failure precision. On the temporal test, edge GCN flags 131 of 185 rows and correctly flags 123 of 145 observed failures. It also flags 8 of 40 continued-activity tokens, giving a realized failure-positive FPR of 20%.

The graph-family results use three seeds on the same held-out rows. Seed variation measures stability across repeated runs; these runs do not form independent test cohorts. At `K=20`, the temporal graph families reach 100% precision while temporal tabular logistic reaches 85% ({temporal_k_text}). The review budget gives a concrete operating rule, and its precision changes with model and evaluation period.

![Locked-test score distributions]({figure_prefix}/score_distributions.png)

## 5. Model interpretation

### Tabular logistic baseline

The baseline predicts `continued_activity`. Positive coefficients increase the odds of that class; negative coefficients increase the odds of `low_volume_dead`. The odds ratios below correspond to a one-standard-deviation increase after training-fitted standardization. They describe how the model uses the inputs.

{chr(10).join(coefficients_lines)}

Event count and swap count are duplicates, so their equal coefficients should be read together. Mint and burn are constant, which explains their zero coefficients. This phase did not run permutation or ablation attribution; a follow-up analysis can add those tests under a separately frozen protocol.

### Graph interpretation

The graph model represents local structure that the nine-feature table does not: which wallets connect to which pools, how activity is distributed across those connections, and the role, timing, and volume summaries carried by each edge. The matched topology-only versus edge-aware comparison isolates the value of those edge features. The general test favors edge GCN at the selected operating points, while the temporal test favors topology GraphSAGE on ranking metrics. The contribution of edge features is therefore split-dependent.

The graph collection contains {len(graph_summary):,} model-ready quality rows, complete participant sender coverage, and the frozen manifest's 18,950 wallet-pool edges. Addresses serve as graph-construction identifiers. Full addresses are omitted from the report, while token symbols are retained.

## 6. Case review

The four cases below use the temporal Edge GCN family mean and its validation-selected 10% budget threshold. Early context comes from the seven-day cutoff; the observed label comes from the completed follow-up.

{case_table(data["cases"])}

![Case scores]({figure_prefix}/case_scores.png)

The [local case-review demonstration]({demo_link}) lets the reader select each token and inspect its symbol, score, threshold, seven-day context, graph summary, and later outcome. The false-positive and false-negative cases show where the ranking succeeds and where review remains necessary.

## 7. Reproducibility

The analysis input manifest is [`analysis_manifest.json`](../data/result_analysis_wallet_graph_20261005_v1/analysis_manifest.json). The source artifacts are the frozen data product, general and temporal split manifests, edge-aware/general and temporal failure-positive evaluation JSON, the temporal analysis cases, and the wallet graph schema/quality files. The generated figure bundle is under [`data/result_analysis_wallet_graph_20261005_v1/`](../data/result_analysis_wallet_graph_20261005_v1/).

The preparation stage reads Parquet through the project `.venv` DuckDB environment. The rendering stage uses the remote base Conda environment for pandas, matplotlib, and the saved logistic model artifact. The pipeline reads the frozen analysis artifacts and writes tables, figures, and case summaries. Test labels appear in post-hoc EDA, locked metric displays, and retrospective case descriptions.

The primary general comparison report and temporal modeling scripts remain alongside this report. The HTML edition embeds the eight generated figures and links to the manifest, tabular outputs, and interactive case review.
'''
    report_path.write_text(report, encoding="utf-8")


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    input_path = args.input.resolve()
    output = args.output.resolve()
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    configure_plot()
    data = read_json(input_path)
    rows, evaluation, scores = as_dataframes(data)
    stats = feature_statistics(rows)
    summary = model_summary(evaluation)
    operating = operating_summary(evaluation)
    coefficients = coefficient_data(args.tabular_model.resolve())

    render_cohort_balance(rows, figures / "cohort_balance_and_drift.png")
    render_feature_distributions(rows, figures / "feature_distributions.png")
    render_feature_quality(rows, figures / "feature_quality_and_zeros.png")
    render_correlation(rows, figures / "feature_correlation.png")
    render_model_comparison(evaluation, figures / "model_ranking_comparison.png")
    render_operating_tradeoffs(evaluation, figures / "operating_tradeoffs.png")
    render_score_distributions(scores, evaluation, figures / "score_distributions.png")
    render_cases(data["cases"], figures / "case_scores.png")

    write_csv(output / "feature_summary.csv", stats)
    write_csv(output / "model_summary.csv", summary)
    write_csv(output / "operating_summary.csv", operating)
    write_csv(output / "tabular_coefficients.csv", coefficients)
    (output / "figure_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": "result-analysis-figures-0.1",
                "figures": sorted(path.name for path in figures.glob("*.png")),
                "source_input": str(input_path),
                "test_labels_used_for": "post-hoc descriptive plots and locked evaluation display",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    render_case_demo(data["cases"], output / "case_demo.html")
    write_report(project_root, output, data, rows, evaluation, scores, stats, summary, operating, coefficients)
    print(json.dumps({"output": str(output), "figures": sorted(path.name for path in figures.glob("*.png")), "report": "reports/wallet_graph_project_result_analysis_20261005_v1.md"}, indent=2))


if __name__ == "__main__":
    main()
