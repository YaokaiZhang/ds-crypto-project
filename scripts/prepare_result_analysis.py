#!/usr/bin/env python3
"""Prepare reproducible inputs for the whole-project analysis.

This phase runs in the project uv environment because it reads the frozen
Parquet products through DuckDB. It retains token symbols from the frozen pool
scope and omits full contract addresses from the public-facing bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--data-product", type=Path, required=True)
    parser.add_argument("--general-evaluation", type=Path, required=True)
    parser.add_argument("--edge-evaluation", type=Path, required=True)
    parser.add_argument("--temporal-evaluation", type=Path, required=True)
    parser.add_argument("--temporal-analysis", type=Path, required=True)
    parser.add_argument("--general-targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            rows.append(value)
    return rows


def fingerprint(token_address: str) -> str:
    return hashlib.sha256(token_address.lower().encode("ascii")).hexdigest()[:16]


def finite_float(value: Any) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def relative_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def git_head(project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def query_rows(connection: duckdb.DuckDBPyConnection, data_product: Path) -> list[dict[str, Any]]:
    features = data_product / "features.parquet"
    outcomes = data_product / "outcomes.parquet"
    splits = data_product / "splits.parquet"
    temporal_splits = data_product.parent / "model_split_temporal_wallet_graph_20261005_v1" / "splits.parquet"
    tokens = data_product / "tokens.parquet"
    pools = data_product / "pools.parquet"
    audit = data_product / "feature_audit.parquet"
    query = """
        WITH token_symbols AS (
            SELECT
                token_address,
                source_dataset,
                MAX(
                    CASE
                        WHEN lower(token0) = lower(token_address) THEN token0_symbol
                        WHEN lower(token1) = lower(token_address) THEN token1_symbol
                    END
                ) AS token_symbol
            FROM read_parquet(?)
            GROUP BY token_address, source_dataset
        )
        SELECT
            f.token_address,
            f.source_dataset,
            f.t0,
            f.cutoff,
            f.observation_days,
            f.event_count,
            f.swap_count,
            f.mint_count,
            f.burn_count,
            CAST(f.pre_cutoff_volume_usd AS DOUBLE) AS pre_cutoff_volume_usd,
            f.pre_cutoff_missing_swap_usd_count,
            f.active_day_count,
            f.pool_count,
            f.protocol_count,
            f.feature_complete,
            f.feature_status,
            o.label,
            s.partition AS general_partition,
            tm.partition AS temporal_partition,
            s.censoring_status,
            t.launch_period,
            ps.token_symbol,
            fa.raw_event_count,
            fa.pre_t0_event_count,
            fa.post_cutoff_event_count,
            fa.missing_timestamp_count
        FROM read_parquet(?) AS f
        JOIN read_parquet(?) AS o USING (token_address, source_dataset)
        JOIN read_parquet(?) AS s USING (token_address, source_dataset)
        JOIN read_parquet(?) AS tm USING (token_address, source_dataset)
        JOIN read_parquet(?) AS t USING (token_address, source_dataset)
        JOIN read_parquet(?) AS fa USING (token_address, source_dataset)
        LEFT JOIN token_symbols AS ps USING (token_address, source_dataset)
        ORDER BY f.token_address
    """
    cursor = connection.execute(
        query,
        [str(pools), str(features), str(outcomes), str(splits), str(temporal_splits), str(tokens), str(audit)],
    )
    column_names = [item[0] for item in cursor.description]
    result: list[dict[str, Any]] = []
    for raw in cursor.fetchall():
        row = dict(zip(column_names, raw))
        address = str(row.pop("token_address"))
        row.pop("source_dataset", None)
        row["token_fingerprint"] = fingerprint(address)
        for key in FEATURE_NAMES:
            row[key] = finite_float(row[key])
        result.append(row)
    if len(result) != 2000:
        raise ValueError(f"expected 2000 joined rows, found {len(result)}")
    return result


def load_graph_summary(path: Path, fingerprints: dict[str, str]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for raw in read_jsonl(path):
        address = str(raw.pop("token_address"))
        item = {
            "token_fingerprint": fingerprints[address],
            "partition": raw.get("partition"),
            "window_swap_count": raw.get("window_swap_count"),
            "wallet_edge_count": raw.get("wallet_edge_count"),
            "selected_pool_count": raw.get("selected_pool_count"),
            "participant_sender_coverage": raw.get("participant_sender_coverage"),
            "model_ready": raw.get("model_ready"),
            "status": raw.get("status"),
        }
        summary.append(item)
    return summary


def canonical_model(name: str) -> str:
    if "edge_gcn" in name:
        return "Edge GCN"
    if "topology_sage" in name or name.startswith("wallet_"):
        return "Topology GraphSAGE"
    if "tabular" in name:
        return "Tabular logistic"
    return name


def evaluation_rows(path: Path, split_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = read_json(path)
    rows: list[dict[str, Any]] = []
    score_members: list[dict[str, Any]] = []
    for model in data.get("models", []):
        raw_name = str(model["model"])
        family = canonical_model(raw_name)
        for result in model.get("results", []):
            validation = result["validation"]
            test = result["test"]
            test_confusion = test.get("confusion_matrix", {})
            continued_flagged_dead = test.get(
                "continued_flagged_dead", test_confusion.get("continued_flagged_dead", 0)
            )
            true_dead = test.get("true_dead", test_confusion.get("true_dead", 0))
            rows.append(
                {
                    "analysis_split": split_name,
                    "model": family,
                    "model_run": raw_name,
                    "evaluation_level": "seed",
                    "target_failure_positive_fpr": result["target_failure_positive_fpr"],
                    "validation_fpr": validation["failure_positive_false_positive_rate"],
                    "validation_failure_recall": validation["dead_recall"],
                    "validation_failure_precision": validation["dead_precision"],
                    "validation_failure_f1": validation["failure_positive_f1"],
                    "test_fpr": test["failure_positive_false_positive_rate"],
                    "test_failure_recall": test["dead_recall"],
                    "test_failure_precision": test["dead_precision"],
                    "test_failure_f1": test["failure_positive_f1"],
                    "test_roc_auc": test["roc_auc_low_volume_dead"],
                    "test_average_precision": test["average_precision_low_volume_dead"],
                    "test_alerts": continued_flagged_dead + true_dead,
                    "test_rows": test["rows"],
                    "review_k": test.get("review_k"),
                    "precision_at_k": test.get("precision_at_k"),
                    "threshold": result["threshold_score_low_volume_dead"],
                }
            )
        prediction_path = Path(str(model["predictions"]))
        if prediction_path.exists():
            for prediction in read_jsonl(prediction_path):
                score = prediction.get("score_low_volume_dead")
                if score is None and prediction.get("score_continued_activity") is not None:
                    score = 1.0 - float(prediction["score_continued_activity"])
                if score is None:
                    continue
                score_members.append(
                    {
                        "analysis_split": split_name,
                        "model": family,
                        "model_run": raw_name,
                        "token_address": str(prediction["token_address"]),
                        "source_dataset": str(prediction.get("source_dataset", "")),
                        "partition": prediction.get("partition"),
                        "label": prediction.get("label"),
                        "score_low_volume_dead": float(score),
                    }
                )
    return rows, score_members


def ensemble_evaluation_rows(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Use the saved temporal family-ensemble metrics as primary summaries."""
    rows: list[dict[str, Any]] = []
    for family_name, family in analysis.get("families", {}).items():
        family_label = canonical_model(str(family_name))
        ensemble = family.get("ensemble", {})
        for result in ensemble.get("results", []):
            validation = result["validation"]
            test = result["test"]
            test_confusion = test.get("confusion_matrix", {})
            continued_flagged_dead = test.get(
                "continued_flagged_dead", test_confusion.get("continued_flagged_dead", 0)
            )
            true_dead = test.get("true_dead", test_confusion.get("true_dead", 0))
            rows.append(
                {
                    "analysis_split": "temporal",
                    "model": family_label,
                    "model_run": f"{family_name}_ensemble",
                    "evaluation_level": "ensemble",
                    "target_failure_positive_fpr": result["target_failure_positive_fpr"],
                    "validation_fpr": validation["failure_positive_false_positive_rate"],
                    "validation_failure_recall": validation["dead_recall"],
                    "validation_failure_precision": validation["dead_precision"],
                    "validation_failure_f1": validation["failure_positive_f1"],
                    "test_fpr": test["failure_positive_false_positive_rate"],
                    "test_failure_recall": test["dead_recall"],
                    "test_failure_precision": test["dead_precision"],
                    "test_failure_f1": test["failure_positive_f1"],
                    "test_roc_auc": test["roc_auc_low_volume_dead"],
                    "test_average_precision": test["average_precision_low_volume_dead"],
                    "test_alerts": continued_flagged_dead + true_dead,
                    "test_rows": test["rows"],
                    "review_k": test.get("review_k"),
                    "precision_at_k": test.get("precision_at_k"),
                    "threshold": result["threshold_score_low_volume_dead"],
                }
            )
    return rows


def aggregate_scores(
    members: Iterable[dict[str, Any]],
    fingerprints_by_key: dict[tuple[str, str], str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for member in members:
        key = (member["analysis_split"], member["model"], member["token_address"])
        grouped[key].append(member)
    result: list[dict[str, Any]] = []
    for (analysis_split, model, address), group in sorted(grouped.items()):
        scores = [float(item["score_low_volume_dead"]) for item in group]
        mean = sum(scores) / len(scores)
        variance = sum((score - mean) ** 2 for score in scores) / len(scores)
        first = group[0]
        result.append(
            {
                "analysis_split": analysis_split,
                "model": model,
                "token_fingerprint": fingerprints_by_key[(address, first["source_dataset"])],
                "partition": first["partition"],
                "label": first["label"],
                "score_low_volume_dead": mean,
                "score_seed_sd": math.sqrt(variance),
                "member_count": len(scores),
            }
        )
    return result


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    data_product = args.data_product.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect()
    rows = query_rows(connection, data_product)
    fingerprints_by_key = {}
    for row in rows:
        # source_dataset is fixed for this cohort, but retain the key shape for
        # joins against prediction files.
        fingerprints_by_key[(row["token_fingerprint"], "wallet_graph_events_20261003_2000")] = row["token_fingerprint"]
    address_to_fingerprint = {
        str(item[0]): fingerprint(str(item[0]))
        for item in connection.execute(
            "SELECT token_address FROM read_parquet(?)", [str(data_product / "tokens.parquet")]
        ).fetchall()
    }
    prediction_fingerprints: dict[tuple[str, str], str] = {}
    for address, token_fingerprint in address_to_fingerprint.items():
        prediction_fingerprints[(address, "wallet_graph_events_20261003_2000")] = token_fingerprint

    general_rows, general_scores = evaluation_rows(args.edge_evaluation.resolve(), "general_stratified")
    temporal_rows, temporal_scores = evaluation_rows(args.temporal_evaluation.resolve(), "temporal")
    analysis = read_json(args.temporal_analysis.resolve())
    eval_rows = general_rows + temporal_rows + ensemble_evaluation_rows(analysis)
    score_rows = aggregate_scores(general_scores + temporal_scores, prediction_fingerprints)
    symbols_by_fingerprint = {
        str(row["token_fingerprint"]): str(row["token_symbol"])
        for row in rows
        if row.get("token_symbol")
    }
    cases = []
    for raw_case in analysis.get("cases", []):
        case = dict(raw_case)
        fingerprint_value = str(case.get("token_fingerprint", ""))
        case["token_symbol"] = symbols_by_fingerprint.get(fingerprint_value, "Symbol unavailable")
        cases.append(case)

    graph_summary = load_graph_summary(
        data_product.parent / "wallet_graph_input_20261003_2000_v4" / "graph_quality.jsonl",
        address_to_fingerprint,
    )

    source_paths = [
        data_product / "features.parquet",
        data_product / "outcomes.parquet",
        data_product / "splits.parquet",
        data_product / "tokens.parquet",
        data_product / "pools.parquet",
        data_product / "feature_audit.parquet",
        data_product.parent / "model_split_temporal_wallet_graph_20261005_v1" / "splits.parquet",
        args.general_evaluation.resolve(),
        args.edge_evaluation.resolve(),
        args.temporal_evaluation.resolve(),
        args.temporal_analysis.resolve(),
        data_product.parent / "wallet_graph_input_20261003_2000_v4" / "feature_schema.json",
        data_product.parent / "wallet_graph_input_20261003_2000_v4" / "edge_schema.json",
        data_product.parent / "wallet_graph_input_20261003_2000_v4" / "graph_manifest.json",
    ]
    schemas = {
        "feature_schema": read_json(
            data_product.parent / "wallet_graph_input_20261003_2000_v4" / "feature_schema.json"
        ),
        "edge_schema": read_json(
            data_product.parent / "wallet_graph_input_20261003_2000_v4" / "edge_schema.json"
        ),
        "graph_manifest": read_json(
            data_product.parent / "wallet_graph_input_20261003_2000_v4" / "graph_manifest.json"
        ),
    }

    analysis_data = {
        "manifest_version": "result-analysis-input-0.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head(project_root),
        "feature_names": FEATURE_NAMES,
        "rows": rows,
        "graph_summary": graph_summary,
        "evaluation_rows": eval_rows,
        "score_rows": score_rows,
        "cases": cases,
        "schemas": schemas,
        "source_paths": [relative_path(path, project_root) for path in source_paths],
        "public_artifacts_anonymized": False,
        "token_identifier_policy": "token symbols retained; full contract addresses omitted",
    }
    (output / "analysis_data.json").write_text(
        json.dumps(analysis_data, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "manifest_version": "result-analysis-run-0.1",
        "generated_at": analysis_data["generated_at"],
        "git_head": analysis_data["git_head"],
        "row_count": len(rows),
        "graph_quality_rows": len(graph_summary),
        "evaluation_rows": len(eval_rows),
        "score_rows": len(score_rows),
        "feature_names": FEATURE_NAMES,
        "source_paths": analysis_data["source_paths"],
        "test_labels_used_for": "post-hoc descriptive EDA and locked evaluation summaries only",
        "test_labels_not_used_for": "feature selection, model fitting, threshold selection, review-budget selection, or tuning",
        "token_address_policy": "full addresses are omitted; token symbols are retained and fingerprints support internal joins",
        "token_symbol_rows": sum(bool(row.get("token_symbol")) for row in rows),
    }
    (output / "analysis_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
