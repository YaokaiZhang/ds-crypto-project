"""Task B offline training, matched baselines and frozen evaluation helpers.

Importing this module or validating a configuration does not start training.
Honeypot and rug-pull remain data-only branches in this release.
"""

from __future__ import annotations

from collections import Counter
import copy
import json
import math
from pathlib import Path
import random
import shutil
from types import MappingProxyType
from typing import Any, Sequence

from .splitting import PARTITIONS, _unix, assert_partition_isolation, experiment_record, task_name
from chainrisk.tasks import get_task


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(config)
    result["task_id"] = task_name(str(result["task_id"]))
    result.setdefault("experiment_mode", "known_positive_vs_unlabeled" if result["task_id"] == "phishing" else "supervised")
    if result["experiment_mode"] not in {"supervised", "supervised_binary", "known_positive_vs_unlabeled", "nnpu"}:
        raise ValueError("unsupported experiment_mode")
    model = result.setdefault("model", {})
    model.setdefault("architecture_id", "mean_sage")
    model.setdefault("layers", 2)
    model.setdefault("hidden_dim", 64)
    model.setdefault("dropout", 0.2)
    for key in ("ignore_direction", "ignore_relations", "ignore_edge_attr"):
        model.setdefault(key, False)
    if model["architecture_id"] not in {"mean_sage", "directed_edge_sage"}:
        raise ValueError("unsupported architecture_id")
    if (model["layers"] not in {2, 3} or not isinstance(model["hidden_dim"], int)
            or isinstance(model["hidden_dim"], bool) or model["hidden_dim"] <= 0
            or not isinstance(model["dropout"], (int, float)) or not 0 <= model["dropout"] < 1):
        raise ValueError("invalid model depth, dimension or dropout")
    loss = result.setdefault("loss", {})
    loss.setdefault("name", "weighted_bce")
    if loss["name"] not in {"weighted_bce", "focal", "nnpu"}:
        raise ValueError("unsupported loss")
    if loss["name"] == "focal":
        loss.setdefault("gamma", 2.0)
        if not isinstance(loss["gamma"], (int, float)) or not math.isfinite(loss["gamma"]) or loss["gamma"] < 0:
            raise ValueError("focal gamma must be non-negative")
    if result.get("balanced_sampling", False):
        raise ValueError("balanced sampling plus class-weighted loss is not admitted")
    if loss["name"] == "nnpu" or result["experiment_mode"] == "nnpu":
        raise NotImplementedError("nnPU is not implemented in this release; class prior and positive/U sampling need a separately audited protocol")
    defaults = {
        "seed": 20261008, "batch_size": 32, "epochs": 200,
        "patience": 25, "learning_rate": 0.001, "weight_decay": 0.0001,
        "min_delta": 0.0001, "device": "cpu", "training_as_of": None,
        "fit_tabular_baselines": True, "precision_at_k": 10,
    }
    for key, value in defaults.items():
        result.setdefault(key, value)
    for key in ("seed", "batch_size", "epochs", "patience", "precision_at_k"):
        if not isinstance(result[key], int) or isinstance(result[key], bool):
            raise ValueError(f"{key} must be an integer")
    for key in ("learning_rate", "weight_decay", "min_delta"):
        if not isinstance(result[key], (int, float)) or not math.isfinite(result[key]):
            raise ValueError(f"{key} must be finite")
    if any(result[key] <= 0 for key in ("batch_size", "epochs", "patience", "learning_rate", "precision_at_k")) or result["weight_decay"] < 0 or result["min_delta"] < 0:
        raise ValueError("invalid optimizer/training configuration")
    if result["device"] not in {"cpu", "cuda", "mps", "auto"}:
        raise ValueError("device must be cpu, cuda, mps or auto")
    return result


def merge_dataset(
    graphs: Sequence[dict[str, Any]], supervision: Sequence[dict[str, Any]],
    splits: Sequence[dict[str, Any]], config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Join frozen artifacts and reject target/group, quality or time leakage."""
    from chainrisk.graph import graph_is_usable, validate_graph_sample
    config = validate_config(config)

    def index(rows: Sequence[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row["sample_id"])
            if key in result:
                raise ValueError(f"duplicate sample_id in {label}: {key}")
            result[key] = row
        return result

    graph_index, split_index = index(graphs, "graphs"), index(splits, "splits")
    supervision_index = index(supervision, "supervision")
    selected: list[dict[str, Any]] = []
    excluded = Counter()
    for sample, canonical in supervision_index.items():
        if task_name(str(canonical["task_id"])) != config["task_id"]:
            continue
        experiment = experiment_record(canonical, config["experiment_mode"])
        if not experiment["experiment_eligible"]:
            excluded[str(canonical.get("label_status", "missing_label_status"))] += 1
            continue
        split = split_index.get(sample)
        if split is None or split.get("partition") not in PARTITIONS:
            raise ValueError(f"eligible sample has no frozen partition: {sample}")
        if split.get("experiment_mode", config["experiment_mode"]) != config["experiment_mode"]:
            raise ValueError(f"split experiment_mode mismatch: {sample}")
        if split.get("observed_target") != experiment["observed_target"]:
            raise ValueError(f"split supervision target mismatch: {sample}")
        graph = graph_index.get(sample)
        if graph is None:
            raise ValueError(f"eligible sample has no graph: {sample}")
        validate_graph_sample(graph)
        if not graph_is_usable(graph):
            raise ValueError(f"eligible sample has unusable graph quality: {sample}")
        if task_name(str(graph["task_id"])) != config["task_id"]:
            raise ValueError(f"graph task mismatch: {sample}")
        entity = str(canonical.get("entity_id") or canonical.get("target") or "").lower()
        if not entity or str(graph["target"]).lower() != entity:
            raise ValueError(f"graph target mismatch: {sample}")
        if canonical.get("cutoff") is not None and canonical["cutoff"] != graph["cutoff"]:
            raise ValueError(f"graph cutoff mismatch: {sample}")
        if canonical.get("chain_id", 1) != graph.get("chain_id", 1):
            raise ValueError(f"graph chain mismatch: {sample}")
        experiment.update(partition=split["partition"], split_group_id=split.get("split_group_id"))
        if experiment["partition"] == "train" and canonical["label_status"] != "unlabeled" and config["training_as_of"] is not None:
            available = _unix(canonical.get("label_available_at"))
            if available is None or available > config["training_as_of"]:
                raise ValueError(f"training label unavailable at training_as_of: {sample}")
        selected.append({"graph": graph, "supervision": experiment})
    assert_partition_isolation([row["supervision"] for row in selected])
    selected.sort(key=lambda row: str(row["graph"]["sample_id"]))
    expected_schema: tuple[Any, ...] | None = None
    graph_recipe: dict[str, Any] | None = None
    for row in selected:
        graph = row["graph"]
        schema = tuple(json.dumps(graph.get(key), sort_keys=True) for key in (
            "schema_version", "graph_view_version", "feature_names", "edge_feature_names", "relation_names",
        ))
        if expected_schema is not None and schema != expected_schema:
            raise ValueError("graph feature/relation/schema mismatch within experiment")
        expected_schema = schema
        lineage = graph.get("lineage", {})
        recipe = {"builder": lineage.get("graph_builder"), "sampling": lineage.get("sampling")}
        if not recipe["builder"] or not isinstance(recipe["sampling"], dict):
            raise ValueError("training graphs require an explicit graph builder/sampling recipe")
        if graph_recipe is not None and recipe != graph_recipe:
            raise ValueError("graph builder/sampling recipe differs within experiment")
        graph_recipe = copy.deepcopy(recipe)
    partition_counts: dict[str, dict[str, int]] = {}
    for partition in PARTITIONS:
        counts = Counter(row["supervision"]["observed_target"] for row in selected if row["supervision"]["partition"] == partition)
        if set(counts) != {0, 1}:
            raise ValueError(f"partition {partition} must contain both observed classes")
        partition_counts[partition] = {str(key): value for key, value in sorted(counts.items())}
    node_sets = {partition: {node for row in selected if row["supervision"]["partition"] == partition for node in row["graph"]["node_refs"]} for partition in PARTITIONS}
    heldout_targets = {row["graph"]["target"] for row in selected if row["supervision"]["partition"] != "train"}
    manifest = {
        "task_id": config["task_id"], "experiment_mode": config["experiment_mode"],
        "eligible_samples": len(selected), "excluded_by_status": dict(excluded),
        "graph_recipe": graph_recipe,
        "partition_class_counts": partition_counts,
        "negative_meaning": "frozen unlabeled background; not verified benign" if config["experiment_mode"] in {"known_positive_vs_unlabeled", "nnpu"} else "task-specific admitted negative",
        "leakage_checks": ["entity/group partition isolation", "graph cutoff/chain/target join", "compatible feature and relation schemas", "graph quality", "train label availability when configured"],
        "neighborhood_overlap_counts": {f"{left}_{right}": len(node_sets[left] & node_sets[right]) for left, right in (("train", "validation"), ("train", "test"), ("validation", "test"))},
        "heldout_targets_in_train_neighborhood": len(heldout_targets & node_sets["train"]),
        "message_passing": "disconnected ego graphs; no persistent address embeddings or label propagation",
    }
    return selected, manifest


def _weighted_bce_strategy(logits: Any, targets: Any, config: dict[str, Any], pos_weight: float) -> Any:
    import torch
    from torch.nn import functional as functional
    loss = functional.binary_cross_entropy_with_logits(logits, targets, reduction="none")
    weights = torch.where(targets == 1, torch.full_like(targets, pos_weight), torch.ones_like(targets))
    return (weights * loss).mean()


def _focal_strategy(logits: Any, targets: Any, config: dict[str, Any], pos_weight: float) -> Any:
    import torch
    from torch.nn import functional as functional
    gamma = float(config.get("gamma", 2.0))
    if gamma < 0:
        raise ValueError("focal gamma must be non-negative")
    loss = functional.binary_cross_entropy_with_logits(logits, targets, reduction="none")
    weights = torch.where(targets == 1, torch.full_like(targets, pos_weight), torch.ones_like(targets))
    probability = torch.sigmoid(logits)
    p_correct = torch.where(targets == 1, probability, 1 - probability)
    return (weights * (1 - p_correct).pow(gamma) * loss).mean()


LOSS_STRATEGIES = MappingProxyType({"weighted_bce": _weighted_bce_strategy, "focal": _focal_strategy})


def binary_loss(logits: Any, targets: Any, loss_config: dict[str, Any], pos_weight: float, mask: Any = None) -> Any:
    """Resolve a registered loss after masking unsupported supervision."""
    import torch
    if loss_config.get("name") == "nnpu":
        raise NotImplementedError("nnPU is not implemented in this release")
    if mask is not None:
        logits, targets = logits[mask], targets[mask]
    if targets.numel() == 0:
        raise ValueError("batch has no eligible supervision")
    if not torch.all((targets == 0) | (targets == 1)):
        raise ValueError("binary targets must be exactly zero or one")
    if not math.isfinite(pos_weight) or pos_weight <= 0:
        raise ValueError("pos_weight must be positive and finite")
    try:
        strategy = LOSS_STRATEGIES[loss_config.get("name", "weighted_bce")]
    except KeyError as error:
        raise ValueError("unsupported binary loss") from error
    return strategy(logits, targets, loss_config, pos_weight)


def metrics(labels: Sequence[int], scores: Sequence[float], threshold: float = 0.5, k: int = 10) -> dict[str, Any]:
    from sklearn.metrics import (
        accuracy_score, average_precision_score, balanced_accuracy_score,
        confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score,
    )
    if not labels or len(labels) != len(scores) or any(label not in (0, 1) for label in labels):
        raise ValueError("metrics require equal non-empty binary labels/scores")
    if any(not math.isfinite(score) or not 0 <= score <= 1 for score in scores):
        raise ValueError("scores must be finite in [0,1]")
    if not math.isfinite(threshold) or not 0 <= threshold <= 1 or k <= 0:
        raise ValueError("invalid threshold or Precision@K")
    predicted = [int(score >= threshold) for score in scores]
    tn, fp, fn, tp = confusion_matrix(labels, predicted, labels=[0, 1]).ravel().tolist()
    both = len(set(labels)) == 2
    ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], index))[:min(k, len(scores))]
    return {
        "rows": len(labels), "label_counts": {"positive": sum(labels), "negative": len(labels) - sum(labels)},
        "accuracy": float(accuracy_score(labels, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predicted)) if both else None,
        "average_precision": float(average_precision_score(labels, scores)) if any(labels) else None,
        "roc_auc": float(roc_auc_score(labels, scores)) if both else None,
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1_positive": float(f1_score(labels, predicted, zero_division=0)),
        "macro_f1": float(f1_score(labels, predicted, labels=[0, 1], average="macro", zero_division=0)),
        "false_positive_rate": fp / (tn + fp) if tn + fp else None,
        "precision_at_k": sum(labels[index] for index in ranked) / len(ranked),
        "k": len(ranked), "precision_at_k_tie_policy": "stable sample order",
        "threshold": threshold, "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
    }


def select_threshold(labels: Sequence[int], scores: Sequence[float]) -> float:
    """Select only on validation; macro-F1, precision, then proximity to .5."""
    candidates = sorted({0.0, 0.5, 1.0, *map(float, scores)})
    best: tuple[float, float, float, float] | None = None
    result = 0.5
    for threshold in candidates:
        report = metrics(labels, scores, threshold)
        key = (report["macro_f1"], report["precision"], -abs(threshold - 0.5), threshold)
        if best is None or key > best:
            best, result = key, threshold
    return result


def _score(model: Any, rows: Sequence[dict[str, Any]], scaler: dict[str, Any], device: Any, batch_size: int) -> tuple[list[int], list[float]]:
    import torch
    from chainrisk.graph import batch_graph_samples
    labels: list[int] = []
    scores: list[float] = []
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(rows), batch_size):
            batch_rows = rows[start:start + batch_size]
            batch = batch_graph_samples([row["graph"] for row in batch_rows], scaler, device=device, add_reverse=True)
            scores.extend(torch.sigmoid(model(batch)).cpu().tolist())
            labels.extend(row["supervision"]["observed_target"] for row in batch_rows)
    return labels, scores


def evaluate(model: Any, rows: Sequence[dict[str, Any]], scaler: dict[str, Any], threshold: float = 0.5, device: Any = "cpu", batch_size: int = 32, k: int = 10) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    labels, scores = _score(model, rows, scaler, device, batch_size)
    predictions = [{
        "sample_id": row["graph"]["sample_id"], "task_id": row["graph"]["task_id"],
        "target": row["graph"]["target"], "cutoff": row["graph"]["cutoff"],
        "partition": row["supervision"]["partition"], "observed_target": label,
        "label_status": row["supervision"]["label_status"], "score": float(score),
        "predicted_label": int(score >= threshold),
    } for row, label, score in zip(rows, labels, scores)]
    return metrics(labels, scores, threshold, k), predictions


def tabular_features(graph: dict[str, Any], neighborhood: bool = False) -> list[float]:
    """Own features; optional bounded graph summaries with matched provenance."""
    import numpy as np
    nodes = np.asarray(graph["node_features"], dtype=float)
    root = int(graph["root_index"])
    result = nodes[root].tolist()
    if neighborhood:
        other = np.delete(nodes, root, axis=0)
        if len(other):
            result += other.mean(axis=0).tolist() + other.std(axis=0).tolist()
        else:
            result += [0.0] * (2 * nodes.shape[1])
        edge_dim = len(graph["edge_feature_names"])
        edges = np.asarray(graph["edge_attributes"], dtype=float).reshape(-1, edge_dim)
        result += edges.mean(axis=0).tolist() if len(edges) else [0.0] * edge_dim
        result += [math.log1p(len(nodes)), math.log1p(len(graph["relation_ids"]))]
        counts = Counter(graph["relation_ids"])
        result += [math.log1p(counts[index]) for index in range(len(graph["relation_names"]))]
    return result


def fit_tabular_baselines(rows: Sequence[dict[str, Any]], config: dict[str, Any], output: Path) -> dict[str, Any]:
    """Fit both baselines on exactly the GraphSAGE cohort and locked splits."""
    import joblib
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    models = {
        "logistic_own_features": (make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000, random_state=config["seed"])), False),
        "hist_gradient_boosting_neighborhood": (HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15, l2_regularization=1.0, early_stopping=False, random_state=config["seed"]), True),
    }
    partitions = {partition: [row for row in rows if row["supervision"]["partition"] == partition] for partition in PARTITIONS}
    results: dict[str, Any] = {}
    for name, (model, neighborhood) in models.items():
        arrays = {partition: np.asarray([tabular_features(row["graph"], neighborhood) for row in subset], dtype=float) for partition, subset in partitions.items()}
        labels = {partition: [row["supervision"]["observed_target"] for row in subset] for partition, subset in partitions.items()}
        if neighborhood:
            counts = Counter(labels["train"])
            weight = np.asarray([len(labels["train"]) / (2 * counts[label]) for label in labels["train"]])
            model.fit(arrays["train"], labels["train"], sample_weight=weight)
        else:
            model.fit(arrays["train"], labels["train"])
        scores = {partition: model.predict_proba(array)[:, 1].tolist() for partition, array in arrays.items()}
        threshold = select_threshold(labels["validation"], scores["validation"])
        results[name] = {"threshold": threshold, "metrics": {partition: metrics(labels[partition], scores[partition], threshold, config["precision_at_k"]) for partition in PARTITIONS}}
        joblib.dump(model, output / f"{name}.joblib")
    return results


def evaluate_bundle(
    bundle_path: str | Path, graphs: Sequence[dict[str, Any]],
    supervision: Sequence[dict[str, Any]], splits: Sequence[dict[str, Any]],
    config: dict[str, Any] | None = None, partition: str = "test",
    out: str | Path | None = None, *, dry_run: bool = False,
    device: str | None = None,
) -> dict[str, Any]:
    """Evaluate a frozen bundle without fitting, threshold selection or labels in prediction."""
    from chainrisk.bundle import load_model_bundle, predict_bundle
    if partition not in {*PARTITIONS, "all"}:
        raise ValueError("evaluation partition must be train, validation, test or all")
    manifest = json.loads((Path(bundle_path) / "manifest.json").read_text(encoding="utf-8"))
    frozen = manifest.get("training_manifest", {}).get("config", {})
    options = copy.deepcopy(config or frozen or {"task_id": manifest["task_id"]})
    if device is not None:
        options["device"] = device
    effective = validate_config(options)
    if frozen and effective["experiment_mode"] != frozen["experiment_mode"]:
        raise ValueError("evaluation experiment mode differs from the frozen model")
    if effective["task_id"] != manifest["task_id"]:
        raise ValueError("evaluation task differs from the frozen model")
    joined, dataset_manifest = merge_dataset(graphs, supervision, splits, effective)
    if dataset_manifest["graph_recipe"] != manifest.get("graph_recipe"):
        raise ValueError("evaluation graph recipe differs from the frozen model")
    subset = [row for row in joined if partition == "all" or row["supervision"]["partition"] == partition]
    if dry_run:
        return {"status": "validated", "task_id": effective["task_id"],
            "partition": partition, "samples": len(subset), "dataset": dataset_manifest,
            "model_version": manifest.get("model_version"), "fitting_performed": False,
            "threshold_selection_performed": False, "prediction_performed": False}
    device = resolve_device(effective["device"])
    bundle = load_model_bundle(bundle_path, device=device, expected_task=effective["task_id"])
    predictions = predict_bundle(bundle, [row["graph"] for row in subset], device, effective["batch_size"])
    by_sample = {row["sample_id"]: row for row in predictions}
    labels, scores, records = [], [], []
    for row in subset:
        prediction = by_sample[row["graph"]["sample_id"]]
        if prediction["score"] is None:
            raise ValueError("quality-approved evaluation sample produced no score")
        observed = row["supervision"]["observed_target"]
        labels.append(observed)
        scores.append(prediction["score"])
        records.append(prediction | {"observed_target": observed,
            "label_status": row["supervision"]["label_status"],
            "partition": row["supervision"]["partition"]})
    summary = {"status": "evaluated_frozen_model", "task_id": effective["task_id"],
        "partition": partition, "model_version": bundle.manifest["model_version"],
        "dataset": dataset_manifest, "score_meaning": bundle.manifest["score_meaning"],
        "metrics": metrics(labels, scores, bundle.manifest["threshold"], effective["precision_at_k"]),
        "fitting_performed": False, "threshold_selection_performed": False,
        "predictions": records}
    if out is not None:
        destination = Path(out)
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / "evaluation.json"
        if path.exists():
            raise FileExistsError(f"refusing to overwrite evaluation: {path}")
        path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def resolve_device(name: str) -> str:
    """Resolve a requested accelerator only when a numerical operation runs."""
    if name not in {"cpu", "cuda", "mps", "auto"}:
        raise ValueError("device must be cpu, cuda, mps or auto")
    import torch
    if name == "auto":
        if torch.cuda.is_available():
            return "cuda"
        return "mps" if torch.backends.mps.is_available() else "cpu"
    if name == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but unavailable")
    if name == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS requested but unavailable")
    return name


def export_run(run_directory: str | Path, out: str | Path | None = None) -> dict[str, Any]:
    """Validate/copy the bundle already exported by train; never train again."""
    from chainrisk.bundle import load_model_bundle
    source = Path(run_directory)
    if (source / "bundle" / "manifest.json").exists():
        source = source / "bundle"
    bundle = load_model_bundle(source, device="cpu")
    destination = source
    if out is not None:
        destination = Path(out)
        if destination.exists():
            raise FileExistsError(f"refusing to overwrite export destination: {destination}")
        shutil.copytree(source, destination)
    return {"status": "exported", "bundle_path": str(destination.resolve()),
        "model_version": bundle.manifest["model_version"],
        "task_id": bundle.manifest["task_id"], "fitting_performed": False}


def train(
    graphs: Sequence[dict[str, Any]], supervision: Sequence[dict[str, Any]],
    splits: Sequence[dict[str, Any]], config: dict[str, Any], out: str | Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    config = validate_config(config)
    if not get_task(config["task_id"]).trainable:
        return {"status": "data_only", "task_id": config["task_id"], "training_supported": False, "config": config}
    rows, dataset_manifest = merge_dataset(graphs, supervision, splits, config)
    summary: dict[str, Any] = {"status": "validated" if dry_run else "trained", "config": config,
        "dataset": dataset_manifest, "graph_recipe": dataset_manifest["graph_recipe"]}
    if dry_run:
        return summary
    import torch
    from chainrisk.graph import batch_graph_samples, fit_scaler
    from chainrisk.models import create_model
    from chainrisk.bundle import export_model_bundle
    output = Path(out)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    seed = config["seed"]
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    device_name = resolve_device(config["device"])
    device = torch.device(device_name)
    partitions = {partition: [row for row in rows if row["supervision"]["partition"] == partition] for partition in PARTITIONS}
    scaler = fit_scaler([row["graph"] for row in partitions["train"]])
    example = rows[0]["graph"]
    model = create_model(config["model"], input_dim=len(example["feature_names"]), edge_dim=len(example["edge_feature_names"]), num_relations=2 * len(example["relation_names"])).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"])
    counts = Counter(row["supervision"]["observed_target"] for row in partitions["train"])
    pos_weight = counts[0] / counts[1]
    best_state, best_ap, best_epoch, stale = None, -math.inf, 0, 0
    history: list[dict[str, Any]] = []
    for epoch in range(1, config["epochs"] + 1):
        model.train()
        order = list(partitions["train"])
        random.shuffle(order)
        batches = [order[start:start + config["batch_size"]] for start in range(0, len(order), config["batch_size"])]
        total_loss = 0.0
        for batch_rows in batches:
            batch = batch_graph_samples([row["graph"] for row in batch_rows], scaler, device=device, add_reverse=True)
            targets = torch.tensor([row["supervision"]["observed_target"] for row in batch_rows], dtype=torch.float32, device=device)
            optimizer.zero_grad(set_to_none=True)
            loss = binary_loss(model(batch), targets, config["loss"], pos_weight)
            if not torch.isfinite(loss):
                raise ValueError("non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
            optimizer.step()
            total_loss += loss.item() * len(batch_rows)
        labels, scores = _score(model, partitions["validation"], scaler, device, config["batch_size"])
        report = metrics(labels, scores, k=config["precision_at_k"])
        history.append({"epoch": epoch, "train_loss": total_loss / sum(map(len, batches)), "validation_average_precision": report["average_precision"]})
        if report["average_precision"] > best_ap + config["min_delta"]:
            best_state, best_ap, best_epoch, stale = copy.deepcopy(model.state_dict()), report["average_precision"], epoch, 0
        else:
            stale += 1
        if stale >= config["patience"]:
            break
    if best_state is None:
        raise ValueError("no validation checkpoint selected")
    model.load_state_dict(best_state)
    labels, scores = _score(model, partitions["validation"], scaler, device, config["batch_size"])
    threshold = select_threshold(labels, scores)
    reports, predictions = {}, []
    for partition, subset in partitions.items():
        report, records = evaluate(model, subset, scaler, threshold, device, config["batch_size"], config["precision_at_k"])
        reports[partition] = report
        predictions.extend(records)
    summary.update(history=history, best_epoch=best_epoch, best_validation_average_precision=best_ap, threshold=threshold, pos_weight=pos_weight, metrics=reports, calibration_status="uncalibrated", test_use="scored only after checkpoint and threshold selection")
    if config["fit_tabular_baselines"]:
        summary["tabular_baselines"] = fit_tabular_baselines(rows, config, output)
    export_model_bundle(output / "bundle", model, config["model"], scaler, config["task_id"], threshold, summary, calibration_status="uncalibrated")
    (output / "training_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (output / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for record in predictions:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return summary
