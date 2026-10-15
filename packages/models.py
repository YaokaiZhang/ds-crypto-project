"""Native PyTorch backbones for independent Scam binary models."""
from __future__ import annotations

from typing import Any, Mapping
from types import MappingProxyType

import torch
from torch import Tensor, nn

from .graph import GraphBatch


def _mean_messages(messages: Tensor, destination: Tensor, num_nodes: int) -> Tensor:
    result = messages.new_zeros((num_nodes, messages.shape[-1]))
    result.index_add_(0, destination, messages)
    count = messages.new_zeros(num_nodes)
    count.index_add_(0, destination, messages.new_ones(len(destination)))
    return result / count.clamp_min(1).unsqueeze(-1)


class MeanSAGE(nn.Module):
    """Mean aggregation baseline; explicitly ignores edge features/relations."""
    consumed_inputs = ["node_features", "edge_index", "root_index"]

    def __init__(self, input_dim: int, hidden_dim: int = 64, layers: int = 2, dropout: float = .2) -> None:
        super().__init__()
        self.self_layers = nn.ModuleList(nn.Linear(input_dim if layer == 0 else hidden_dim, hidden_dim) for layer in range(layers))
        self.neighbor_layers = nn.ModuleList(nn.Linear(input_dim if layer == 0 else hidden_dim, hidden_dim) for layer in range(layers))
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(hidden_dim, 1)

    def forward(self, batch: GraphBatch) -> Tensor:
        h = batch.x
        source, destination = batch.edge_index
        for own, neighbor in zip(self.self_layers, self.neighbor_layers):
            aggregate = _mean_messages(h[source], destination, len(h))
            h = self.dropout(torch.relu(own(h) + neighbor(aggregate)))
        return self.head(h[batch.root_indices]).squeeze(-1)


class DirectedEdgeSAGE(nn.Module):
    """Separate per-relation means, edge messages, residuals and JK readout."""
    consumed_inputs = ["node_features", "edge_index", "edge_attributes", "relation_ids", "root_index"]

    def __init__(self, input_dim: int, edge_dim: int, num_relations: int, hidden_dim: int = 64,
                 layers: int = 2, dropout: float = .2, ignore_direction: bool = False,
                 ignore_relations: bool = False, ignore_edge_attr: bool = False) -> None:
        super().__init__()
        self.num_relations = num_relations
        self.ignore_direction, self.ignore_relations, self.ignore_edge_attr = ignore_direction, ignore_relations, ignore_edge_attr
        self.consumed_inputs = ["node_features", "edge_index", "root_index"]
        if not ignore_edge_attr:
            self.consumed_inputs.append("edge_attributes")
        if not ignore_relations:
            self.consumed_inputs.append("relation_ids")
        self.project = nn.Linear(input_dim, hidden_dim)
        self.self_layers = nn.ModuleList(nn.Linear(hidden_dim, hidden_dim) for _ in range(layers))
        self.edge_mlps = nn.ModuleList(nn.Sequential(nn.Linear(edge_dim, hidden_dim), nn.ReLU(), nn.Linear(hidden_dim, hidden_dim)) for _ in range(layers))
        self.relation_nodes = nn.ModuleList(nn.ModuleList(nn.Linear(hidden_dim, hidden_dim, bias=False) for _ in range(num_relations)) for _ in range(layers))
        self.relation_edges = nn.ModuleList(nn.ModuleList(nn.Linear(hidden_dim, hidden_dim, bias=False) for _ in range(num_relations)) for _ in range(layers))
        self.norms = nn.ModuleList(nn.LayerNorm(hidden_dim) for _ in range(layers))
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Sequential(nn.Linear(hidden_dim * (layers + 1), hidden_dim), nn.ReLU(), nn.Dropout(dropout), nn.Linear(hidden_dim, 1))

    def forward(self, batch: GraphBatch) -> Tensor:
        h = torch.relu(self.project(batch.x))
        representations = [h]
        source, destination = batch.edge_index
        relations = batch.relation_ids
        if relations.numel() and (relations.min() < 0 or relations.max() >= self.num_relations):
            raise ValueError("message relation ID outside model schema")
        if self.ignore_direction:
            relations = relations % (self.num_relations // 2)
        if self.ignore_relations:
            relations = torch.zeros_like(relations)
        for own, edge_mlp, node_weights, edge_weights, norm in zip(
                self.self_layers, self.edge_mlps, self.relation_nodes, self.relation_edges, self.norms):
            edge_h = edge_mlp(batch.edge_attr)
            if self.ignore_edge_attr:
                edge_h = torch.zeros_like(edge_h)
            aggregate = torch.zeros_like(h)
            for relation in torch.unique(relations).tolist():
                selected = relations == relation
                messages = node_weights[relation](h[source[selected]]) + edge_weights[relation](edge_h[selected])
                aggregate = aggregate + _mean_messages(messages, destination[selected], len(h))
            h = self.dropout(torch.relu(norm(own(h) + aggregate + h)))
            representations.append(h)
        root_h = torch.cat([representation[batch.root_indices] for representation in representations], dim=-1)
        return self.head(root_h).squeeze(-1)


def _mean_factory(config: Mapping[str, Any], input_dim: int, edge_dim: int, num_relations: int,
                  hidden: int, layers: int, dropout: float) -> nn.Module:
    return MeanSAGE(input_dim, hidden, layers, dropout)


def _directed_factory(config: Mapping[str, Any], input_dim: int, edge_dim: int, num_relations: int,
                      hidden: int, layers: int, dropout: float) -> nn.Module:
    if num_relations % 2:
        raise ValueError("directed model expects forward + reverse relation schema")
    return DirectedEdgeSAGE(input_dim, edge_dim, num_relations, hidden, layers, dropout,
        bool(config.get("ignore_direction", False)), bool(config.get("ignore_relations", False)),
        bool(config.get("ignore_edge_attr", False)))


BACKBONE_FACTORIES = MappingProxyType({"mean_sage": _mean_factory, "directed_edge_sage": _directed_factory})


def create_model(config: Mapping[str, Any], input_dim: int, edge_dim: int, num_relations: int) -> nn.Module:
    architecture = config.get("architecture_id", "directed_edge_sage")
    layers, hidden, dropout = int(config.get("layers", 2)), int(config.get("hidden_dim", 64)), float(config.get("dropout", .2))
    if layers not in {2, 3, 4} or hidden < 1 or not 0 <= dropout < 1 or input_dim < 1 or edge_dim < 1 or num_relations < 1:
        raise ValueError("invalid model dimensions/depth/dropout")
    try:
        factory = BACKBONE_FACTORIES[architecture]
    except KeyError as error:
        raise ValueError(f"unsupported architecture_id: {architecture}") from error
    return factory(config, input_dim, edge_dim, num_relations, hidden, layers, dropout)
