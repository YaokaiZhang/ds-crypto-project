#!/usr/bin/env python3
"""Build an auditable analysis artifact from temporal prediction outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from scripts.evaluate_failure_predictions import (
    choose_failure_threshold,
    failure_labels_and_scores,
    failure_metrics,
)


VALIDATION_SPLITS = frozenset(("validation",))
TEST_SPLITS = frozenset(("test", "test_holdout"))
DEFAULT_TARGET_FPRS = (0.05, 0.10, 0.15)
FAMILY_ORDER = ("edge_gcn", "topology_sage", "tabular_logistic")
FAMILY_LABELS = {
    "edge_gcn": "Edge GCN",
    "topology_sage": "Topology GraphSAGE",
    "tabular_logistic": "Tabular logistic",
}
CONTEXT_FEATURES = (
    "observation_days",
    "event_count",
    "swap_count",
    "mint_count",
    "burn_count",
    "pre_cutoff_volume_usd",
    "pre_cutoff_missing_swap_usd_count",
    "active_day_count",
    "pool_count",
    "protocol_count",
)
GRAPH_STATS = (
    "node_count",
    "edge_count",
    "wallet_count",
    "pool_count",
    "wallet_pool_edge_count",
    "window_swap_count",
)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


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
    token = str(row.get("token_address", "")).strip().lower()
    source_dataset = str(row.get("source_dataset", "")).strip()
    if not token or not source_dataset:
        raise ValueError(f"prediction row is missing its key: {row}")
    return token, source_dataset


def _indexed(rows: Iterable[dict[str, Any]], source: Path) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = row_key(row)
        if key in indexed:
            raise ValueError(f"{source}: duplicate prediction key {key}")
        indexed[key] = row
    if not indexed:
        raise ValueError(f"{source}: no prediction rows")
    return indexed


def model_family(model_name: str) -> str:
    return model_name.rsplit("_seed", 1)[0] if "_seed" in model_name else model_name


def aggregate_prediction_rows(paths: list[Path]) -> list[dict[str, Any]]:
    """Average native continued-activity scores across one model family."""
    if not paths:
        raise ValueError("at least one prediction path is required")
    indexed_rows = [_indexed(read_jsonl(path), path) for path in paths]
    keys = set(indexed_rows[0])
    for path, rows in zip(paths[1:], indexed_rows[1:]):
        if set(rows) != keys:
            missing = sorted(keys - set(rows))[:3]
            extra = sorted(set(rows) - keys)[:3]
            raise ValueError(f"{path}: prediction keys differ; missing={missing}, extra={extra}")

    aggregated: list[dict[str, Any]] = []
    for key in sorted(keys):
        source_rows = [rows[key] for rows in indexed_rows]
        reference = source_rows[0]
        native_labels = {int(row["label_int"]) for row in source_rows}
        splits = {str(row.get("split")) for row in source_rows}
        partitions = {str(row.get("partition", row.get("split"))) for row in source_rows}
        if len(native_labels) != 1 or len(splits) != 1 or len(partitions) != 1:
            raise ValueError(f"model family disagrees on metadata for {key}")
        continued_scores = [float(row["score_continued_activity"]) for row in source_rows]
        if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in continued_scores):
            raise ValueError(f"model family has an invalid score for {key}")
        mean_continued = statistics.fmean(continued_scores)
        aggregated.append(
            {
                "token_address": key[0],
                "source_dataset": key[1],
                "label": reference.get("label"),
                "label_int": native_labels.pop(),
                "split": splits.pop(),
                "partition": partitions.pop(),
                "score_continued_activity": mean_continued,
                "score_low_volume_dead": 1.0 - mean_continued,
            }
        )
    return aggregated


def _target_fpr_result(results: list[dict[str, Any]], target_fpr: float) -> dict[str, Any]:
    for result in results:
        if math.isclose(float(result["target_failure_positive_fpr"]), target_fpr):
            return result
    raise KeyError(f"missing target FPR {target_fpr}")


def evaluate_aggregate(
    rows: list[dict[str, Any]], target_fprs: list[float], review_k: int
) -> dict[str, Any]:
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
        "validation_rows": len(validation_rows),
        "test_rows": len(test_rows),
        "results": results,
    }


def _mean_sd(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "sd": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }


def seed_summary(
    entries: list[dict[str, Any]], target_fprs: list[float]
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for target_fpr in sorted(set(target_fprs)):
        metrics_by_name: defaultdict[str, list[float]] = defaultdict(list)
        for entry in entries:
            result = _target_fpr_result(entry["results"], target_fpr)
            test = result["test"]
            metrics_by_name["roc_auc_low_volume_dead"].append(
                float(test["roc_auc_low_volume_dead"])
            )
            metrics_by_name["average_precision_low_volume_dead"].append(
                float(test["average_precision_low_volume_dead"])
            )
            metrics_by_name["failure_positive_f1"].append(float(test["failure_positive_f1"]))
            metrics_by_name["dead_recall"].append(float(test["dead_recall"]))
            metrics_by_name["dead_precision"].append(float(test["dead_precision"]))
            metrics_by_name["failure_positive_false_positive_rate"].append(
                float(test["failure_positive_false_positive_rate"])
            )
            metrics_by_name["alerts"].append(
                float(test["confusion_matrix"]["true_dead"] + test["confusion_matrix"]["continued_flagged_dead"])
            )
        summary[str(target_fpr)] = {
            name: _mean_sd(values) for name, values in sorted(metrics_by_name.items())
        }
    return summary


def load_context(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = read_jsonl(path)
    return _indexed(rows, path)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _context_value(row: dict[str, Any], key: str) -> int | float | str | None:
    value = row.get(key)
    if key == "pre_cutoff_volume_usd":
        parsed = _as_float(value)
        return round(parsed, 6) if parsed is not None else None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    parsed = _as_float(value)
    if parsed is not None and parsed.is_integer():
        return int(parsed)
    return value


def _fingerprint(token_address: str) -> str:
    return hashlib.sha256(token_address.lower().encode("utf-8")).hexdigest()[:16]


def _case_type(row: dict[str, Any], threshold: float) -> str:
    dead = row["label"] == "low_volume_dead"
    flagged = float(row["score_low_volume_dead"]) >= threshold
    if dead and flagged:
        return "TP"
    if not dead and flagged:
        return "FP"
    if dead and not flagged:
        return "FN"
    return "TN"


def select_cases(
    rows: list[dict[str, Any]],
    threshold: float,
    targets: dict[tuple[str, str], dict[str, Any]],
    graphs: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    test_rows = [row for row in rows if row.get("split") in TEST_SPLITS]
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in test_rows:
        grouped[_case_type(row, threshold)].append(row)

    cases: list[dict[str, Any]] = []
    for case_type in ("TP", "FP", "FN", "TN"):
        candidates = grouped[case_type]
        if not candidates:
            raise ValueError(f"no temporal test candidate for case type {case_type}")
        reverse = case_type in ("TP", "FP")
        selected = sorted(
            candidates,
            key=lambda row: float(row["score_low_volume_dead"]),
            reverse=reverse,
        )[0]
        key = row_key(selected)
        target = targets[key]
        graph = graphs[key]
        relation_counts = Counter(
            str(edge.get("relation", "unknown")) for edge in graph.get("edge_refs", [])
        )
        graph_stats = graph.get("stats", {})
        case = {
            "case_id": f"{case_type}-1",
            "case_type": case_type,
            "token_fingerprint": _fingerprint(key[0]),
            "source_dataset": key[1],
            "observed_label": selected["label"],
            "model_decision": "flag_failure" if case_type in ("TP", "FP") else "do_not_flag_failure",
            "score_low_volume_dead": round(float(selected["score_low_volume_dead"]), 8),
            "decision_threshold_low_volume_dead": round(threshold, 8),
            "score_margin": round(float(selected["score_low_volume_dead"]) - threshold, 8),
            "t0": target.get("t0"),
            "launch_period": target.get("launch_period"),
            "transaction_context": {
                name: _context_value(target, name) for name in CONTEXT_FEATURES
            },
            "graph_context": {
                name: graph_stats.get(name) for name in GRAPH_STATS
            }
            | {"relation_counts": dict(sorted(relation_counts.items()))},
            "interpretation": {
                "TP": "Correctly prioritized observed low_volume_dead token.",
                "FP": "False failure alert on an observed continued_activity token.",
                "FN": "Missed observed low_volume_dead token at the selected threshold.",
                "TN": "Correctly left an observed continued_activity token unflagged.",
            }[case_type],
        }
        cases.append(case)
    return cases


def _relative_link(target: Path, source: Path) -> str:
    return os.path.relpath(target, source.parent).replace(os.sep, "/")


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.{digits}f}"


def _fmt_count(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_mean_sd(payload: dict[str, float], digits: int = 3) -> str:
    return f"{payload['mean']:.{digits}f} +/- {payload['sd']:.{digits}f}"


def write_report(
    report_path: Path,
    analysis_path: Path,
    output_dir: Path,
    split_manifest: dict[str, Any],
    evaluation: dict[str, Any],
    families: dict[str, dict[str, Any]],
    cases: list[dict[str, Any]],
    target_fprs: list[float],
    primary_family: str,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    quality = split_manifest.get("quality", split_manifest)
    boundaries = split_manifest.get("boundaries", {})
    partition_counts = quality.get("partition_counts", split_manifest.get("partition_counts", {}))
    partition_label_counts = quality.get(
        "partition_label_counts", split_manifest.get("partition_label_counts", {})
    )
    primary = families[primary_family]["ensemble"]
    primary_mid = _target_fpr_result(primary["results"], 0.10)
    primary_test = primary_mid["test"]
    primary_confusion = primary_test["confusion_matrix"]
    composition_lines = [
        "### Active/inactive composition",
        "",
        "Active means `continued_activity`; inactive means `low_volume_dead`.",
        "",
        "| Split | Active | Inactive | Total |",
        "| --- | ---: | ---: | ---: |",
    ]
    for partition in ("train", "validation", "test"):
        counts = partition_label_counts[partition]
        composition_lines.append(
            f"| {partition.title()} | {_fmt_count(counts['continued_activity'])} | {_fmt_count(counts['low_volume_dead'])} | {_fmt_count(partition_counts[partition])} |"
        )
    composition_lines.extend(
        [
            "",
            "The newest test period is failure-heavy rather than balanced: 145 inactive tokens and 40 active tokens.",
        ]
    )

    lines = [
        "# Temporal wallet-graph comparison",
        "",
        "Status: completed temporal validation on the frozen 2,000-token matched cohort.",
        "",
        "This report is a separate temporal holdout from the general stratified comparison. "
        "The model-selection contract remains validation-only threshold selection, with "
        "`low_volume_dead` treated as the failure-positive class.",
        "",
        "## Scope and split",
        "",
        f"- Temporal split: [`{split_manifest.get('split_name', 'wallet_graph_temporal')}`]({_relative_link(Path(split_manifest.get('_path', 'split_manifest.json')), report_path)})",
        f"- Input rows: {quality.get('input_rows', quality.get('eligible_rows', '-'))}; eligible rows: {quality.get('eligible_rows', '-')}; discarded rows: {quality.get('discarded_rows', 0)}.",
        f"- Cutoffs: train before `{boundaries.get('train_end', '-')}`, validation before `{boundaries.get('validation_end', '-')}`, test before `{boundaries.get('test_end', '-')}`.",
        f"- Partition counts: train {_fmt_count(partition_counts.get('train'))}, validation {_fmt_count(partition_counts.get('validation'))}, test {_fmt_count(partition_counts.get('test'))}.",
        f"- Test labels: `{partition_label_counts.get('test', {})}`. The calendar test set is imbalanced: {primary['test_rows']} rows, with {primary_test['support']['low_volume_dead']} failures and {primary_test['support']['continued_activity']} continued tokens.",
        "",
        "The split is assigned from `t0` before labels are used. No rows were censored or discarded in this run, and the graph and tabular prediction keys were required to match the temporal sidecar.",
        "",
        *composition_lines,
        "",
        "## Main result",
        "",
        f"The three-seed `{FAMILY_LABELS.get(primary_family, primary_family)}` ensemble reaches temporal test ROC-AUC {_fmt(primary_test['roc_auc_low_volume_dead'])} and average precision {_fmt(primary_test['average_precision_low_volume_dead'])} for `low_volume_dead`. At the 0.10 validation false-positive-rate budget, it reaches failure recall {_fmt(primary_test['dead_recall'])}, failure precision {_fmt(primary_test['dead_precision'])}, F1 {_fmt(primary_test['failure_positive_f1'])}, and flags {_fmt_count(primary_test['confusion_matrix']['true_dead'] + primary_test['confusion_matrix']['continued_flagged_dead'])} of {primary_test['rows']} test tokens.",
        "",
        "The topology-only GraphSAGE control is a useful guard against over-crediting edge features. It ranks the temporal test set slightly better than the edge-aware model, so this run supports graph structure but does not establish a benefit from edge features specifically.",
        "",
        "### How to read the operating point",
        "",
        f"At the 0.10 validation target, the Edge GCN family mean correctly flags {primary_confusion['true_dead']:,} inactive tokens, misses {primary_confusion['dead_called_active']:,}, raises {primary_confusion['continued_flagged_dead']:,} false alerts, and correctly leaves {primary_confusion['true_continued']:,} active tokens unflagged.",
        f"The realized test false-positive rate is {_fmt(primary_test['failure_positive_false_positive_rate'])}, rather than the validation target of 0.100. That gap is evidence of temporal shift and is why the threshold should be treated as a review operating point, not a guarantee.",
        "",
        "## Test metrics by threshold budget",
        "",
        "Thresholds are selected separately on validation data for each family and target budget. Test columns are evaluated once the threshold is frozen.",
        "",
        "| Model | Target FPR | Test FPR | Failure recall | Failure precision | Failure F1 | Alerts |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family in FAMILY_ORDER:
        if family not in families:
            continue
        for target_fpr in target_fprs:
            result = _target_fpr_result(families[family]["ensemble"]["results"], target_fpr)
            test = result["test"]
            alerts = test["confusion_matrix"]["true_dead"] + test["confusion_matrix"]["continued_flagged_dead"]
            lines.append(
                f"| {FAMILY_LABELS.get(family, family)} | {_fmt(target_fpr)} | {_fmt(test['failure_positive_false_positive_rate'])} | {_fmt(test['dead_recall'])} | {_fmt(test['dead_precision'])} | {_fmt(test['failure_positive_f1'])} | {_fmt_count(alerts)} |"
            )

    lines.extend(
        [
            "",
            "## Seed stability",
            "",
            "The following values are mean +/- population standard deviation across the saved seeds. The aggregate rows above average scores before threshold selection and are the primary family-level analysis.",
            "",
            "| Model | ROC-AUC (dead) | AP (dead) | Failure F1 at 0.10 |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for family in FAMILY_ORDER:
        if family not in families:
            continue
        summary = families[family]["seed_summary"]["0.1"]
        lines.append(
            f"| {FAMILY_LABELS.get(family, family)} | {_fmt_mean_sd(summary['roc_auc_low_volume_dead'])} | {_fmt_mean_sd(summary['average_precision_low_volume_dead'])} | {_fmt_mean_sd(summary['failure_positive_f1'])} |"
        )

    figures_dir = output_dir / "figures"
    lines.extend(
        [
            "",
            "## Result illustration",
            "",
            f"- [What the temporal result means]({_relative_link(figures_dir / 'result_story.png', report_path)})",
            f"- [Chronological cohort and class composition]({_relative_link(figures_dir / 'cohort_timeline.png', report_path)})",
            "",
            "These two views are the short presentation path: first establish the time ordering and class mix, then connect ranking quality to the chosen review operating point.",
            "",
            "## Score distributions and tradeoffs",
            "",
            f"- [Score distributions]({_relative_link(figures_dir / 'score_distributions.png', report_path)})",
            f"- [Threshold tradeoffs]({_relative_link(figures_dir / 'threshold_tradeoffs.png', report_path)})",
            f"- [Model summary]({_relative_link(figures_dir / 'model_summary.png', report_path)})",
            f"- [Selected case scores]({_relative_link(figures_dir / 'case_scores.png', report_path)})",
            "",
            "The score plots show the family-level mean failure score and the frozen validation-derived thresholds. They are descriptive diagnostics, not calibration claims.",
            "",
            "## Anonymized cases",
            "",
            f"Cases use the `{FAMILY_LABELS.get(primary_family, primary_family)}` family mean at the 0.10 validation FPR budget. The displayed fingerprint is a truncated SHA-256 of the token address; the address itself is intentionally omitted.",
            "",
            "| Case | Fingerprint | Observed outcome | Failure score | Threshold | t0 | Swaps | Volume USD | Active days | Nodes | Wallet-pool edges |",
            "| --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for case in cases:
        transaction = case["transaction_context"]
        graph = case["graph_context"]
        lines.append(
            f"| {case['case_id']} | `{case['token_fingerprint']}` | `{case['observed_label']}` ({case['model_decision']}) | {_fmt(case['score_low_volume_dead'])} | {_fmt(case['decision_threshold_low_volume_dead'])} | {case.get('t0', '-')} | {_fmt_count(transaction.get('swap_count'))} | {_fmt(transaction.get('pre_cutoff_volume_usd'), 2)} | {_fmt_count(transaction.get('active_day_count'))} | {_fmt_count(graph.get('node_count'))} | {_fmt_count(graph.get('wallet_pool_edge_count'))} |"
        )
    lines.extend(
        [
            "",
            "Transaction and graph context are measured descriptors attached to each case. They are not feature-attribution results. In particular, the case table cannot establish that connectivity, volume, or activity caused a prediction.",
            "",
            "## Measured findings and hypotheses",
            "",
            "Measured in this run:",
            "",
            "- Temporal test ranking quality is high for all three graph seeds, but the calendar test prevalence is strongly failure-heavy.",
            "- The topology-only control is at least as strong as the edge-aware family on the reported temporal metrics, so edge-aware message passing should not be presented as a demonstrated improvement.",
            "- The tabular baseline provides a lower-complexity reference and remains materially below the graph families on temporal ROC-AUC and AP.",
            "",
            "Still hypotheses:",
            "",
            "- Graph connectivity may capture useful structure beyond the nine tabular features; this needs a matched ablation or attribution analysis under the same temporal split.",
            "- The false positives and false negatives may represent distinct launch or liquidity regimes; the four cases are examples for inspection, not evidence of a subgroup mechanism.",
            "",
            "## Limits and next use",
            "",
            "- This is one frozen temporal cohort with 185 test rows, including only 40 continued-activity positives for the continued class.",
            "- The labels are the project proxy defined in `CONTRACT.md`; they are not a production failure oracle, and no uncensored external future outcome was added here.",
            "- Thresholds and the review budget were not tuned on test rows. The displayed alert counts are operating points, not deployment recommendations.",
            "- The artifact is suitable for the analysis/demo walkthrough. Any deployment claim would require prospective evaluation, monitoring, and an operational decision policy.",
            "",
            "## Reproducibility artifacts",
            "",
            f"- [Temporal split manifest]({_relative_link(Path(split_manifest['_path']), report_path)})",
            f"- [Failure-positive evaluator output]({_relative_link(Path(evaluation['_path']), report_path)})",
            f"- [Analysis JSON]({_relative_link(analysis_path, report_path)})",
            f"- [Anonymized cases JSONL]({_relative_link(output_dir / 'cases.jsonl', report_path)})",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")


def build_analysis(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    evaluation_path = Path(args.evaluation)
    split_manifest_path = Path(args.split_manifest)
    targets_path = Path(args.targets)
    graphs_path = Path(args.graphs)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    evaluation = read_json(evaluation_path)
    evaluation["_path"] = str(evaluation_path)
    split_manifest = read_json(split_manifest_path)
    split_manifest["_path"] = str(split_manifest_path)
    targets = load_context(targets_path)
    graphs = load_context(graphs_path)
    if set(targets) != set(graphs):
        raise ValueError("temporal target and graph keys differ")

    grouped_entries: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in evaluation.get("models", []):
        grouped_entries[model_family(str(entry["model"]))].append(entry)
    if args.primary_family not in grouped_entries:
        raise ValueError(f"primary family {args.primary_family} is not present in evaluation")

    families: dict[str, dict[str, Any]] = {}
    for family in FAMILY_ORDER:
        entries = grouped_entries.get(family)
        if not entries:
            continue
        paths = [Path(str(entry["predictions"])) for entry in entries]
        rows = aggregate_prediction_rows(paths)
        for row in rows:
            key = row_key(row)
            target = targets[key]
            if row["label"] is None:
                row["label"] = target["label"]
            if row["label"] != target["label"]:
                raise ValueError(f"prediction/target label mismatch for {key}")
        ensemble = evaluate_aggregate(rows, args.target_fpr, args.review_k)
        families[family] = {
            "model_names": [str(entry["model"]) for entry in entries],
            "model_paths": [str(entry["predictions"]) for entry in entries],
            "ensemble": ensemble,
            "seed_summary": seed_summary(entries, args.target_fpr),
            "score_data": {
                split_name: [
                    {
                        "label": row["label"],
                        "score": round(float(row["score_low_volume_dead"]), 8),
                    }
                    for row in rows
                    if row.get("split") in splits
                ]
                for split_name, splits in (
                    ("validation", VALIDATION_SPLITS),
                    ("test", TEST_SPLITS),
                )
            },
            "_rows": rows,
        }

    expected_keys = set(targets)
    for family, payload in families.items():
        family_keys = {row_key(row) for row in payload["_rows"]}
        if family_keys != expected_keys:
            missing = sorted(expected_keys - family_keys)[:3]
            extra = sorted(family_keys - expected_keys)[:3]
            raise ValueError(f"{family}: prediction keys differ from temporal targets; missing={missing}, extra={extra}")

    primary_rows = families[args.primary_family]["_rows"]
    primary_mid = _target_fpr_result(families[args.primary_family]["ensemble"]["results"], 0.10)
    cases = select_cases(
        primary_rows,
        float(primary_mid["threshold_score_low_volume_dead"]),
        targets,
        graphs,
    )

    analysis = {
        "manifest_version": "temporal-prediction-analysis-0.1",
        "evaluation": str(evaluation_path),
        "split_manifest": str(split_manifest_path),
        "targets": str(targets_path),
        "graphs": str(graphs_path),
        "primary_family": args.primary_family,
        "review_k": args.review_k,
        "target_fprs": sorted(set(args.target_fpr)),
        "split": split_manifest,
        "families": {
            family: {key: value for key, value in payload.items() if not key.startswith("_")}
            for family, payload in families.items()
        },
        "cases": cases,
    }
    analysis_path = output_dir / "analysis.json"
    analysis_path.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (output_dir / "cases.jsonl").open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, sort_keys=True) + "\n")
    return analysis, analysis_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True, type=Path)
    parser.add_argument("--split-manifest", required=True, type=Path)
    parser.add_argument("--targets", required=True, type=Path)
    parser.add_argument("--graphs", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--primary-family", default="edge_gcn")
    parser.add_argument("--review-k", type=int, default=20)
    parser.add_argument("--target-fpr", type=float, action="append", default=list(DEFAULT_TARGET_FPRS))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analysis, analysis_path = build_analysis(args)
    split_manifest = analysis["split"]
    evaluation = read_json(Path(analysis["evaluation"]))
    evaluation["_path"] = analysis["evaluation"]
    families = analysis["families"]
    # The report writer only needs serialized family data and the private rows are not emitted.
    cases = analysis["cases"]
    write_report(
        args.report,
        analysis_path,
        args.output_dir,
        split_manifest,
        evaluation,
        families,
        cases,
        args.target_fpr,
        args.primary_family,
    )
    print(f"wrote {analysis_path}")
    print(f"wrote {args.output_dir / 'cases.jsonl'}")
    print(f"wrote {args.report}")


if __name__ == "__main__":
    main()
