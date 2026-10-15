"""Thin command orchestration over task, source, graph and model strategies."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sys
from types import MappingProxyType

from packages.io import load_json, read_records, save_json, sha256_file, write_records
from packages.tasks import canonical_task, get_task
from packages.collection import CollectionError
from packages.progress import add_progress_arguments


@dataclass(frozen=True)
class CommandContext:
    args: argparse.Namespace
    task_id: str | None
    config: dict


def _require(args, *names):
    for name in names:
        if getattr(args, name, None) is None:
            raise ValueError(f"--{name.replace('_', '-')} is required for this command")


def _task_rows(path, task):
    rows = read_records(path)
    selected = [dict(row, task_id=canonical_task(row.get("task_id", task))) for row in rows
                if canonical_task(row.get("task_id", task)) == task]
    if not selected:
        raise ValueError(f"no records for task {task}: {path}")
    return selected


def _write(ctx, path, rows):
    if not ctx.args.dry_run:
        if path is None:
            raise ValueError("--output is required outside --dry-run")
        write_records(path, rows)


def _import_labels(ctx):
    from packages.labeling import import_labels
    a = ctx.args
    _require(a, "input", "source")
    rows = import_labels(a.source, a.input, ctx.task_id, mapping_path=a.mapping)
    _write(ctx, a.output, rows)
    return {"status": "validated" if a.dry_run else "imported", "task_id": ctx.task_id,
            "records": len(rows), "input_sha256": sha256_file(a.input),
            "label_status_counts": {status: sum(row["label_status"] == status for row in rows)
                                    for status in sorted({row["label_status"] for row in rows})}}


def _collect(ctx):
    from packages.collection import collect_dataset
    a = ctx.args
    _require(a, "targets")
    if not a.dry_run:
        _require(a, "output")
    settings = dict(ctx.config.get("collection", {}))
    settings.update(ctx.config.get("graph", {}))
    if a.settings:
        settings.update(load_json(a.settings))
    if a.allow_network:
        settings["allow_network"] = True
    # No key is supplied as a CLI argument or saved into experiment settings.
    return collect_dataset(_task_rows(a.targets, ctx.task_id), a.output or "data/scam/unused-dry-run",
                           settings, dry_run=a.dry_run)


def _verify_targets(ctx):
    from packages.token_sources import verify_token_targets
    a = ctx.args
    _require(a, "targets")
    if not a.dry_run:
        _require(a, "output")
    settings = load_json(a.settings) if a.settings else {}
    settings["allow_network"] = a.allow_network
    return verify_token_targets(_task_rows(a.targets, ctx.task_id), a.output or "unused-dry-run", settings, a.dry_run)


def _capture_honeypot(ctx):
    from packages.token_sources import collect_honeypot_evidence
    a = ctx.args
    _require(a, "targets")
    if not a.dry_run:
        _require(a, "output")
    settings = load_json(a.settings) if a.settings else {}
    settings["allow_network"] = a.allow_network
    return collect_honeypot_evidence(_task_rows(a.targets, ctx.task_id), a.output or "unused-dry-run", settings, a.dry_run)


def _prepare(ctx):
    from .preparation import prepare_dataset
    a = ctx.args
    _require(a, "events", "targets", "input")
    if not a.dry_run:
        _require(a, "output")
    return prepare_dataset(a.events, a.targets, a.input, ctx.config, a.output,
                           training_as_of=a.training_as_of, audit_path=a.audit, dry_run=a.dry_run)


def _normalize(ctx):
    from packages.data import normalize_bundle
    a = ctx.args
    _require(a, "input")
    rows, audit = normalize_bundle(a.input)
    _write(ctx, a.output, rows)
    if not a.dry_run:
        save_json(a.audit or str(a.output) + ".audit.json", audit)
    return {"status": "validated" if a.dry_run else "normalized", "events": len(rows), "audit": audit}


def _label(ctx):
    from packages.labeling import reconcile_labels
    a = ctx.args
    _require(a, "input", "targets")
    rows = reconcile_labels(_task_rows(a.input, ctx.task_id), _task_rows(a.targets, ctx.task_id), a.training_as_of)
    _write(ctx, a.output, rows)
    return {"status": "validated" if a.dry_run else "reconciled", "records": len(rows),
            "supervised_eligible": sum(row["eligible"] for row in rows)}


def _build_graphs(ctx):
    from packages.graph import build_graph_sample, validate_graph_sample
    a = ctx.args
    _require(a, "events", "targets")
    events = read_records(a.events)
    targets = _task_rows(a.targets, ctx.task_id)
    if a.coverage:
        coverage = {row["sample_id"]: row for row in read_records(a.coverage)}
        targets = [dict(row, coverage=coverage.get(row["sample_id"], {"complete": False})) for row in targets]
    audit_paths = [Path(a.audit)] if a.audit else [Path(str(a.events) + ".audit.json"), Path(a.events).parent / "normalization_audit.json"]
    for audit_path in audit_paths:
        if audit_path.is_file() and load_json(audit_path).get("complete") is not True:
            targets = [dict(row, coverage={**row.get("coverage", {}), "complete": False,
                                          "normalization_failure": True}) for row in targets]
    options = {key: value for key, value in ctx.config.get("graph", {}).items()
               if key in {"window_days", "hops", "fanouts", "max_nodes", "max_edges", "seed", "builder_name"}}
    options.setdefault("seed", ctx.config.get("seed", 20261008))
    graphs = [build_graph_sample(target, events, **options) for target in targets]
    for graph in graphs:
        validate_graph_sample(graph)
    _write(ctx, a.output, graphs)
    return {"status": "validated" if a.dry_run else "built", "graphs": len(graphs),
            "quality_status_counts": {status: sum(g["quality"]["status"] == status for g in graphs)
                                      for status in sorted({g["quality"]["status"] for g in graphs})}}


def _split(ctx):
    from .splitting import split_records
    a = ctx.args
    _require(a, "supervision")
    mode = a.experiment_mode or ctx.config.get("experiment_mode", "supervised_binary")
    rows, manifest = split_records(_task_rows(a.supervision, ctx.task_id),
                                  seed=ctx.config.get("seed", 20261008), mode=mode,
                                  training_as_of=a.training_as_of if a.training_as_of is not None else ctx.config.get("training_as_of"))
    _write(ctx, a.output, rows)
    if not a.dry_run:
        save_json(a.manifest or str(a.output) + ".manifest.json", manifest)
    return {"status": "validated" if a.dry_run else "split", **manifest}


def _train(ctx):
    from .training import train, validate_config
    a = ctx.args
    if not get_task(ctx.task_id).trainable:
        return {"status": "data_only", "task_id": ctx.task_id, "training_supported": False}
    _require(a, "graphs", "supervision", "splits")
    config = dict(ctx.config, task_id=ctx.task_id)
    config["model"] = dict(config.get("model", {}))
    config["loss"] = dict(config.get("loss", {}))
    if a.architecture:
        config["model"]["architecture_id"] = a.architecture
    if a.loss:
        config["loss"]["name"] = a.loss
    if a.device:
        config["device"] = a.device
    if a.epochs is not None:
        config["epochs"] = a.epochs
    if a.training_as_of is not None:
        config["training_as_of"] = a.training_as_of
    if a.progress is not None:
        config["progress"] = a.progress
    config = validate_config(config)
    if not a.dry_run:
        _require(a, "output")
    return train(_task_rows(a.graphs, ctx.task_id), _task_rows(a.supervision, ctx.task_id),
                 _task_rows(a.splits, ctx.task_id), config, a.output or "data/scam/unused-dry-run", a.dry_run)


def _evaluate(ctx):
    from .training import evaluate_bundle
    a = ctx.args
    if not get_task(ctx.task_id).trainable:
        return {"status": "data_only", "task_id": ctx.task_id}
    _require(a, "graphs", "supervision", "splits", "bundle")
    if not a.dry_run:
        _require(a, "output")
    # Evaluation consumes the bundle's frozen experiment contract. CLI task
    # filtering and the helper's task/recipe checks prevent a silent mismatch.
    return evaluate_bundle(a.bundle, _task_rows(a.graphs, ctx.task_id),
                           _task_rows(a.supervision, ctx.task_id), _task_rows(a.splits, ctx.task_id),
                           partition=a.partition, out=None if a.dry_run else a.output,
                           dry_run=a.dry_run, device=a.device, progress=a.progress)


def _export(ctx):
    from packages.bundle import load_model_bundle
    a = ctx.args
    if not get_task(ctx.task_id).trainable:
        return {"status": "data_only", "task_id": ctx.task_id}
    _require(a, "run_dir")
    source = Path(a.run_dir) / "bundle"
    bundle = load_model_bundle(source, expected_task=ctx.task_id)
    if not a.dry_run:
        _require(a, "output")
        shutil.copytree(source, a.output)  # Refuses overwriting an existing artifact.
    return {"status": "validated" if a.dry_run else "exported", "manifest": bundle.manifest}


def _predict(ctx):
    from packages.graph import validate_graph_sample
    a = ctx.args
    _require(a, "graphs")
    graphs = _task_rows(a.graphs, ctx.task_id)
    for graph in graphs:
        validate_graph_sample(graph)
    if a.dry_run:
        return {"status": "validated", "graphs": len(graphs), "requires_label": False}
    model_files_present = bool(a.bundle and all((Path(a.bundle) / name).is_file()
                                                for name in ("manifest.json", "model.pt", "scaler.json")))
    if not get_task(ctx.task_id).trainable or not model_files_present:
        status = "data_only" if not get_task(ctx.task_id).trainable else "model_unavailable"
        rows = [{"sample_id": g["sample_id"], "task_id": ctx.task_id, "target": g["target"],
                 "cutoff": g["cutoff"], "status": status, "score": None, "predicted_label": None,
                 "model_version": None, "quality": g["quality"], "score_meaning": None,
                 "calibration_status": "unavailable", "result_origin": "unavailable"} for g in graphs]
    else:
        from packages.bundle import load_model_bundle, predict_bundle
        from .training import resolve_device
        device = resolve_device(a.device or "cpu")
        bundle = load_model_bundle(a.bundle, device=device, expected_task=ctx.task_id)
        rows = predict_bundle(bundle, graphs, device=device)
    _write(ctx, a.output, rows)
    return {"status": "predicted", "results": rows}


def _resolve(ctx):
    from packages.transactions import resolve_transaction
    a = ctx.args
    _require(a, "input")
    tx = load_json(a.input)
    receipt = load_json(a.receipt) if a.receipt else None
    known = load_json(a.known_entities) if a.known_entities else None
    rows = resolve_transaction(tx, receipt, known)
    if a.output and not a.dry_run:
        save_json(a.output, {"entities": rows, "score": None, "score_meaning": "entity_resolution_only"})
    return {"status": "resolved", "entities": rows, "score": None,
            "score_meaning": "entity_resolution_only", "requires_entity_history": True}


COMMANDS = MappingProxyType({
    "import-labels": _import_labels, "collect": _collect, "normalize": _normalize,
    "label": _label, "build-graphs": _build_graphs, "split": _split, "train": _train,
    "evaluate": _evaluate, "export": _export, "predict": _predict, "resolve-transaction": _resolve,
    "verify-token-targets": _verify_targets, "capture-honeypot": _capture_honeypot, "prepare": _prepare,
})


def parser():
    root = argparse.ArgumentParser(description="Scam offline data and GraphSAGE framework; no services")
    subs = root.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        p = subs.add_parser(name)
        p.add_argument("--task", required=name != "resolve-transaction")
        p.add_argument("--config", help="JSON config; defaults to configs/<task>.json")
        p.add_argument("--output")
        p.add_argument("--dry-run", action="store_true", help="Validate/plan without writing outputs or calling the network")
        if name in {"import-labels", "normalize", "label", "resolve-transaction", "prepare"}:
            p.add_argument("--input")
        if name == "import-labels":
            p.add_argument("--source")
            p.add_argument("--mapping")
        if name in {"collect", "label", "build-graphs", "verify-token-targets", "capture-honeypot", "prepare"}:
            p.add_argument("--targets")
        if name in {"collect", "verify-token-targets", "capture-honeypot"}:
            p.add_argument("--settings")
            p.add_argument("--allow-network", action="store_true", help="Explicit opt-in; key is read from ETHERSCAN_API_KEY")
        if name == "normalize":
            p.add_argument("--audit")
        if name in {"build-graphs", "prepare"}:
            p.add_argument("--events")
            if name == "build-graphs":
                p.add_argument("--coverage")
            p.add_argument("--audit", help="Normalization audit; otherwise checks the standard adjacent audit files")
        if name in {"split", "train", "evaluate"}:
            p.add_argument("--supervision")
        if name in {"label", "split", "train", "evaluate", "prepare"}:
            p.add_argument("--training-as-of", type=int)
        if name == "split":
            p.add_argument("--experiment-mode", choices=["supervised_binary", "known_positive_vs_unlabeled"])
            p.add_argument("--manifest")
        if name in {"train", "evaluate", "predict"}:
            p.add_argument("--graphs")
            p.add_argument("--device", choices=["cpu", "mps", "cuda", "auto"])
        if name in {"train", "evaluate"}:
            p.add_argument("--splits")
            add_progress_arguments(p, default=None)
        if name == "train":
            p.add_argument("--architecture", choices=["mean_sage", "directed_edge_sage"])
            p.add_argument("--loss", choices=["weighted_bce", "focal"])
            p.add_argument("--epochs", type=int)
        if name in {"evaluate", "predict"}:
            p.add_argument("--bundle")
        if name == "evaluate":
            p.add_argument("--partition", choices=["train", "validation", "test"], default="test")
        if name == "export":
            p.add_argument("--run-dir")
        if name == "resolve-transaction":
            p.add_argument("--receipt")
            p.add_argument("--known-entities")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        task = canonical_task(args.task) if args.task else None
        config_path = Path(args.config) if args.config else Path(__file__).parent / "configs" / f"{task}.json"
        config = load_json(config_path) if config_path.is_file() else {"task_id": task}
        if not isinstance(config, dict):
            raise ValueError("config must be a JSON object")
        if args.config and not config_path.is_file():
            raise FileNotFoundError(config_path)
        if task and config.get("task_id") and canonical_task(config["task_id"]) != task:
            raise ValueError("--config task does not match --task")
        result = COMMANDS[args.command](CommandContext(args, task, config))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except (ValueError, FileNotFoundError, FileExistsError, ImportError, KeyError, NotImplementedError, CollectionError) as exc:
        print(json.dumps({"status": "error", "command": args.command, "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
