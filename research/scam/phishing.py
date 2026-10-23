"""Phishing source-to-graph preparation; fitting belongs to the existing trainer."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import io
from pathlib import Path
from urllib.parse import urlsplit

from packages.collection import collect_dataset
from packages.provider_access import etherscan_key, REQUESTS_PER_SECOND, REQUESTS_PER_24H
from packages.io import atomic_bytes, load_json, read_records, save_json, sha256_file, write_records
from packages.sources.phishing import fetch_phishing_labels
from research.scam.cohorts import build_phishing_cohort
from packages.sources.historical import discover_background
from .preparation import prepare_dataset
from .training import validate_config

ETHEREUM_GENESIS_TIMESTAMP = 1438269988
STAGES = ("sources", "cohort", "collect", "prepare", "all")


def _background_directory(out, settings):
    reference = out / "background_ref.json"
    explicit = settings.get("background_snapshot")
    if reference.exists():
        saved = load_json(reference)
        directory = Path(saved["path"])
        if explicit and Path(explicit).resolve() != directory:
            raise ValueError("background_snapshot_changed")
        if sha256_file(directory / "manifest.json") != saved["manifest_sha256"]:
            raise ValueError("shared_background_manifest_changed")
        return directory
    if explicit:
        return Path(explicit).resolve()
    legacy = out / "background"
    return legacy if (legacy / "manifest.json").exists() else None


def _check_settings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower().replace("_", "") in {"apikey", "authorization", "token", "password"}:
                raise ValueError("credentials_belong_in_environment_variables_not_settings")
            if key == "endpoint":
                parts = urlsplit(str(item))
                if parts.query or parts.fragment or parts.username or parts.password:
                    raise ValueError("endpoint_must_not_contain_credentials_or_query_parameters")
            _check_settings(item)
    elif isinstance(value, list):
        for item in value:
            _check_settings(item)


def _freeze_json(path: Path, payload):
    if path.exists():
        if load_json(path) != payload:
            raise ValueError("snapshot_inputs_changed_use_a_new_snapshot")
    else:
        save_json(path, payload)


def _freeze_rows(path: Path, rows):
    if path.exists():
        if read_records(path) != rows:
            raise ValueError("snapshot_inputs_changed_use_a_new_snapshot")
    else:
        write_records(path, rows)


def _address_lists(out, targets, evidence):
    by_entity = {}
    for row in evidence:
        by_entity.setdefault(row["entity_id"], set()).add(row["source_file"])
    positive = sorted(row["target"] for row in targets if not row["background_selected"])
    background = sorted(row["target"] for row in targets if row["background_selected"])
    content = {"scam_addresses.txt": "\n".join(positive) + "\n",
               "background_addresses.txt": "\n".join(background) + "\n"}
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["address", "training_target", "label_status", "sources", "cutoff"])
    for row in sorted(targets, key=lambda value: (value["background_selected"], value["target"])):
        background_selected = row["background_selected"]
        writer.writerow([row["target"], 0 if background_selected else 1,
                         "unlabeled" if background_selected else "supported_positive",
                         ";".join(sorted(by_entity[row["target"]])), row["cutoff"]])
    content["address_labels.csv"] = stream.getvalue()
    hashes = {name: hashlib.sha256(value.encode()).hexdigest() for name, value in content.items()}
    for name, value in content.items():
        path = out / name
        if path.exists() and path.read_bytes() != value.encode():
            raise ValueError("address_list_changed_use_a_new_snapshot")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_bytes(path, value.encode())
    return hashes


def prepare_phishing(out: str | Path, config: dict, *, stage: str = "all",
                     settings: dict | None = None, positive_source: str = "forta",
                     per_class: int = 6000, source_as_of: int | None = None,
                     discover: bool = False, background_blocks: int = 384, progress: str = "auto",
                     allow_network: bool = False, dry_run: bool = False) -> dict:
    """Download labels, freeze historical roots, collect, and build train inputs.

    Static address labels are paired with full history up to their source
    snapshot, not with an arbitrary current 30-day interval. Node/edge/fanout
    budgets still apply. Source-file commit time is a collection upper bound,
    never a fabricated incident date. Public normal labels stay unlabeled.
    """
    if stage not in STAGES:
        raise ValueError("unsupported_phishing_preparation_stage")
    if not isinstance(per_class, int) or isinstance(per_class, bool) or per_class < 10:
        raise ValueError("per_class_must_be_at_least_10_for_80_10_10_split")
    config = validate_config(config)
    if config["task_id"] != "phishing" or config["experiment_mode"] != "known_positive_vs_unlabeled":
        raise ValueError("phishing_pipeline_requires_phishing_positive_unlabeled_config")
    if config.get("training_as_of") is not None:
        raise ValueError("public_static_labels_do_not_establish_historical_training_as_of")
    settings = copy.deepcopy(settings or {})
    _check_settings(settings)
    out = Path(out)
    paths = {name: str((out / name).resolve()) for name in ("sources", "background", "cohort", "collection", "prepared")}
    background = _background_directory(out, settings)
    paths["background"] = str(background.resolve()) if background is not None else None
    if dry_run:
        sources = fetch_phishing_labels(out / "sources", local_files=settings.get("label_files"),
                                        positive_source=positive_source, source_as_of=source_as_of, dry_run=True)
        actual_cohort = None
        roots = 2 * per_class
        if stage in {"collect", "prepare"}:
            frozen = load_json(out / "cohort" / "manifest.json")
            for name, expected in frozen["address_lists"].items():
                if sha256_file(out / "cohort" / name) != expected:
                    raise ValueError("address_list_checksum_mismatch")
            background = _background_directory(out, settings)
            planned_targets, planned_evidence, actual_cohort = build_phishing_cohort(
                out / "sources", per_class=per_class, seed=config["seed"], background_directory=background)
            if actual_cohort != frozen["cohort"] or read_records(out / "cohort/evidence.jsonl") != planned_evidence:
                raise ValueError("frozen_cohort_changed")
            saved = read_records(out / "cohort/targets.jsonl")
            if [{key: row[key] for key in planned_targets[0]} for row in saved] != planned_targets:
                raise ValueError("frozen_targets_changed")
            roots = len(saved)
        return {"status": "planned", "stage": stage, "paths": paths, "sources": sources,
                "cohort": actual_cohort,
                "per_class": per_class, "model": config["model"], "fitting_performed": False,
                "network_performed": False, "history": "genesis through frozen source cutoff",
                "background_discovery": {"enabled": discover, "blocks": background_blocks,
                                         "rpc_env": "ETHEREUM_RPC_URL", "etherscan_used": False},
                "etherscan_api_key_env": settings.get("collection", {}).get("api_key_env", "ETHERSCAN_API_KEY"),
                "provider_policy": {"rate_limit_rps": min(REQUESTS_PER_SECOND, max(0.01, float(settings.get("collection", {}).get("rate_limit_rps", REQUESTS_PER_SECOND)))),
                                    "rolling_24h_limit": REQUESTS_PER_24H,
                                    "credentials": "project local_secrets.py or explicit environment",
                                    "scope": "single serial collector; other programs are not counted"},
                "graph_budget": {key: config["graph"][key] for key in ("hops", "fanouts", "max_nodes", "max_edges")},
                "maximum_history_queries_before_pagination": roots * (1 + sum(config["graph"]["fanouts"][:-1])) * len(config["collection"]["actions"])}

    if stage in {"sources", "cohort", "all"}:
        source_manifest = fetch_phishing_labels(out / "sources", allow_network=allow_network,
            local_files=settings.get("label_files"), positive_source=positive_source, source_as_of=source_as_of,
            source_snapshot=settings.get("source_snapshot"))
    else:
        source_manifest = load_json(out / "sources" / "manifest.json")
        if source_manifest["positive_source"] != positive_source:
            raise ValueError("source_changed_use_the_frozen_positive_source")
    if stage == "sources":
        return {"status": "sources_ready", "sources": source_manifest, "paths": paths, "fitting_performed": False}
    background = _background_directory(out, settings)
    if discover:
        if stage not in {"cohort", "all"}:
            raise ValueError("background_discovery_belongs_to_the_cohort_stage")
        if background is None:
            if settings.get("shared_background", False):
                from .storage import background_path
                background = background_path(source_manifest["source_as_of"], config["seed"], background_blocks)
            else:
                background = out / "background"
        from .execution import snapshot_lock
        with snapshot_lock(background):
            discover_background(background, cutoff=source_manifest["source_as_of"], seed=config["seed"],
                            block_count=background_blocks, allow_network=allow_network, progress=progress)
    targets, evidence, cohort = build_phishing_cohort(out / "sources", per_class=per_class, seed=config["seed"],
                                                     background_directory=background)
    paths["background"] = str(background.resolve()) if background is not None else None
    if background is not None and background.resolve() != (out / "background").resolve():
        _freeze_json(out / "background_ref.json", {"path": str(background.resolve()),
                     "manifest_sha256": sha256_file(background / "manifest.json")})
    cutoff = cohort["cutoff"]
    if cutoff <= ETHEREUM_GENESIS_TIMESTAMP:
        raise ValueError("source_cutoff_must_follow_ethereum_genesis")
    effective = copy.deepcopy(config)
    effective["graph"]["window_days"] = math.ceil((cutoff - ETHEREUM_GENESIS_TIMESTAMP + 1) / 86400)
    effective["history_policy"] = "full_history_to_source_snapshot"
    effective["score_target"] = "phishing_risk_from_observed_transaction_graph"
    targets = [dict(target, observation_start=cutoff - effective["graph"]["window_days"] * 86400,
                    start_block=0,
                    source_snapshot=sha256_file(out / "sources" / "manifest.json")) for target in targets]
    collection_settings = dict(effective["collection"])
    collection_settings.update(settings.get("collection", {}))
    collection_settings.setdefault("max_history_rows", 100000)
    collection_settings.setdefault("max_raw_rows", 500000)
    # Collection and graph builder must use the identical sampling recipe.
    collection_settings["graph"] = effective["graph"]
    collection_settings["allow_network"] = allow_network
    public_settings = {key: value for key, value in collection_settings.items()
                       if key not in {"fixtures", "allow_network"}}
    contract = {"config": effective, "cohort": cohort, "collection": public_settings,
                "fixtures_sha256": hashlib.sha256(json.dumps(collection_settings.get("fixtures"), sort_keys=True).encode()).hexdigest()}
    contract["address_lists"] = _address_lists(out / "cohort", targets, evidence)
    _freeze_json(out / "cohort" / "manifest.json", contract)
    _freeze_rows(out / "cohort" / "targets.jsonl", targets)
    _freeze_rows(out / "cohort" / "evidence.jsonl", evidence)
    _freeze_json(out / "cohort" / "training_config.json", effective)
    if stage == "cohort":
        return {"status": "cohort_ready", "cohort": cohort, "paths": paths, "fitting_performed": False}
    if stage in {"collect", "all"}:
        cached_manifest = out / "collection" / "manifest.json"
        fully_cached = cached_manifest.exists() and load_json(cached_manifest).get("complete") is True
        if not fully_cached and not collection_settings.get("fixtures") and not collection_settings.get("fixture_dir"):
            if not allow_network:
                raise ValueError("transaction_collection_requires_allow_network_or_fixtures")
            key_env = collection_settings.get("api_key_env", "ETHERSCAN_API_KEY")
            if not etherscan_key(key_env):
                raise ValueError(f"set_{key_env}_in_local_secrets.py_or_environment_before_transaction_collection")
        collection_settings["progress"] = progress
        collected = collect_dataset(targets, out / "collection", collection_settings)
        if not collected["complete"]:
            row_budget_reached = any(
                item.get("failure") == "raw_row_budget_exhausted" or
                any(gap.get("reason") == "history_row_budget_exhausted"
                    for source in item.get("sources", []) for gap in source.get("gaps", []))
                for item in collected["coverage"])
            return {"status": "collection_incomplete", "collection": collected, "paths": paths,
                    "resume": ("row budget reached; use a new snapshot with fewer roots or explicitly larger row budgets"
                               if row_budget_reached else "repeat the same snapshot; verified requests are cached"),
                    "fitting_performed": False}
        if stage == "collect":
            return {"status": "collected", "collection": collected, "paths": paths, "fitting_performed": False}
    collected = load_json(out / "collection" / "manifest.json")
    if not collected.get("complete"):
        raise ValueError("complete_collection_required_before_preparation")
    prepared = out / "prepared"
    if (prepared / "dataset_manifest.json").exists():
        report = load_json(prepared / "dataset_manifest.json")
        inputs = {"events": sha256_file(out / "collection" / "events.jsonl"),
                  "targets": sha256_file(out / "collection" / "targets_with_coverage.jsonl"),
                  "evidence": sha256_file(out / "cohort" / "evidence.jsonl")}
        if report["inputs"] != inputs or report["config"] != effective:
            raise ValueError("prepared_dataset_inputs_changed")
        for name, digest in report["artifacts"].items():
            if sha256_file(prepared / f"{name}.jsonl") != digest:
                raise ValueError("prepared_dataset_checksum_mismatch")
    else:
        report = prepare_dataset(out / "collection" / "events.jsonl",
            out / "collection" / "targets_with_coverage.jsonl", out / "cohort" / "evidence.jsonl",
            effective, prepared, audit_path=out / "collection" / "normalization_audit.json", progress=progress)
    _freeze_json(prepared / "training_config.json", effective)
    return {"status": "prepared", "paths": paths, "dataset": report, "fitting_performed": False,
            "training_config": str((prepared / "training_config.json").resolve())}
