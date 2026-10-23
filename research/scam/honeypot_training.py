"""Prepare the user-adopted retrospective mixed-source Honeypot experiment."""
from collections import Counter
from pathlib import Path

from packages.io import load_json, read_records, save_json, sha256_file
from .honeypot import _digest, _verified
from .honeypot_graphs import _outcome
from .preparation import prepare_graph_dataset


def prepare_training(root, *, dry_run=False):
    root = Path(root)
    plan = _verified(root / "plan.json")
    manifest = load_json(root / "graph_manifest.json")
    if manifest["plan_sha256"] != sha256_file(root / "plan.json"):
        raise ValueError("honeypot_training_plan_checksum_mismatch")
    if manifest["graphs_sha256"] != sha256_file(root / "graphs.jsonl"):
        raise ValueError("honeypot_training_graphs_checksum_mismatch")
    source_targets = read_records(root / "targets.jsonl")
    labels = {r["sample_id"]: r for r in read_records(root / "candidate_labels.jsonl")}
    graphs, targets, evidence, excluded, outcomes = [], [], [], [], []
    for target in source_targets:
        sample = root / "samples" / target["sample_id"]
        # Every requested root must be published or explicitly excluded. Missing
        # or unfinished roots never become implicit preparation exclusions.
        result = None
        for stage, expected in (("verify", "verified"), ("collect", "collected"), ("build-graphs", "built")):
            result = _outcome(sample / f"{stage}.json", target)
            if result is None or result["status"] == "retryable_sample_failure":
                raise ValueError("honeypot_collection_unfinished_run_graphs_before_prepare_training")
            outcomes.append(result)
            if result["status"] == "excluded_sample_failure":
                excluded.append({"sample_id": target["sample_id"], "stage": stage, "reason": result["failure"]})
                break
            if result["status"] != expected:
                raise ValueError("unexpected_honeypot_collection_outcome")
        if result["status"] != "built":
            continue
        label = labels[target["sample_id"]]
        value = label["candidate_label"]
        if value not in (0, 1):
            raise ValueError("unknown_label_cannot_enter_honeypot_training")
        historical = target["source_cohort"] == "historical"
        graph = load_json(sample / "graph.json")
        scoped = load_json(sample / "collection/target.json")
        if graph["cutoff"] != target["cutoff"] or scoped["cutoff"] != target["cutoff"]:
            raise ValueError("honeypot_training_cutoff_mismatch")
        graphs.append(graph)
        targets.append({**scoped, "role": "token_contract", "source_cohort": target["source_cohort"],
                        "cutoff_basis": target["cutoff_basis"]})
        evidence.append({"task_id": "honeypot", "entity_id": target["target"], "role": "token_contract",
            "mapped_label": value, "label_status": "supported_positive" if value else "supported_negative",
            "pool_addresses": sorted(target["pools"]), "source_id": label["source"],
            "source_sha256": plan["recipe"]["source_hashes"][target["source_cohort"] + "_manifest_sha256"],
            "evidence_ref": label["evidence_ref"], "label_version": "honeypot-source-adopted-1",
            "audit_decision": "admitted", "audit_basis": "user_adopted_source_defined_retrospective_experiment",
            "independent_mechanism_validation": False,
            "valid_from": None if historical else label["checked_at"],
            "valid_to": None if historical else label["checked_at"],
            "label_available_at": None if historical else label["checked_at"]})
    aggregate = read_records(root / "graphs.jsonl")
    if _digest(aggregate) != _digest(graphs) or len(graphs) != manifest["graph_count"]:
        raise ValueError("honeypot_training_aggregate_graph_alignment_mismatch")
    config = load_json(Path(__file__).parent / "configs/honeypot.json")
    config.update(config_version="honeypot-recent-retrospective-1", graph=plan["recipe"]["graph"],
        seed=plan["recipe"]["graph"]["seed"], graph_view_version="token-v2-recent-1.0", training_as_of=None,
        negative_meaning="source-defined Trapdoor non-malicious or API-defined non-honeypot at capture; not universally benign",
        label_scope="source-defined retrospective Trapdoor plus captured Honeypot.is selected-pair detections",
        execution_status="prepared_not_trained", temporal_protocol="retrospective_source_anchors_not_incident_or_label_known_at")
    inputs = {"plan": sha256_file(root / "plan.json"), "graph_manifest": sha256_file(root / "graph_manifest.json"),
              "graphs": sha256_file(root / "graphs.jsonl"), "sample_outcomes": _digest(outcomes)}
    selection = {"requested": len(source_targets), "published": len(graphs), "excluded": excluded,
        "source_class_counts": dict(Counter(f"{t['source_cohort']}:{e['mapped_label']}" for t,e in zip(targets,evidence))),
        "label_policy": "user_adopted_source_labels_not_independent_ground_truth_validation",
        "temporal_limit": "historical validity and label availability remain unknown; no early-warning claim",
        "source_time_confounding": "mixed sources have different years and class proportions; report source support",
        "split_policy": "class-stratified 90/10 train/validation; all token and selected-pool groups stay together"}
    destination = root / "prepared"
    if (destination / "dataset_manifest.json").exists():
        frozen = load_json(destination / "dataset_manifest.json")
        if frozen["inputs"] != inputs or frozen["selection"] != selection:
            raise ValueError("honeypot_prepared_inputs_changed_use_new_graph_run")
        for name, digest in frozen["artifacts"].items():
            if sha256_file(destination / f"{name}.jsonl") != digest:
                raise ValueError("honeypot_prepared_artifact_checksum_mismatch")
        config_path = destination / "training_config.json"
        if not config_path.exists() and not dry_run:
            save_json(config_path, frozen["config"])
        if config_path.exists() and load_json(config_path) != frozen["config"]:
            raise ValueError("honeypot_prepared_training_config_changed")
        return frozen
    report = prepare_graph_dataset(graphs, targets, evidence, config, destination,
        inputs=inputs, selection=selection, dry_run=dry_run)
    if not dry_run:
        save_json(destination / "training_config.json", report["config"])
    return report
