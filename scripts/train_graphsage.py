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
from torch.nn import functional as F


LABEL_TO_INT = {"low_volume_dead": 0, "continued_activity": 1}
TOPOLOGY_ARCHITECTURE = "topology_sage"
EDGE_ARCHITECTURES = frozenset({"edge_sage", "edge_gcn", "edge_gat"})
ARCHITECTURES = (TOPOLOGY_ARCHITECTURE, "edge_sage", "edge_gcn", "edge_gat")
ARCHITECTURE_LABELS = {
    TOPOLOGY_ARCHITECTURE: "topology-only mean GraphSAGE",
    "edge_sage": "edge-aware GraphSAGE",
    "edge_gcn": "edge-aware GCN",
    "edge_gat": "edge-aware GAT",
}
GraphTensor = tuple[Tensor, Tensor, int] | tuple[Tensor, Tensor, Tensor, int]


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


def apply_partition_override(rows: list[dict[str, Any]], path: Path) -> None:
    """Apply a frozen token partition without copying or rebuilding graph tensors."""
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise SystemExit("pyarrow is required for --partition-override") from exc

    table = parquet.read_table(path, columns=["token_address", "source_dataset", "partition"])
    override: dict[tuple[str, str], str] = {}
    for record in table.to_pylist():
        key = (str(record["token_address"]).lower(), str(record["source_dataset"]))
        partition = str(record["partition"])
        if partition not in {"train", "validation", "test"}:
            raise ValueError(f"partition override contains invalid partition: {partition!r}")
        if key in override:
            raise ValueError(f"partition override contains duplicate target: {key}")
        override[key] = partition

    row_keys = [(str(row["token_address"]).lower(), str(row["source_dataset"])) for row in rows]
    if len(row_keys) != len(set(row_keys)):
        raise ValueError("graph manifest contains duplicate token/source keys")
    missing = sorted(set(row_keys) - set(override))
    extra = sorted(set(override) - set(row_keys))
    if missing or extra:
        raise ValueError(
            "partition override does not match graph manifest: "
            f"missing={len(missing)}, extra={len(extra)}"
        )
    for row in rows:
        key = (str(row["token_address"]).lower(), str(row["source_dataset"]))
        partition = override[key]
        row["partition"] = partition
        row["graph_role"] = "test_holdout" if partition == "test" else "development"


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
    edge_mean: Tensor | None = None,
    edge_std: Tensor | None = None,
) -> tuple[Tensor, Tensor, int] | tuple[Tensor, Tensor, Tensor, int]:
    target_device = device or mean.device
    x = torch.tensor(row["node_features"], dtype=torch.float32, device=target_device)
    x = (x - mean) / std
    edge = torch.tensor(row["edge_index"], dtype=torch.long, device=target_device)
    if edge.ndim != 2 or edge.shape[0] != 2:
        raise ValueError("edge_index must have shape [2, edge_count]")
    label = row.get("label")
    if label not in LABEL_TO_INT:
        raise ValueError(f"unknown label: {label}")
    if edge_mean is None and edge_std is None:
        return x, edge, LABEL_TO_INT[label]
    if edge_mean is None or edge_std is None:
        raise ValueError("edge_mean and edge_std must be provided together")
    if edge_mean.ndim != 1 or edge_std.ndim != 1 or edge_mean.shape != edge_std.shape:
        raise ValueError("edge normalization statistics must be one-dimensional and aligned")
    if torch.any(~torch.isfinite(edge_mean)) or torch.any(~torch.isfinite(edge_std)):
        raise ValueError("edge normalization statistics must be finite")
    if torch.any(edge_std <= 0):
        raise ValueError("edge normalization standard deviations must be positive")
    edge_values = _edge_feature_tensor(
        row,
        edge_count=edge.shape[1],
        expected_dim=edge_mean.shape[0],
        device=target_device,
    )
    edge_values = (edge_values - edge_mean.to(target_device)) / edge_std.to(target_device)
    return x, edge, edge_values, LABEL_TO_INT[label]


def _edge_feature_tensor(
    row: dict[str, Any],
    edge_count: int,
    expected_dim: int | None = None,
    device: torch.device | None = None,
) -> Tensor:
    """Read one graph's edge matrix and enforce the edge-input contract."""
    raw_values = row.get("edge_features")
    if raw_values is None:
        raise ValueError("edge_features are required for edge-aware architectures")
    values = torch.tensor(raw_values, dtype=torch.float32, device=device)
    if values.ndim != 2 or values.shape[0] != edge_count:
        raise ValueError("edge_features must have shape [edge_count, edge_dim]")
    if expected_dim is not None and values.shape[1] != expected_dim:
        raise ValueError(
            f"edge feature width mismatch: expected {expected_dim}, got {values.shape[1]}"
        )
    if not torch.isfinite(values).all():
        raise ValueError("edge_features must contain only finite values")
    names = row.get("edge_feature_names")
    if names is not None and (not isinstance(names, list) or len(names) != values.shape[1]):
        raise ValueError("edge_feature_names must match edge feature width")
    return values
    return x, edge, LABEL_TO_INT[label]


def _combine_graph_tensors(
    graphs: list[GraphTensor],
    device: torch.device,
) -> (
    tuple[Tensor, Tensor, Tensor, list[int]]
    | tuple[Tensor, Tensor, Tensor, Tensor, list[int]]
):
    if not graphs:
        raise ValueError("cannot batch an empty graph list")
    feature_parts: list[Tensor] = []
    edge_parts: list[Tensor] = []
    edge_feature_parts: list[Tensor] = []
    center_indices: list[int] = []
    labels: list[int] = []
    node_offset = 0
    graph_widths = {len(graph) for graph in graphs}
    if graph_widths not in ({3}, {4}):
        raise ValueError("graph tensors must consistently include edge features")
    with_edge_features = 4 in graph_widths
    for graph in graphs:
        if with_edge_features:
            x, edge, edge_values, label = graph
            edge_feature_parts.append(edge_values)
        else:
            x, edge, label = graph
        feature_parts.append(x)
        edge_parts.append(edge + node_offset)
        center_indices.append(node_offset)
        labels.append(label)
        node_offset += x.shape[0]
    base = (
        torch.cat(feature_parts, dim=0),
        torch.cat(edge_parts, dim=1),
    )
    centers = torch.tensor(center_indices, dtype=torch.long, device=device)
    if with_edge_features:
        return base[0], base[1], torch.cat(edge_feature_parts, dim=0), centers, labels
    return base[0], base[1], centers, labels


def cache_graph_tensors(
    rows: list[dict[str, Any]],
    mean: Tensor,
    std: Tensor,
    device: torch.device | None = None,
    edge_mean: Tensor | None = None,
    edge_std: Tensor | None = None,
) -> list[GraphTensor]:
    """Materialize normalized graph tensors once on the target device."""
    if not rows:
        raise ValueError("cannot cache an empty graph list")
    target_device = device or mean.device
    return [graph_tensor(row, mean, std, target_device, edge_mean, edge_std) for row in rows]


def batch_cached_graph_tensors(
    graph_cache: list[GraphTensor],
    indices: list[int],
    device: torch.device | None = None,
) -> (
    tuple[Tensor, Tensor, Tensor, list[int]]
    | tuple[Tensor, Tensor, Tensor, Tensor, list[int]]
):
    """Combine cached graph tensors without rebuilding host-side graph data."""
    if not indices:
        raise ValueError("cannot batch an empty graph index list")
    if any(index < 0 or index >= len(graph_cache) for index in indices):
        raise IndexError("graph cache index is outside the cached rows")
    target_device = device or graph_cache[0][0].device
    return _combine_graph_tensors([graph_cache[index] for index in indices], target_device)


def batch_graph_tensors(
    rows: list[dict[str, Any]],
    mean: Tensor,
    std: Tensor,
    device: torch.device | None = None,
    edge_mean: Tensor | None = None,
    edge_std: Tensor | None = None,
) -> (
    tuple[Tensor, Tensor, Tensor, list[int]]
    | tuple[Tensor, Tensor, Tensor, Tensor, list[int]]
):
    """Combine disconnected ego graphs into one graph with batched centers."""
    if not rows:
        raise ValueError("cannot batch an empty graph list")
    target_device = device or mean.device
    graphs = [graph_tensor(row, mean, std, target_device, edge_mean, edge_std) for row in rows]
    return _combine_graph_tensors(graphs, target_device)


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


def _edge_count(row: dict[str, Any]) -> int:
    edge_index = row.get("edge_index")
    if not isinstance(edge_index, list) or len(edge_index) != 2:
        raise ValueError("edge_index must have shape [2, edge_count]")
    if len(edge_index[0]) != len(edge_index[1]):
        raise ValueError("edge_index must have two equal-length rows")
    return len(edge_index[0])


def edge_feature_schema(rows: Iterable[dict[str, Any]]) -> list[str]:
    names: list[str] | None = None
    materialized = list(rows)
    if not materialized:
        raise ValueError("cannot infer edge feature schema from empty rows")
    expected_dim: int | None = None
    for row in materialized:
        values = _edge_feature_tensor(row, _edge_count(row), expected_dim)
        expected_dim = values.shape[1]
        row_names = row.get("edge_feature_names")
        if not isinstance(row_names, list) or len(row_names) != expected_dim:
            raise ValueError("edge_feature_names must match edge feature width")
        normalized_names = [str(name) for name in row_names]
        if names is None:
            names = normalized_names
        elif names != normalized_names:
            raise ValueError("edge_feature_names must be consistent across graphs")
    if names is None:
        raise ValueError("edge feature schema is missing")
    return names


def edge_feature_stats(rows: Iterable[dict[str, Any]]) -> tuple[Tensor, Tensor]:
    materialized = list(rows)
    names = edge_feature_schema(materialized)
    total: Tensor | None = None
    square_total: Tensor | None = None
    count = 0
    for row in materialized:
        values = _edge_feature_tensor(row, _edge_count(row), len(names))
        total = values.sum(dim=0) if total is None else total + values.sum(dim=0)
        square_total = values.square().sum(dim=0) if square_total is None else square_total + values.square().sum(dim=0)
        count += values.shape[0]
    if total is None or square_total is None or count == 0:
        raise ValueError("training split has no edge features")
    mean = total / count
    variance = (square_total / count - mean.square()).clamp_min(1.0e-6)
    return mean, variance.sqrt()


class MeanSAGE(nn.Module):
    """Mean-aggregation GraphSAGE layers followed by center readout."""

    def __init__(self, input_dim: int, hidden_dim: int, dropout: float, layers: int = 2) -> None:
        super().__init__()
        if input_dim <= 0 or hidden_dim <= 0 or layers <= 0:
            raise ValueError("input_dim, hidden_dim, and layers must be positive")
        self.layers = layers
        self.self_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        self.neighbor_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        for _ in range(1, layers):
            self.self_layers.append(nn.Linear(hidden_dim, hidden_dim))
            self.neighbor_layers.append(nn.Linear(hidden_dim, hidden_dim))
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
        h = x
        for self_layer, neighbor_layer in zip(self.self_layers, self.neighbor_layers):
            h = torch.relu(self_layer(h) + neighbor_layer(self.aggregate(h, edge_index)))
            h = self.dropout(h)
        logits = self.output(h).squeeze(-1)
        if readout_indices is None:
            return logits[0]
        return logits[readout_indices]


def _validate_edge_inputs(
    x: Tensor,
    edge_index: Tensor,
    edge_features: Tensor,
    edge_dim: int,
) -> None:
    if x.ndim != 2:
        raise ValueError("node features must have shape [node_count, input_dim]")
    if edge_index.ndim != 2 or edge_index.shape[0] != 2:
        raise ValueError("edge_index must have shape [2, edge_count]")
    if edge_features.ndim != 2 or edge_features.shape[0] != edge_index.shape[1]:
        raise ValueError("edge_features must have shape [edge_count, edge_dim]")
    if edge_features.shape[1] != edge_dim:
        raise ValueError(f"edge feature width mismatch: expected {edge_dim}, got {edge_features.shape[1]}")
    if not torch.isfinite(edge_features).all():
        raise ValueError("edge_features must contain only finite values")
    if edge_index.numel() and (edge_index.min() < 0 or edge_index.max() >= x.shape[0]):
        raise ValueError("edge_index points outside node feature matrix")


def _readout_center(logits: Tensor, readout_indices: Tensor | None) -> Tensor:
    if readout_indices is None:
        return logits[0]
    return logits[readout_indices]


class EdgeSAGE(nn.Module):
    """Mean-aggregation GraphSAGE with an additive edge-conditioned message."""

    def __init__(
        self,
        input_dim: int,
        edge_dim: int,
        hidden_dim: int,
        dropout: float,
        layers: int = 2,
    ) -> None:
        super().__init__()
        if input_dim <= 0 or edge_dim <= 0 or hidden_dim <= 0 or layers <= 0:
            raise ValueError("input_dim, edge_dim, hidden_dim, and layers must be positive")
        self.edge_dim = edge_dim
        self.layers = layers
        self.self_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        self.source_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        self.edge_layers = nn.ModuleList([nn.Linear(edge_dim, hidden_dim)])
        for _ in range(1, layers):
            self.self_layers.append(nn.Linear(hidden_dim, hidden_dim))
            self.source_layers.append(nn.Linear(hidden_dim, hidden_dim))
            self.edge_layers.append(nn.Linear(edge_dim, hidden_dim))
        self.dropout = nn.Dropout(dropout)
        self.output = nn.Linear(hidden_dim, 1)

    def forward(
        self,
        x: Tensor,
        edge_index: Tensor,
        edge_features: Tensor,
        readout_indices: Tensor | None = None,
    ) -> Tensor:
        _validate_edge_inputs(x, edge_index, edge_features, self.edge_dim)
        source, destination = edge_index
        h = x
        for self_layer, source_layer, edge_layer in zip(
            self.self_layers, self.source_layers, self.edge_layers
        ):
            source_states = source_layer(h)
            messages = source_states[source] + edge_layer(edge_features)
            neighbor_sum = torch.zeros_like(source_states)
            neighbor_sum.index_add_(0, destination, messages)
            degree = torch.zeros(x.shape[0], dtype=x.dtype, device=x.device)
            degree.index_add_(0, destination, torch.ones_like(destination, dtype=x.dtype))
            neighbor_mean = neighbor_sum / degree.clamp_min(1.0).unsqueeze(1)
            h = torch.relu(self_layer(h) + neighbor_mean)
            h = self.dropout(h)
        return _readout_center(self.output(h).squeeze(-1), readout_indices)


class EdgeGCN(nn.Module):
    """Degree-normalized graph convolution with edge-conditioned messages."""

    def __init__(
        self,
        input_dim: int,
        edge_dim: int,
        hidden_dim: int,
        dropout: float,
        layers: int = 2,
    ) -> None:
        super().__init__()
        if input_dim <= 0 or edge_dim <= 0 or hidden_dim <= 0 or layers <= 0:
            raise ValueError("input_dim, edge_dim, hidden_dim, and layers must be positive")
        self.edge_dim = edge_dim
        self.layers = layers
        self.self_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        self.source_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        self.edge_layers = nn.ModuleList([nn.Linear(edge_dim, hidden_dim)])
        for _ in range(1, layers):
            self.self_layers.append(nn.Linear(hidden_dim, hidden_dim))
            self.source_layers.append(nn.Linear(hidden_dim, hidden_dim))
            self.edge_layers.append(nn.Linear(edge_dim, hidden_dim))
        self.dropout = nn.Dropout(dropout)
        self.output = nn.Linear(hidden_dim, 1)

    @staticmethod
    def incoming_normalization(edge_index: Tensor, node_count: int) -> Tensor:
        source, destination = edge_index
        degree = torch.zeros(node_count, dtype=torch.float32, device=edge_index.device)
        degree.index_add_(0, destination, torch.ones_like(destination, dtype=degree.dtype))
        return torch.rsqrt(degree[source].clamp_min(1.0) * degree[destination].clamp_min(1.0))

    def forward(
        self,
        x: Tensor,
        edge_index: Tensor,
        edge_features: Tensor,
        readout_indices: Tensor | None = None,
    ) -> Tensor:
        _validate_edge_inputs(x, edge_index, edge_features, self.edge_dim)
        source, destination = edge_index
        normalization = self.incoming_normalization(edge_index, x.shape[0]).to(x.dtype)
        h = x
        for self_layer, source_layer, edge_layer in zip(
            self.self_layers, self.source_layers, self.edge_layers
        ):
            source_states = source_layer(h)
            messages = (source_states[source] + edge_layer(edge_features)) * normalization.unsqueeze(1)
            neighbor_sum = torch.zeros_like(source_states)
            neighbor_sum.index_add_(0, destination, messages)
            h = torch.relu(self_layer(h) + neighbor_sum)
            h = self.dropout(h)
        return _readout_center(self.output(h).squeeze(-1), readout_indices)


def _incoming_softmax(logits: Tensor, destination: Tensor, node_count: int) -> Tensor:
    if logits.numel() == 0:
        return logits
    maximum = torch.full(
        (node_count,),
        -torch.inf,
        dtype=logits.dtype,
        device=logits.device,
    )
    maximum.scatter_reduce_(0, destination, logits, reduce="amax", include_self=True)
    exponentials = torch.exp(logits - maximum[destination])
    denominator = torch.zeros_like(maximum)
    denominator.index_add_(0, destination, exponentials)
    return exponentials / denominator[destination].clamp_min(torch.finfo(logits.dtype).tiny)


class EdgeGAT(nn.Module):
    """Graph attention with source, destination, and edge-conditioned scores."""

    def __init__(
        self,
        input_dim: int,
        edge_dim: int,
        hidden_dim: int,
        dropout: float,
        layers: int = 2,
    ) -> None:
        super().__init__()
        if input_dim <= 0 or edge_dim <= 0 or hidden_dim <= 0 or layers <= 0:
            raise ValueError("input_dim, edge_dim, hidden_dim, and layers must be positive")
        self.edge_dim = edge_dim
        self.layers = layers
        self.negative_slope = 0.2
        self.self_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        self.source_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        self.destination_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        self.edge_layers = nn.ModuleList([nn.Linear(edge_dim, hidden_dim)])
        self.attention_source_layers = nn.ModuleList([nn.Linear(hidden_dim, 1, bias=False)])
        self.attention_destination_layers = nn.ModuleList([nn.Linear(hidden_dim, 1, bias=False)])
        self.attention_edge_layers = nn.ModuleList([nn.Linear(hidden_dim, 1, bias=False)])
        for _ in range(1, layers):
            self.self_layers.append(nn.Linear(hidden_dim, hidden_dim))
            self.source_layers.append(nn.Linear(hidden_dim, hidden_dim))
            self.destination_layers.append(nn.Linear(hidden_dim, hidden_dim))
            self.edge_layers.append(nn.Linear(edge_dim, hidden_dim))
            self.attention_source_layers.append(nn.Linear(hidden_dim, 1, bias=False))
            self.attention_destination_layers.append(nn.Linear(hidden_dim, 1, bias=False))
            self.attention_edge_layers.append(nn.Linear(hidden_dim, 1, bias=False))
        self.dropout = nn.Dropout(dropout)
        self.output = nn.Linear(hidden_dim, 1)

    def _attention_components(
        self,
        h: Tensor,
        edge_index: Tensor,
        edge_features: Tensor,
        layer_index: int,
    ) -> tuple[Tensor, Tensor, Tensor, Tensor]:
        source, destination = edge_index
        source_states = self.source_layers[layer_index](h)
        destination_states = self.destination_layers[layer_index](h)
        edge_states = self.edge_layers[layer_index](edge_features)
        logits = (
            self.attention_source_layers[layer_index](source_states[source]).squeeze(-1)
            + self.attention_destination_layers[layer_index](destination_states[destination]).squeeze(-1)
            + self.attention_edge_layers[layer_index](edge_states).squeeze(-1)
        )
        weights = _incoming_softmax(
            F.leaky_relu(logits, negative_slope=self.negative_slope),
            destination,
            h.shape[0],
        )
        return source_states, destination_states, edge_states, weights

    def attention_weights(
        self,
        x: Tensor,
        edge_index: Tensor,
        edge_features: Tensor,
        layer_index: int = 0,
    ) -> Tensor:
        _validate_edge_inputs(x, edge_index, edge_features, self.edge_dim)
        if not 0 <= layer_index < self.layers:
            raise ValueError("layer_index is outside the configured model depth")
        return self._attention_components(x, edge_index, edge_features, layer_index)[3]

    def forward(
        self,
        x: Tensor,
        edge_index: Tensor,
        edge_features: Tensor,
        readout_indices: Tensor | None = None,
    ) -> Tensor:
        _validate_edge_inputs(x, edge_index, edge_features, self.edge_dim)
        _, destination = edge_index
        h = x
        for layer_index, self_layer in enumerate(self.self_layers):
            source_states, _, edge_states, weights = self._attention_components(
                h, edge_index, edge_features, layer_index
            )
            messages = (source_states[edge_index[0]] + edge_states) * weights.unsqueeze(1)
            neighbor_sum = torch.zeros_like(source_states)
            neighbor_sum.index_add_(0, destination, messages)
            h = torch.relu(self_layer(h) + neighbor_sum)
            h = self.dropout(h)
        return _readout_center(self.output(h).squeeze(-1), readout_indices)


def build_model(
    architecture: str,
    input_dim: int,
    edge_dim: int | None,
    hidden_dim: int,
    dropout: float,
    layers: int,
) -> nn.Module:
    if architecture == TOPOLOGY_ARCHITECTURE:
        return MeanSAGE(input_dim, hidden_dim, dropout, layers)
    if architecture not in EDGE_ARCHITECTURES:
        raise ValueError(f"unknown architecture: {architecture}")
    if edge_dim is None or edge_dim <= 0:
        raise ValueError("edge-aware architectures require a positive edge feature dimension")
    model_class: type[nn.Module] = {
        "edge_sage": EdgeSAGE,
        "edge_gcn": EdgeGCN,
        "edge_gat": EdgeGAT,
    }[architecture]
    return model_class(input_dim, edge_dim, hidden_dim, dropout, layers)


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
    edge_mean: Tensor | None = None,
    edge_std: Tensor | None = None,
    graph_cache: list[GraphTensor] | None = None,
) -> tuple[list[int], list[float]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    model.eval()
    target_device = device or next(model.parameters()).device
    if graph_cache is not None and len(graph_cache) != len(rows):
        raise ValueError("graph cache must align with the scored rows")
    labels: list[int] = []
    scores: list[float] = []
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            if graph_cache is None:
                batch = batch_graph_tensors(
                    rows[start:start + batch_size],
                    mean,
                    std,
                    target_device,
                    edge_mean=edge_mean,
                    edge_std=edge_std,
                )
            else:
                batch = batch_cached_graph_tensors(
                    graph_cache,
                    list(range(start, min(start + batch_size, len(rows)))),
                    target_device,
                )
            if edge_mean is None and edge_std is None:
                x, edge, centers, batch_labels = batch
                logits = model(x, edge, centers)
            else:
                x, edge, edge_features, centers, batch_labels = batch
                logits = model(x, edge, edge_features, centers)
            batch_scores = torch.sigmoid(logits).detach().cpu().tolist()
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
    edge_mean: Tensor | None = None,
    edge_std: Tensor | None = None,
    graph_cache: list[GraphTensor] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    labels, scores = score_rows(
        model,
        rows,
        mean,
        std,
        device,
        batch_size,
        edge_mean,
        edge_std,
        graph_cache,
    )
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
    architecture = getattr(args, "architecture", TOPOLOGY_ARCHITECTURE)
    if architecture not in ARCHITECTURES:
        raise ValueError(f"unknown architecture: {architecture}")
    device = resolve_device(args.device)
    set_seed(args.seed)
    torch.set_num_threads(args.threads)
    source = Path(args.graphs).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(source)
    partition_override = getattr(args, "partition_override", None)
    if partition_override:
        apply_partition_override(rows, Path(partition_override).resolve())
    train_rows = [row for row in rows if row.get("graph_role") == "development" and row.get("partition") == "train"]
    validation_rows = [row for row in rows if row.get("graph_role") == "development" and row.get("partition") == "validation"]
    test_rows = [row for row in rows if row.get("graph_role") == "test_holdout"]
    if not train_rows or not validation_rows or not test_rows:
        raise ValueError("expected non-empty train, validation, and test splits")
    mean, std = feature_stats(train_rows)
    mean, std = mean.to(device), std.to(device)
    edge_feature_names: list[str] | None = None
    edge_mean: Tensor | None = None
    edge_std: Tensor | None = None
    edge_dim: int | None = None
    if architecture in EDGE_ARCHITECTURES:
        edge_feature_names = edge_feature_schema(rows)
        edge_mean, edge_std = edge_feature_stats(train_rows)
        edge_mean, edge_std = edge_mean.to(device), edge_std.to(device)
        edge_dim = len(edge_feature_names)
    graph_cache_enabled = bool(getattr(args, "cache_graphs", False))
    train_graph_cache = (
        cache_graph_tensors(train_rows, mean, std, device, edge_mean, edge_std)
        if graph_cache_enabled
        else None
    )
    validation_graph_cache = (
        cache_graph_tensors(validation_rows, mean, std, device, edge_mean, edge_std)
        if graph_cache_enabled
        else None
    )
    test_graph_cache = (
        cache_graph_tensors(test_rows, mean, std, device, edge_mean, edge_std)
        if graph_cache_enabled
        else None
    )
    model = build_model(
        architecture,
        input_dim=len(mean),
        edge_dim=edge_dim,
        hidden_dim=args.hidden_dim,
        dropout=args.dropout,
        layers=args.layers,
    ).to(device)
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
            batch_indices = order[start:start + args.batch_size]
            batch_rows = [train_rows[index] for index in batch_indices]
            if train_graph_cache is None:
                batch = batch_graph_tensors(
                    batch_rows,
                    mean,
                    std,
                    device,
                    edge_mean=edge_mean,
                    edge_std=edge_std,
                )
            else:
                batch = batch_cached_graph_tensors(train_graph_cache, batch_indices, device)
            if edge_mean is None and edge_std is None:
                x, edge, centers, labels = batch
                logits = model(x, edge, centers)
            else:
                x, edge, edge_features, centers, labels = batch
                logits = model(x, edge, edge_features, centers)
            optimizer.zero_grad(set_to_none=True)
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
            edge_mean=edge_mean,
            edge_std=edge_std,
            graph_cache=validation_graph_cache,
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
        model,
        validation_rows,
        mean,
        std,
        device,
        args.batch_size,
        edge_mean,
        edge_std,
        validation_graph_cache,
    )
    decision_threshold = select_threshold(validation_labels, validation_scores)
    train_metrics, train_predictions = evaluate(
        model,
        train_rows,
        mean,
        std,
        "train",
        decision_threshold,
        device,
        args.batch_size,
        edge_mean,
        edge_std,
        train_graph_cache,
    )
    validation_metrics, validation_predictions = evaluate(
        model,
        validation_rows,
        mean,
        std,
        "validation",
        decision_threshold,
        device,
        args.batch_size,
        edge_mean,
        edge_std,
        validation_graph_cache,
    )
    test_metrics, test_predictions = evaluate(
        model,
        test_rows,
        mean,
        std,
        "test_holdout",
        decision_threshold,
        device,
        args.batch_size,
        edge_mean,
        edge_std,
        test_graph_cache,
    )

    model_state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
    torch.save(
        {
            "model_state_dict": model_state,
            "architecture": architecture,
            "input_dim": len(mean),
            "edge_dim": edge_dim,
            "edge_feature_names": edge_feature_names,
            "hidden_dim": args.hidden_dim,
            "dropout": args.dropout,
            "layers": args.layers,
            "feature_mean": mean.detach().cpu(),
            "feature_std": std.detach().cpu(),
            "edge_feature_mean": edge_mean.detach().cpu() if edge_mean is not None else None,
            "edge_feature_std": edge_std.detach().cpu() if edge_std is not None else None,
            "best_epoch": best_epoch,
            "seed": args.seed,
            "positive_class_weight": positive_class_weight,
            "decision_threshold_continued_activity": decision_threshold,
            "batch_size": args.batch_size,
            "graph_tensor_cache": graph_cache_enabled,
        },
        output / "model.pt",
    )
    predictions = train_predictions + validation_predictions + test_predictions
    with (output / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")
    edge_normalization = (
        {
            "fit_split": "train",
            "feature_names": edge_feature_names,
            "mean": edge_mean.detach().cpu().tolist(),
            "std": edge_std.detach().cpu().tolist(),
        }
        if edge_mean is not None and edge_std is not None
        else None
    )
    metrics = {
        "manifest_version": "graphsage-0.6",
        "split_name": args.split_name,
        "graphs": str(source),
        "partition_override": str(Path(partition_override).resolve()) if partition_override else None,
        "output": str(output),
        "seed": args.seed,
        "device": str(device),
        "cuda_device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "architecture": {
            "name": architecture,
            "model": ARCHITECTURE_LABELS[architecture],
            "input_dim": len(mean),
            "edge_feature_dim": edge_dim,
            "edge_feature_names": edge_feature_names,
            "hidden_dim": args.hidden_dim,
            "dropout": args.dropout,
            "layers": args.layers,
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
            "feature_normalization": (
                "mean/std fit on train graph nodes only"
                if edge_normalization is None
                else "node and edge mean/std fit on train graph nodes/edges only"
            ),
            "edge_feature_normalization": edge_normalization,
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
            "graph_tensor_cache": graph_cache_enabled,
        },
        "split_counts": {"train": len(train_rows), "validation": len(validation_rows), "test_holdout": len(test_rows)},
        "metrics": {"train": train_metrics, "validation": validation_metrics, "test_holdout": test_metrics},
        "feature_normalization": {
            "node": {
                "fit_split": "train",
                "mean": mean.detach().cpu().tolist(),
                "std": std.detach().cpu().tolist(),
            },
            "edge": edge_normalization,
        },
        "history": history,
        "test_use": "scored once after validation checkpoint selection; not used for early stopping or tuning",
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "feature_normalization.json").write_text(
        json.dumps(
            {
                "mean": mean.detach().cpu().tolist(),
                "std": std.detach().cpu().tolist(),
                "node": {
                    "fit_split": "train",
                    "mean": mean.detach().cpu().tolist(),
                    "std": std.detach().cpu().tolist(),
                },
                "edge": edge_normalization,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return metrics


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--graphs", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--partition-override")
    result.add_argument("--split-name", default="general_stratified_primary")
    result.add_argument("--architecture", choices=ARCHITECTURES, default=TOPOLOGY_ARCHITECTURE)
    result.add_argument("--seed", type=int, default=20261001)
    result.add_argument("--hidden-dim", type=int, default=32)
    result.add_argument("--layers", type=int, default=2)
    result.add_argument("--dropout", type=float, default=0.20)
    result.add_argument("--learning-rate", type=float, default=0.003)
    result.add_argument("--weight-decay", type=float, default=0.0001)
    result.add_argument("--epochs", type=int, default=250)
    result.add_argument("--patience", type=int, default=35)
    result.add_argument("--min-delta", type=float, default=0.0001)
    result.add_argument("--threads", type=int, default=4)
    result.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    result.add_argument("--batch-size", type=int, default=512)
    result.add_argument(
        "--cache-graphs",
        action="store_true",
        help="keep normalized graph tensors on the target device between epochs",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(train(parser().parse_args()), indent=2, sort_keys=True))
