#!/usr/bin/env python3
"""Train a small GraphSAGE pilot on cutoff-bounded ego graphs.

The script intentionally uses a compact native PyTorch implementation rather
than adding PyTorch Geometric as a dependency.  Each JSONL row is one target
token graph; the center node logit is the prediction.  The test holdout is
read and scored only after the best validation checkpoint is selected.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import torch
from torch import Tensor, nn


LABEL_TO_INT = {"low_volume_dead": 0, "continued_activity": 1}


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


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def graph_tensor(
    row: dict[str, Any],
    mean: Tensor,
    std: Tensor,
    device: torch.device | None = None,
) -> tuple[Tensor, Tensor, int]:
    target_device = device or mean.device
    x = torch.tensor(row["node_features"], dtype=torch.float32, device=target_device)
    x = (x - mean) / std
    edge = torch.tensor(row["edge_index"], dtype=torch.long, device=target_device)
    if edge.ndim != 2 or edge.shape[0] != 2:
        raise ValueError("edge_index must have shape [2, edge_count]")
    label = row.get("label")
    if label not in LABEL_TO_INT:
        raise ValueError(f"unknown label: {label}")
    return x, edge, LABEL_TO_INT[label]


def batch_graph_tensors(
    rows: list[dict[str, Any]],
    mean: Tensor,
    std: Tensor,
    device: torch.device | None = None,
) -> tuple[Tensor, Tensor, Tensor, list[int]]:
    """Combine disconnected ego graphs into one graph with batched centers."""
    if not rows:
        raise ValueError("cannot batch an empty graph list")
    target_device = device or mean.device
    feature_parts: list[Tensor] = []
    edge_parts: list[Tensor] = []
    center_indices: list[int] = []
    labels: list[int] = []
    node_offset = 0
    for row in rows:
        x, edge, label = graph_tensor(row, mean, std, target_device)
        feature_parts.append(x)
        edge_parts.append(edge + node_offset)
        center_indices.append(node_offset)
        labels.append(label)
        node_offset += x.shape[0]
    return (
        torch.cat(feature_parts, dim=0),
        torch.cat(edge_parts, dim=1),
        torch.tensor(center_indices, dtype=torch.long, device=target_device),
        labels,
    )


def feature_stats(rows: Iterable[dict[str, Any]]) -> tuple[Tensor, Tensor]:
    total: Tensor | None = None
    square_total: Tensor | None = None
    count = 0
    for row in rows:
        x = torch.tensor(row["node_features"], dtype=torch.float32)
        total = x.sum(dim=0) if total is None else total + x.sum(dim=0)
        square_total = x.square().sum(dim=0) if square_total is None else square_total + x.square().sum(dim=0)
        count += x.shape[0]
    if total is None or square_total is None or count == 0:
        raise ValueError("training split has no graph nodes")
    mean = total / count
    variance = (square_total / count - mean.square()).clamp_min(1.0e-6)
    return mean, variance.sqrt()


class MeanSAGE(nn.Module):
    """Two mean-aggregation GraphSAGE layers followed by center readout."""

    def __init__(self, input_dim: int, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.self1 = nn.Linear(input_dim, hidden_dim)
        self.neighbor1 = nn.Linear(input_dim, hidden_dim)
        self.self2 = nn.Linear(hidden_dim, hidden_dim)
        self.neighbor2 = nn.Linear(hidden_dim, hidden_dim)
        self.dropout = nn.Dropout(dropout)
        self.output = nn.Linear(hidden_dim, 1)

    @staticmethod
    def aggregate(x: Tensor, edge_index: Tensor) -> Tensor:
        source, destination = edge_index
        neighbor_sum = torch.zeros_like(x)
        neighbor_sum.index_add_(0, destination, x[source])
        degree = torch.zeros(x.shape[0], dtype=x.dtype, device=x.device)
        degree.index_add_(0, destination, torch.ones_like(destination, dtype=x.dtype))
        return neighbor_sum / degree.clamp_min(1.0).unsqueeze(1)

    def forward(
        self,
        x: Tensor,
        edge_index: Tensor,
        readout_indices: Tensor | None = None,
    ) -> Tensor:
        h = torch.relu(self.self1(x) + self.neighbor1(self.aggregate(x, edge_index)))
        h = self.dropout(h)
        h = torch.relu(self.self2(h) + self.neighbor2(self.aggregate(h, edge_index)))
        h = self.dropout(h)
        logits = self.output(h).squeeze(-1)
        if readout_indices is None:
            return logits[0]
        return logits[readout_indices]


def safe_auc(labels: list[int], scores: list[float]) -> float | None:
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    # Rank-sum AUC uses ascending score ranks.  Average tied ranks so the
    # metric is invariant to the input order when scores are tied.
    order = sorted(range(len(scores)), key=lambda index: scores[index])
    rank_sum = 0.0
    position = 0
    while position < len(order):
        end = position + 1
        while end < len(order) and scores[order[end]] == scores[order[position]]:
            end += 1
        average_rank = (position + 1 + end) / 2
        rank_sum += average_rank * sum(labels[order[index]] for index in range(position, end))
        position = end
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def average_precision(labels: list[int], scores: list[float]) -> float | None:
    positives = sum(labels)
    if positives == 0:
        return None
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    hits = 0
    total_precision = 0.0
    for rank, index in enumerate(order, start=1):
        if labels[index] == 1:
            hits += 1
            total_precision += hits / rank
    return total_precision / positives


def score_rows(
    model: nn.Module,
    rows: list[dict[str, Any]],
    mean: Tensor,
    std: Tensor,
    device: torch.device | None = None,
    batch_size: int = 1,
) -> tuple[list[int], list[float]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    model.eval()
    target_device = device or next(model.parameters()).device
    labels: list[int] = []
    scores: list[float] = []
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            x, edge, centers, batch_labels = batch_graph_tensors(
                rows[start:start + batch_size], mean, std, target_device
            )
            batch_scores = torch.sigmoid(model(x, edge, centers)).detach().cpu().tolist()
            labels.extend(batch_labels)
            scores.extend(float(score) for score in batch_scores)
    return labels, scores


def classification_metrics(
    labels: list[int],
    scores: list[float],
    threshold: float,
) -> dict[str, Any]:
    true_positive = sum(label == 1 and score >= threshold for label, score in zip(labels, scores))
    true_negative = sum(label == 0 and score < threshold for label, score in zip(labels, scores))
    false_positive = sum(label == 0 and score >= threshold for label, score in zip(labels, scores))
    false_negative = sum(label == 1 and score < threshold for label, score in zip(labels, scores))
    positive_count = true_positive + false_negative
    negative_count = true_negative + false_positive
    recall_active = true_positive / positive_count if positive_count else 0.0
    specificity = true_negative / negative_count if negative_count else 0.0
    precision_active = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    f1_active = (
        2 * precision_active * recall_active / (precision_active + recall_active)
        if precision_active + recall_active else 0.0
    )
    precision_dead = true_negative / (true_negative + false_negative) if true_negative + false_negative else 0.0
    recall_dead = true_negative / (true_negative + false_positive) if true_negative + false_positive else 0.0
    f1_dead = (
        2 * precision_dead * recall_dead / (precision_dead + recall_dead)
        if precision_dead + recall_dead else 0.0
    )
    return {
        "rows": len(labels),
        "label_counts": dict(Counter("continued_activity" if label else "low_volume_dead" for label in labels)),
        "accuracy": (true_positive + true_negative) / len(labels) if labels else None,
        "balanced_accuracy": (recall_active + specificity) / 2 if labels else None,
        "roc_auc": safe_auc(labels, scores),
        "average_precision": average_precision(labels, scores),
        "precision_continued_activity": precision_active,
        "recall_continued_activity": recall_active,
        "f1_continued_activity": f1_active,
        "precision_low_volume_dead": precision_dead,
        "recall_low_volume_dead": recall_dead,
        "f1_low_volume_dead": f1_dead,
        "macro_f1": (f1_active + f1_dead) / 2,
        "false_positive_rate": false_positive / negative_count if negative_count else None,
        "decision_threshold_continued_activity": threshold,
        "confusion_matrix": {
            "true_negative": true_negative,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_positive": true_positive,
        },
        "majority_accuracy": max(positive_count, negative_count) / len(labels) if labels else None,
    }


def evaluate(
    model: nn.Module,
    rows: list[dict[str, Any]],
    mean: Tensor,
    std: Tensor,
    split: str,
    threshold: float = 0.5,
    device: torch.device | None = None,
    batch_size: int = 1,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    labels, scores = score_rows(model, rows, mean, std, device, batch_size)
    predictions: list[dict[str, Any]] = []
    for row, label, score in zip(rows, labels, scores):
        predicted = int(score >= threshold)
        predictions.append({
            "token_address": row["token_address"],
            "source_dataset": row["source_dataset"],
            "graph_role": row.get("graph_role"),
            "partition": row.get("partition"),
            "label": row["label"],
            "label_int": label,
            "score_continued_activity": score,
            "score_low_volume_dead": 1.0 - score,
            "prediction_int": predicted,
            "predicted_label": "continued_activity" if predicted else "low_volume_dead",
            "split": split,
        })
    metrics = classification_metrics(labels, scores, threshold)
    metrics["split"] = split
    return metrics, predictions


def select_threshold(labels: list[int], scores: list[float]) -> float:
    """Select a threshold on validation data using balanced accuracy first."""
    if not labels:
        raise ValueError("cannot select a threshold without validation rows")
    candidates = sorted({0.0, 0.5, 1.0, *scores})
    best_threshold = 0.5
    best_key: tuple[float, float, float, float] | None = None
    for threshold in candidates:
        metrics = classification_metrics(labels, scores, threshold)
        key = (
            float(metrics["balanced_accuracy"] or 0.0),
            float(metrics["macro_f1"]),
            float(metrics["f1_low_volume_dead"]),
            -abs(threshold - 0.5),
        )
        if best_key is None or key > best_key:
            best_key = key
            best_threshold = threshold
    return best_threshold


def resolve_device(requested: str) -> torch.device:
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("--device cuda requested but CUDA is not available")
    return torch.device(requested)


def train(args: argparse.Namespace) -> dict[str, Any]:
    if args.batch_size <= 0:
        raise ValueError("batch_size must be positive")
    device = resolve_device(args.device)
    set_seed(args.seed)
    torch.set_num_threads(args.threads)
    source = Path(args.graphs).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(source)
    train_rows = [row for row in rows if row.get("graph_role") == "development" and row.get("partition") == "train"]
    validation_rows = [row for row in rows if row.get("graph_role") == "development" and row.get("partition") == "validation"]
    test_rows = [row for row in rows if row.get("graph_role") == "test_holdout"]
    if not train_rows or not validation_rows or not test_rows:
        raise ValueError("expected non-empty train, validation, and test splits")
    mean, std = feature_stats(train_rows)
    mean, std = mean.to(device), std.to(device)
    model = MeanSAGE(len(mean), args.hidden_dim, args.dropout).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    positive_count = sum(row["label"] == "continued_activity" for row in train_rows)
    negative_count = sum(row["label"] == "low_volume_dead" for row in train_rows)
    if positive_count == 0 or negative_count == 0:
        raise ValueError("training split must contain both labels for class weighting")
    positive_class_weight = negative_count / positive_count
    criterion = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([positive_class_weight], dtype=torch.float32, device=device)
    )

    best_state: dict[str, Tensor] | None = None
    best_epoch = 0
    best_auc = -math.inf
    stale_epochs = 0
    history: list[dict[str, Any]] = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        order = list(range(len(train_rows)))
        random.shuffle(order)
        total_loss = 0.0
        for start in range(0, len(order), args.batch_size):
            batch_rows = [train_rows[index] for index in order[start:start + args.batch_size]]
            x, edge, centers, labels = batch_graph_tensors(batch_rows, mean, std, device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(x, edge, centers)
            loss = criterion(
                logits,
                torch.tensor(labels, dtype=torch.float32, device=device),
            )
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * len(batch_rows)
        validation, _ = evaluate(
            model,
            validation_rows,
            mean,
            std,
            "validation",
            device=device,
            batch_size=args.batch_size,
        )
        row = {
            "epoch": epoch,
            "train_loss": total_loss / len(train_rows),
            "validation_roc_auc": validation["roc_auc"],
            "validation_average_precision": validation["average_precision"],
            "validation_balanced_accuracy": validation["balanced_accuracy"],
        }
        history.append(row)
        score = validation["roc_auc"] if validation["roc_auc"] is not None else -math.inf
        if score > best_auc + args.min_delta:
            best_auc = score
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
        if stale_epochs >= args.patience:
            break
    if best_state is None:
        raise RuntimeError("no validation checkpoint was selected")
    model.load_state_dict(best_state)
    validation_labels, validation_scores = score_rows(
        model, validation_rows, mean, std, device, args.batch_size
    )
    decision_threshold = select_threshold(validation_labels, validation_scores)
    train_metrics, train_predictions = evaluate(
        model, train_rows, mean, std, "train", decision_threshold, device, args.batch_size
    )
    validation_metrics, validation_predictions = evaluate(
        model, validation_rows, mean, std, "validation", decision_threshold, device, args.batch_size
    )
    test_metrics, test_predictions = evaluate(
        model, test_rows, mean, std, "test_holdout", decision_threshold, device, args.batch_size
    )

    model_state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
    torch.save(
        {
            "model_state_dict": model_state,
            "input_dim": len(mean),
            "hidden_dim": args.hidden_dim,
            "dropout": args.dropout,
            "feature_mean": mean.detach().cpu(),
            "feature_std": std.detach().cpu(),
            "best_epoch": best_epoch,
            "seed": args.seed,
            "positive_class_weight": positive_class_weight,
            "decision_threshold_continued_activity": decision_threshold,
            "batch_size": args.batch_size,
        },
        output / "model.pt",
    )
    predictions = train_predictions + validation_predictions + test_predictions
    with (output / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")
    metrics = {
        "manifest_version": "graphsage-general-stratified-0.3",
        "graphs": str(source),
        "output": str(output),
        "seed": args.seed,
        "device": str(device),
        "cuda_device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "architecture": {
            "model": "two-layer mean GraphSAGE",
            "input_dim": len(mean),
            "hidden_dim": args.hidden_dim,
            "dropout": args.dropout,
            "readout": "center node",
            "optimizer": "Adam",
            "learning_rate": args.learning_rate,
            "weight_decay": args.weight_decay,
        },
        "training": {
            "max_epochs": args.epochs,
            "epochs_run": len(history),
            "patience": args.patience,
            "best_epoch": best_epoch,
            "best_validation_roc_auc": best_auc,
            "feature_normalization": "mean/std fit on train graph nodes only",
            "loss": "BCEWithLogitsLoss with train-only positive class weight",
            "positive_label": "continued_activity",
            "positive_class_weight": positive_class_weight,
            "train_label_counts": {
                "continued_activity": positive_count,
                "low_volume_dead": negative_count,
            },
            "decision_threshold_selection": "validation balanced accuracy, then macro-F1",
            "decision_threshold_continued_activity": decision_threshold,
            "device": str(device),
            "batch_size": args.batch_size,
        },
        "split_counts": {"train": len(train_rows), "validation": len(validation_rows), "test_holdout": len(test_rows)},
        "metrics": {"train": train_metrics, "validation": validation_metrics, "test_holdout": test_metrics},
        "history": history,
        "test_use": "scored once after validation checkpoint selection; not used for early stopping or tuning",
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "feature_normalization.json").write_text(
        json.dumps(
            {"mean": mean.detach().cpu().tolist(), "std": std.detach().cpu().tolist()},
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return metrics


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--graphs", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--seed", type=int, default=20261001)
    result.add_argument("--hidden-dim", type=int, default=32)
    result.add_argument("--dropout", type=float, default=0.20)
    result.add_argument("--learning-rate", type=float, default=0.003)
    result.add_argument("--weight-decay", type=float, default=0.0001)
    result.add_argument("--epochs", type=int, default=250)
    result.add_argument("--patience", type=int, default=35)
    result.add_argument("--min-delta", type=float, default=0.0001)
    result.add_argument("--threads", type=int, default=4)
    result.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    result.add_argument("--batch-size", type=int, default=512)
    return result


if __name__ == "__main__":
    print(json.dumps(train(parser().parse_args()), indent=2, sort_keys=True))
