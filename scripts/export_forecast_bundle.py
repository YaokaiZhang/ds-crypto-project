"""Export the Task A edge-GCN seed ensemble as a checked Forecast bundle.

Reads existing training runs only; never trains, refits scalers or tunes on the
test holdout. The ensemble threshold is selected on validation predictions with
the training script's rule (balanced accuracy, then macro-F1). The written
bundle is reloaded and must reproduce the recorded ensemble scores for every
graph in the training dataset; otherwise the export fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.forecast import export_forecast_bundle, load_forecast_bundle, predict_forecast
from scripts.train_graphsage import average_precision, classification_metrics, safe_auc, select_threshold


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def split_metrics(rows: list[dict], threshold: float) -> dict:
    labels = [row["label_int"] for row in rows]
    scores = [row["score"] for row in rows]
    metrics = classification_metrics(labels, scores, threshold)
    return {"rows": len(rows), "roc_auc": safe_auc(labels, scores), "average_precision": average_precision(labels, scores),
            **{key: metrics[key] for key in ("balanced_accuracy", "macro_f1", "f1_continued_activity",
                                             "f1_low_volume_dead", "false_positive_rate", "confusion_matrix")}}


def export(args: argparse.Namespace) -> dict:
    runs = [Path(run).resolve() for run in args.runs]
    checkpoints, configs, normalizations, predictions = [], [], [], []
    for run in runs:
        checkpoint = torch.load(run / "model.pt", map_location="cpu", weights_only=True)
        metrics = json.loads((run / "metrics.json").read_text())
        if checkpoint["architecture"] != "edge_gcn" or metrics["architecture"]["name"] != "edge_gcn":
            raise ValueError(f"{run.name} is not an edge_gcn run")
        architecture = metrics["architecture"]
        configs.append({"architecture_id": "edge_gcn", "hidden_dim": architecture["hidden_dim"],
                        "layers": architecture["layers"], "dropout": architecture["dropout"]})
        normalizations.append(json.loads((run / "feature_normalization.json").read_text()))
        predictions.append({row["token_address"]: row for row in read_jsonl(run / "predictions.jsonl")})
        checkpoints.append((run, checkpoint, metrics))
    if any(config != configs[0] for config in configs) or any(n != normalizations[0] for n in normalizations):
        raise ValueError("ensemble members must share architecture and training scaler")
    if any(p.keys() != predictions[0].keys() for p in predictions):
        raise ValueError("ensemble members must score the same tokens")

    graphs = read_jsonl(Path(args.graphs))
    names = {"node": graphs[0]["node_feature_names"], "edge": graphs[0]["edge_feature_names"]}
    normalization = normalizations[0]
    if normalization["edge"]["feature_names"] != names["edge"] or len(normalization["node"]["mean"]) != len(names["node"]):
        raise ValueError("training scaler does not match the graph feature schema")
    scaler = {"node_feature_names": names["node"], "node_mean": normalization["node"]["mean"],
              "node_std": normalization["node"]["std"], "edge_feature_names": names["edge"],
              "edge_mean": normalization["edge"]["mean"], "edge_std": normalization["edge"]["std"],
              "fit_split": "train", "source": "Task A training feature_normalization.json"}

    ensemble = []
    for token, row in predictions[0].items():
        if any(p[token]["label_int"] != row["label_int"] or p[token]["split"] != row["split"] for p in predictions):
            raise ValueError("ensemble members disagree on labels/splits")
        ensemble.append({"token_address": token, "split": row["split"], "label_int": row["label_int"],
                         "score": sum(p[token]["score_continued_activity"] for p in predictions) / len(predictions)})
    validation = [row for row in ensemble if row["split"] == "validation"]
    threshold = select_threshold([row["label_int"] for row in validation], [row["score"] for row in validation])
    evaluation = {split: split_metrics([row for row in ensemble if row["split"] == split], threshold)
                  for split in ("train", "validation", "test_holdout")}

    metadata = {
        "model_family": "Task A first-week wallet graph edge-aware GCN",
        "score_target": "continued_activity", "positive_outcome": "continued_activity",
        "negative_outcome": "low_volume_dead", "observation_days": 7, "horizon_days": 90,
        "swap_volume_threshold_usd": "1000",
        "threshold_selection": "validation ensemble predictions; balanced accuracy, then macro-F1",
        "training": {"split_name": args.split_name, "graphs_sha256": hashlib.sha256(Path(args.graphs).read_bytes()).hexdigest(),
                     "graph_count": len(graphs), "test_use": "reported only; not used for checkpoint or threshold selection",
                     "ensemble_metrics": evaluation},
        "input_notes": ("Trained with historical USD swap volumes. Inputs without amount_usd carry zero "
                        "log1p_positive_volume_usd and are outside the training distribution."),
    }
    members = [(f"member-{metrics['seed']}.pt", checkpoint["model_state_dict"],
                {"seed": metrics["seed"], "source_run": run.name, "best_epoch": metrics["training"]["best_epoch"],
                 "member_threshold": metrics["training"]["decision_threshold_continued_activity"]})
               for run, checkpoint, metrics in checkpoints]
    manifest = export_forecast_bundle(args.output, members, configs[0], scaler, threshold, metadata)

    # The exported bundle must reproduce the recorded research scores.
    bundle = load_forecast_bundle(args.output)
    graph_scores = predict_forecast(bundle, graphs, batch_size=256)
    expected = {row["token_address"]: row["score"] for row in ensemble}
    difference = max(abs(score - expected[graph["token_address"]]) for graph, score in zip(graphs, graph_scores))
    if difference > args.tolerance:
        raise ValueError(f"bundle does not reproduce recorded ensemble scores (max diff {difference})")
    report = {"model_version": manifest["model_version"], "threshold": threshold, "max_abs_score_difference": difference,
              "verified_graphs": len(graphs), "ensemble_metrics": evaluation}
    if args.full_graphs:
        # Full 18/11-feature graphs (the live backend schema) select the same columns by name.
        full = read_jsonl(Path(args.full_graphs))
        full_scores = predict_forecast(bundle, full, batch_size=256)
        report["max_abs_full_schema_difference"] = max(
            abs(score - expected[graph["token_address"]]) for graph, score in zip(full, full_scores))
        if report["max_abs_full_schema_difference"] > args.tolerance:
            raise ValueError("full-schema graphs do not reproduce recorded ensemble scores")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", required=True, help="Task A edge_gcn run directories (one per seed)")
    parser.add_argument("--graphs", required=True, help="graphs.jsonl the runs were trained on")
    parser.add_argument("--full-graphs", help="optional unpruned graphs.jsonl for schema-selection verification")
    parser.add_argument("--split-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=1e-5)
    print(json.dumps(export(parser.parse_args()), indent=2))


if __name__ == "__main__":
    main()
