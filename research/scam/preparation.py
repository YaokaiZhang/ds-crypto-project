"""Freeze a quality-approved dataset, supervision and split without fitting."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from packages.graph import build_graph_sample, graph_is_usable
from packages.io import load_json, read_records, save_json, sha256_file, write_records
from packages.labeling import reconcile_labels
from packages.tasks import canonical_task
from .splitting import split_records
from .training import train, validate_config


def prepare_dataset(events_path: str | Path, targets_path: str | Path,
                    evidence_path: str | Path, config: dict[str, Any], out: str | Path | None,
                    *, training_as_of: int | None = None, audit_path: str | Path | None = None,
                    dry_run: bool = False) -> dict[str, Any]:
    config = validate_config(config)
    if training_as_of is not None:
        config["training_as_of"] = training_as_of
    task = config["task_id"]
    targets = [row for row in read_records(targets_path) if canonical_task(row.get("task_id", task)) == task]
    evidence = [row for row in read_records(evidence_path) if canonical_task(row.get("task_id", task)) == task]
    if not targets:
        raise ValueError("no_targets_for_preparation")
    if any(not row.get("sample_id") for row in targets) or len({row["sample_id"] for row in targets}) != len(targets):
        raise ValueError("missing_or_duplicate_target_sample_id")
    events = read_records(events_path)
    audits = ([Path(audit_path)] if audit_path else
              [Path(str(events_path) + ".audit.json"), Path(events_path).parent / "normalization_audit.json"])
    if audit_path and not Path(audit_path).is_file():
        raise FileNotFoundError(audit_path)
    for audit in audits:
        if audit.is_file() and load_json(audit).get("complete") is not True:
            targets = [dict(row, coverage={**row.get("coverage", {}), "complete": False}) for row in targets]
    options = {key: value for key, value in config.get("graph", {}).items()
               if key in {"builder_name", "window_days", "hops", "fanouts", "max_nodes", "max_edges", "seed"}}
    options.setdefault("seed", config["seed"])
    graphs = [build_graph_sample(row, events, **options) for row in targets]
    targets = [dict(row, data_eligible=graph_is_usable(graph), quality=graph["quality"])
               for row, graph in zip(targets, graphs)]
    supervision = reconcile_labels(evidence, targets, config["training_as_of"])
    splits, split_manifest = split_records(supervision, seed=config["seed"], mode=config["experiment_mode"],
                                           training_as_of=config["training_as_of"])
    # Exercise the same join/quality/leakage admission that the real trainer uses.
    plan = train(graphs, supervision, splits, config, "unused-dry-run", dry_run=True)
    report = {"status": "validated" if dry_run else "prepared", "task_id": task,
              "fitting_performed": False, "targets": len(targets),
              "quality_counts": dict(Counter(graph["quality"]["status"] for graph in graphs)),
              "label_counts": dict(Counter(row["label_status"] for row in supervision)),
              "excluded_reasons": dict(Counter(row["reason"] for row in supervision if not row["eligible"])),
              "split": split_manifest, "training_admission": plan["dataset"], "config": config,
              "inputs": {"events": sha256_file(events_path), "targets": sha256_file(targets_path),
                         "evidence": sha256_file(evidence_path)},
              "audits": {str(path.resolve()): sha256_file(path) for path in audits if path.is_file()}}
    if not dry_run:
        if out is None:
            raise ValueError("preparation_requires_output_directory")
        destination = Path(out)
        if destination.exists() and any(destination.iterdir()):
            raise FileExistsError("refusing_to_overwrite_prepared_dataset")
        destination.mkdir(parents=True, exist_ok=True)
        for name, records in (("targets", targets), ("graphs", graphs), ("supervision", supervision), ("splits", splits)):
            path = destination / f"{name}.jsonl"
            write_records(path, records)
        report["artifacts"] = {name: sha256_file(destination / f"{name}.jsonl") for name in ("targets", "graphs", "supervision", "splits")}
        save_json(destination / "dataset_manifest.json", report)
    return report
