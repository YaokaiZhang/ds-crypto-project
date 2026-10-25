"""Checked Forecast (Task A continued_activity) bundles and prediction.

The Forecast model is a seed ensemble of edge-aware GCNs over the first-week
wallet --swap_activity--> pool --contains_token--> token graph built by
``scripts.build_wallet_graph``. It does not use the Scam graph schema, so it has
its own bundle format. Weights are tensor-only state dicts loaded with
``weights_only=True``; the frozen training scaler is applied exactly once.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor, nn

BUNDLE_VERSION = "forecast-bundle-1.0"
TASK_ID = "continued_activity"
ARCHITECTURES = frozenset({"edge_gcn"})
# Full research graphs and the pruned revision differ only by dropped columns,
# so features are selected by name rather than by position.
GRAPH_VERSIONS = frozenset({"wallet-graph-input-0.1", "wallet-graph-input-pruned-20261010-0.1"})
MAX_NODES, MAX_EDGES = 50_000, 200_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_digest(manifest: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key not in {"bundle_sha256", "model_version"}}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class EdgeGCN(nn.Module):
    """Degree-normalized graph convolution with edge-conditioned messages.

    Identical parameters and forward pass to the Task A training script, so
    research checkpoints load with ``strict=True``. Node 0 of every graph is the
    target token; its logit is the prediction.
    """

    def __init__(self, input_dim: int, edge_dim: int, hidden_dim: int, dropout: float, layers: int = 2) -> None:
        super().__init__()
        self.self_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        self.source_layers = nn.ModuleList([nn.Linear(input_dim, hidden_dim)])
        self.edge_layers = nn.ModuleList([nn.Linear(edge_dim, hidden_dim)])
        for _ in range(1, layers):
            self.self_layers.append(nn.Linear(hidden_dim, hidden_dim))
            self.source_layers.append(nn.Linear(hidden_dim, hidden_dim))
            self.edge_layers.append(nn.Linear(edge_dim, hidden_dim))
        self.dropout = nn.Dropout(dropout)
        self.output = nn.Linear(hidden_dim, 1)

    def forward(self, x: Tensor, edge_index: Tensor, edge_features: Tensor, centers: Tensor) -> Tensor:
        source, destination = edge_index
        degree = torch.zeros(x.shape[0], dtype=x.dtype, device=x.device)
        degree.index_add_(0, destination, torch.ones_like(destination, dtype=x.dtype))
        normalization = torch.rsqrt(degree[source].clamp_min(1.0) * degree[destination].clamp_min(1.0))
        h = x
        for self_layer, source_layer, edge_layer in zip(self.self_layers, self.source_layers, self.edge_layers):
            source_states = source_layer(h)
            messages = (source_states[source] + edge_layer(edge_features)) * normalization.unsqueeze(1)
            neighbor_sum = torch.zeros_like(source_states)
            neighbor_sum.index_add_(0, destination, messages)
            h = self.dropout(torch.relu(self_layer(h) + neighbor_sum))
        return self.output(h).squeeze(-1)[centers]


def create_model(config: Mapping[str, Any], input_dim: int, edge_dim: int) -> nn.Module:
    if config.get("architecture_id") not in ARCHITECTURES:
        raise ValueError("unsupported Forecast architecture")
    layers, hidden, dropout = int(config["layers"]), int(config["hidden_dim"]), float(config["dropout"])
    if layers not in {1, 2, 3, 4} or hidden < 1 or not 0 <= dropout < 1 or input_dim < 1 or edge_dim < 1:
        raise ValueError("invalid Forecast model dimensions")
    return EdgeGCN(input_dim, edge_dim, hidden, dropout, layers)


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("bundle_version") != BUNDLE_VERSION or manifest.get("task_id") != TASK_ID or manifest.get("chain_id") != 1:
        raise ValueError("unsupported Forecast bundle version/task/chain")
    nodes, edges = manifest.get("node_feature_names"), manifest.get("edge_feature_names")
    if (not isinstance(nodes, list) or not isinstance(edges, list) or len(set(nodes)) != len(nodes)
            or len(set(edges)) != len(edges) or manifest.get("input_dim") != len(nodes) or manifest.get("edge_dim") != len(edges)):
        raise ValueError("Forecast feature schema/dimensions are inconsistent")
    threshold = manifest.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("invalid Forecast decision threshold")
    members = manifest.get("members")
    if not isinstance(members, list) or not members or manifest.get("aggregation") != "mean_probability":
        raise ValueError("Forecast bundle requires mean-probability ensemble members")
    files = [member.get("weights_file") for member in members]
    # Fixed name pattern prevents a manifest from escaping the bundle directory.
    if len(set(files)) != len(files) or any(not isinstance(f, str) or "/" in f or "\\" in f or not f.endswith(".pt") for f in files):
        raise ValueError("Forecast member filenames are invalid")
    if manifest.get("scaler_file") != "scaler.json":
        raise ValueError("Forecast scaler filename is invalid")


@dataclass
class ForecastBundle:
    models: list[nn.Module]
    scaler: dict[str, Any]
    manifest: dict[str, Any]


def export_forecast_bundle(
    path: str | Path, state_dicts: Sequence[tuple[str, Mapping[str, Tensor], Mapping[str, Any]]],
    model_config: Mapping[str, Any], scaler: Mapping[str, Any], threshold: float,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Write weights, scaler and a checksummed manifest; never overwrite."""
    destination = Path(path)
    destination.mkdir(parents=True, exist_ok=False)
    nodes, edges = list(scaler["node_feature_names"]), list(scaler["edge_feature_names"])
    members = []
    for filename, weights, provenance in state_dicts:
        model = create_model(model_config, len(nodes), len(edges))
        model.load_state_dict(weights, strict=True)
        torch.save({key: value.detach().cpu() for key, value in model.state_dict().items()}, destination / filename)
        members.append({"weights_file": filename, "weights_sha256": _sha256(destination / filename), **provenance})
    (destination / "scaler.json").write_text(json.dumps(dict(scaler), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    manifest = {
        "bundle_version": BUNDLE_VERSION, "task_id": TASK_ID, "chain_id": 1,
        "accepted_graph_versions": sorted(GRAPH_VERSIONS),
        "node_feature_names": nodes, "edge_feature_names": edges,
        "input_dim": len(nodes), "edge_dim": len(edges), "model_config": dict(model_config),
        "aggregation": "mean_probability", "members": members, "threshold": float(threshold),
        "scaler_file": "scaler.json", "scaler_sha256": _sha256(destination / "scaler.json"),
        "score_meaning": "uncalibrated_continued_activity_score", "calibration_status": "uncalibrated",
        "label_meanings": {"1": "continued_activity", "0": "low_volume_dead"},
        **dict(metadata),
    }
    _validate_manifest(manifest)
    manifest["bundle_sha256"] = _bundle_digest(manifest)
    manifest["model_version"] = TASK_ID + "-" + manifest["bundle_sha256"][:16]
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return manifest


def load_forecast_bundle(path: str | Path, device: Any = "cpu") -> ForecastBundle:
    directory = Path(path)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    digest = _bundle_digest(manifest)
    if manifest.get("bundle_sha256") != digest or manifest.get("model_version") != TASK_ID + "-" + digest[:16]:
        raise ValueError("Forecast bundle manifest checksum/identity mismatch")
    if _sha256(directory / "scaler.json") != manifest.get("scaler_sha256"):
        raise ValueError("Forecast bundle checksum mismatch: scaler.json")
    scaler = json.loads((directory / "scaler.json").read_text(encoding="utf-8"))
    if scaler.get("node_feature_names") != manifest["node_feature_names"] or scaler.get("edge_feature_names") != manifest["edge_feature_names"]:
        raise ValueError("Forecast scaler schema mismatch")
    for kind, width in (("node", manifest["input_dim"]), ("edge", manifest["edge_dim"])):
        mean, std = scaler.get(f"{kind}_mean"), scaler.get(f"{kind}_std")
        if (not isinstance(mean, list) or not isinstance(std, list) or len(mean) != width or len(std) != width
                or not all(math.isfinite(v) for v in mean + std) or any(v <= 0 for v in std)):
            raise ValueError(f"Forecast {kind} scaler is invalid")
    models = []
    for member in manifest["members"]:
        weights_path = directory / member["weights_file"]
        if _sha256(weights_path) != member.get("weights_sha256"):
            raise ValueError(f"Forecast bundle checksum mismatch: {member['weights_file']}")
        model = create_model(manifest["model_config"], manifest["input_dim"], manifest["edge_dim"])
        model.load_state_dict(torch.load(weights_path, map_location=device, weights_only=True), strict=True)
        models.append(model.to(device).eval())
    return ForecastBundle(models, scaler, manifest)


def _columns(available: Any, required: Sequence[str], kind: str) -> list[int]:
    if not isinstance(available, list) or len(set(available)) != len(available):
        raise ValueError(f"graph {kind}_feature_names are required")
    missing = [name for name in required if name not in available]
    if missing:
        raise ValueError(f"graph is missing {kind} features: {', '.join(missing)}")
    return [available.index(name) for name in required]


def validate_forecast_graph(graph: Mapping[str, Any]) -> None:
    """Check the label-free wallet graph structure, before any scaling."""
    if not isinstance(graph, Mapping) or graph.get("graph_version") not in GRAPH_VERSIONS:
        raise ValueError("unsupported Forecast graph_version")
    nodes, edge_index, edges = graph.get("node_features"), graph.get("edge_index"), graph.get("edge_features")
    refs = graph.get("node_refs")
    if not isinstance(nodes, list) or not nodes or len(nodes) > MAX_NODES:
        raise ValueError("graph must contain the target node and fit the input budget")
    if (not isinstance(refs, list) or len(refs) != len(nodes) or not all(isinstance(ref, Mapping) for ref in refs)
            or refs[0].get("kind") != "center"):
        raise ValueError("node zero must be the target center")
    if (not isinstance(edge_index, list) or len(edge_index) != 2 or not all(isinstance(row, list) for row in edge_index)
            or len(edge_index[0]) != len(edge_index[1]) or len(edge_index[0]) > MAX_EDGES
            or not isinstance(edges, list) or len(edges) != len(edge_index[0])):
        raise ValueError("edge index/features must be aligned")
    if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(nodes) for row in edge_index for i in row):
        raise ValueError("edge index points outside node feature matrix")
    for kind, rows in (("node", nodes), ("edge", edges)):
        width = len(graph.get(f"{kind}_feature_names") or [])
        if any(not isinstance(row, list) or len(row) != width for row in rows):
            raise ValueError(f"{kind} feature width mismatch")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for row in rows for v in row):
            raise ValueError(f"non-finite {kind} feature")


def _tensors(graph: Mapping[str, Any], bundle: ForecastBundle, device: Any) -> tuple[Tensor, Tensor, Tensor]:
    scaler, manifest = bundle.scaler, bundle.manifest
    node_columns = _columns(graph.get("node_feature_names"), manifest["node_feature_names"], "node")
    edge_columns = _columns(graph.get("edge_feature_names"), manifest["edge_feature_names"], "edge")
    x = torch.tensor(graph["node_features"], dtype=torch.float32, device=device)[:, node_columns]
    x = (x - torch.tensor(scaler["node_mean"], device=device)) / torch.tensor(scaler["node_std"], device=device)
    edge_index = torch.tensor(graph["edge_index"], dtype=torch.long, device=device).reshape(2, -1)
    edge = torch.tensor(graph["edge_features"], dtype=torch.float32, device=device).reshape(-1, len(graph["edge_feature_names"]))
    edge = (edge[:, edge_columns] - torch.tensor(scaler["edge_mean"], device=device)) / torch.tensor(scaler["edge_std"], device=device)
    return x, edge_index, edge


def predict_forecast(bundle: ForecastBundle, graphs: Sequence[Mapping[str, Any]], device: Any = "cpu",
                     batch_size: int = 64) -> list[float]:
    """Return the mean continued_activity probability across ensemble members."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    scores: list[float] = []
    with torch.inference_mode():
        for start in range(0, len(graphs), batch_size):
            parts, centers, offset = [], [], 0
            for graph in graphs[start:start + batch_size]:
                validate_forecast_graph(graph)
                x, edge_index, edge = _tensors(graph, bundle, device)
                parts.append((x, edge_index + offset, edge))
                centers.append(offset)
                offset += x.shape[0]
            x = torch.cat([p[0] for p in parts])
            edge_index = torch.cat([p[1] for p in parts], dim=1)
            edge = torch.cat([p[2] for p in parts])
            center_index = torch.tensor(centers, dtype=torch.long, device=device)
            member_scores = torch.stack([torch.sigmoid(model(x, edge_index, edge, center_index)) for model in bundle.models])
            scores.extend(float(score) for score in member_scores.mean(0).cpu().tolist())
    if any(not math.isfinite(score) for score in scores):
        raise ValueError("Forecast model produced a non-finite score")
    return scores
