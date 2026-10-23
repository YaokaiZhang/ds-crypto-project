"""Versioned, checked model packages and label-independent prediction.

Weights are a tensor-only state dict loaded with ``weights_only=True``. This is
a local model-artifact interface, not an HTTP/deployment service.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .graph import (RELATION_NAMES, SCHEMA_VERSION, batch_graph_samples, graph_is_usable, graph_recipe,
    validate_graph_sample, graph_schema)
from .tasks import get_task

BUNDLE_VERSION = "chainrisk-bundle-1.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _bundle_digest(manifest: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items()
               if key not in {"bundle_sha256", "model_version"}}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_manifest(manifest: Mapping[str, Any], expected_task: str | None = None) -> None:
    mode = manifest.get("graph_recipe", {}).get("sampling", {}).get("sampling_mode")
    view, features, edge_features = graph_schema(manifest.get("task_id"), mode)
    if manifest.get("bundle_version") != BUNDLE_VERSION:
        raise ValueError("unsupported model bundle version")
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("graph_view_version") != view:
        raise ValueError("model bundle graph schema/version mismatch")
    if manifest.get("feature_names") != features or manifest.get("edge_feature_names") != edge_features or manifest.get("relation_names") != RELATION_NAMES:
        raise ValueError("model bundle feature/relation schema mismatch")
    if manifest.get("input_dim") != len(features) or manifest.get("edge_dim") != len(edge_features) or manifest.get("num_relations") != 2 * len(RELATION_NAMES):
        raise ValueError("model bundle dimensions incompatible with schema")
    if manifest.get("task_id") not in {"phishing", "ponzi", "honeypot", "rug_pull"} or manifest.get("chain_id") != 1:
        raise ValueError("unsupported model task/chain")
    if not get_task(manifest["task_id"]).trainable:
        raise ValueError("task is data_only; model export/load is not admitted")
    if expected_task is not None and manifest["task_id"] != expected_task:
        raise ValueError("model bundle task mismatch")
    threshold = manifest.get("threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("invalid decision threshold")
    if manifest.get("add_reverse") is not True:
        raise ValueError("v1 bundles require independent reverse message relations")
    recipe = manifest.get("graph_recipe")
    if not isinstance(recipe, dict) or recipe.get("builder") != get_task(manifest["task_id"]).graph_family or not isinstance(recipe.get("sampling"), dict):
        raise ValueError("model bundle graph recipe missing or incompatible")


def export_model_bundle(
    path: str | Path, model: Any, model_config: Mapping[str, Any],
    scaler: Mapping[str, Any], task_id: str, threshold: float,
    training_manifest: Mapping[str, Any], calibration_status: str = "uncalibrated",
) -> dict[str, Any]:
    import torch
    view, features, edge_features = graph_schema(task_id, scaler.get("graph_recipe", {}).get("sampling", {}).get("sampling_mode"))
    destination = Path(path)
    destination.mkdir(parents=True, exist_ok=True)
    if any((destination / filename).exists() for filename in ("model.pt", "scaler.json", "manifest.json")):
        raise FileExistsError("refusing to overwrite an existing model bundle")
    if scaler.get("feature_names") != features or scaler.get("edge_feature_names") != edge_features:
        raise ValueError("export scaler schema mismatch")
    config = dict(model_config)
    config.setdefault("architecture_id", "directed_edge_sage")
    weights_path, scaler_path = destination / "model.pt", destination / "scaler.json"
    experiment_mode = training_manifest.get("config", {}).get("experiment_mode", training_manifest.get("experiment_mode", "supervised"))
    proxy = experiment_mode == "known_positive_vs_unlabeled"
    recipe = training_manifest.get("graph_recipe", scaler.get("graph_recipe"))
    if recipe != scaler.get("graph_recipe"):
        raise ValueError("training manifest/scaler graph recipes disagree")
    manifest = {
        "bundle_version": BUNDLE_VERSION, "task_id": task_id, "chain_id": 1,
        "code_version": "chainrisk-0.1.0",
        "schema_version": SCHEMA_VERSION, "graph_view_version": view,
        "feature_names": features, "edge_feature_names": edge_features,
        "relation_names": list(RELATION_NAMES), "add_reverse": True,
        "graph_recipe": recipe,
        "input_dim": len(features), "edge_dim": len(edge_features),
        "num_relations": 2 * len(RELATION_NAMES), "model_config": config,
        "consumed_inputs": list(model.consumed_inputs), "threshold": threshold,
        "label_meanings": {"1": get_task(task_id).positive,
                           "0": "sampled_unlabeled_background" if proxy else "audited_task_specific_negative"},
        "positive_meaning": "known positive in frozen source; prediction is screening evidence" if proxy else "task-specific pattern screening; model output is not definitive mechanism evidence",
        "score_meaning": "known_positive_vs_sampled_unlabeled" if proxy else "uncalibrated_pattern_screening_score",
        "calibration_status": calibration_status, "training_manifest": dict(training_manifest),
        "weights_file": "model.pt", "scaler_file": "scaler.json",
    }
    _validate_manifest(manifest)
    torch.save({key: value.detach().cpu() for key, value in model.state_dict().items()}, weights_path)
    _write_json(scaler_path, dict(scaler))
    manifest["weights_sha256"] = _sha256(weights_path)
    manifest["scaler_sha256"] = _sha256(scaler_path)
    manifest["bundle_sha256"] = _bundle_digest(manifest)
    manifest["model_version"] = task_id + "-" + manifest["bundle_sha256"][:16]
    _write_json(destination / "manifest.json", manifest)
    return manifest


@dataclass
class ModelBundle:
    model: Any
    scaler: dict[str, Any]
    manifest: dict[str, Any]


def load_model_bundle(path: str | Path, device: Any = "cpu", expected_task: str | None = None) -> ModelBundle:
    directory = Path(path)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    _validate_manifest(manifest, expected_task)
    digest = _bundle_digest(manifest)
    if manifest.get("bundle_sha256") != digest or manifest.get("model_version") != manifest["task_id"] + "-" + digest[:16]:
        raise ValueError("model bundle manifest checksum/identity mismatch")
    # Fixed filenames also prevent a manifest from escaping the package directory.
    if manifest.get("weights_file") != "model.pt" or manifest.get("scaler_file") != "scaler.json":
        raise ValueError("model bundle filenames are invalid")
    for filename, checksum_key in (("model.pt", "weights_sha256"), ("scaler.json", "scaler_sha256")):
        if _sha256(directory / filename) != manifest.get(checksum_key):
            raise ValueError(f"model bundle checksum mismatch: {filename}")
    scaler = json.loads((directory / "scaler.json").read_text(encoding="utf-8"))
    if scaler.get("feature_names") != manifest["feature_names"] or scaler.get("edge_feature_names") != manifest["edge_feature_names"]:
        raise ValueError("model bundle scaler schema mismatch")
    if scaler.get("graph_recipe") != manifest["graph_recipe"]:
        raise ValueError("model bundle scaler/manifest graph recipes disagree")
    import torch
    from .models import create_model
    model = create_model(manifest["model_config"], manifest["input_dim"], manifest["edge_dim"], manifest["num_relations"])
    if list(model.consumed_inputs) != manifest.get("consumed_inputs"):
        raise ValueError("manifest consumed_inputs contradict model architecture")
    weights = torch.load(directory / "model.pt", map_location=device, weights_only=True)
    model.load_state_dict(weights, strict=True)
    model.to(device).eval()
    return ModelBundle(model, scaler, manifest)


def predict_bundle(
    bundle_or_path: ModelBundle | str | Path,
    samples: Sequence[Mapping[str, Any]], device: Any = "cpu", batch_size: int = 32,
) -> list[dict[str, Any]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    try:
        bundle = (bundle_or_path if isinstance(bundle_or_path, ModelBundle)
                  else load_model_bundle(bundle_or_path, device))
    except FileNotFoundError:
        results = []
        for sample in samples:
            validate_graph_sample(sample)
            results.append({"sample_id": sample["sample_id"], "task_id": sample["task_id"],
                "target": sample["target"], "cutoff": sample["cutoff"], "status": "model_unavailable",
                "score": None, "predicted_label": None, "predicted_class": None,
                "quality": dict(sample["quality"]), "model_version": None,
                "score_meaning": "unavailable", "calibration_status": "unavailable",
                "result_origin": "model", "evidence": []})
        return results
    _validate_manifest(bundle.manifest)
    outputs: list[dict[str, Any]] = []
    usable: list[Mapping[str, Any]] = []
    usable_indices: list[int] = []
    for sample in samples:
        validate_graph_sample(sample)
        if sample["task_id"] != bundle.manifest["task_id"]:
            raise ValueError("prediction graph task does not match model bundle")
        if graph_recipe(sample) != bundle.manifest["graph_recipe"]:
            raise ValueError("prediction graph recipe does not match model bundle")
        quality = dict(sample["quality"])
        good = graph_is_usable(sample)
        status = "ok" if good else quality["status"]
        if not good and status == "ok":
            status = "data_incomplete"
        outputs.append({"sample_id": sample["sample_id"], "task_id": sample["task_id"],
            "target": sample["target"], "cutoff": sample["cutoff"], "status": status,
            "score": None, "predicted_label": None, "predicted_class": None, "quality": quality,
            "model_version": bundle.manifest.get("model_version"),
            "score_meaning": bundle.manifest["score_meaning"],
            "calibration_status": bundle.manifest["calibration_status"],
            "result_origin": "model", "evidence": []})
        if good:
            usable_indices.append(len(outputs) - 1)
            usable.append(sample)
    if usable:
        import torch
        bundle.model.to(device).eval()
        with torch.inference_mode():
            for start in range(0, len(usable), batch_size):
                batch = batch_graph_samples(usable[start:start + batch_size], bundle.scaler, device, add_reverse=True)
                logits = bundle.model(batch)
                scores = torch.sigmoid(logits).detach().cpu().tolist()
                if len(scores) != len(batch.sample_ids):
                    raise ValueError("model output count does not match graph count")
                for position, score in enumerate(scores):
                    result = outputs[usable_indices[start + position]]
                    if not math.isfinite(score):
                        result["status"] = "model_error"
                        continue
                    predicted = int(score >= bundle.manifest["threshold"])
                    result.update(score=float(score), predicted_class=predicted,
                        predicted_label="screen_positive" if predicted else "screen_negative")
    return outputs


# Concise aliases for research callers; both retain the same admission checks.
load_bundle = load_model_bundle
export_bundle = export_model_bundle
