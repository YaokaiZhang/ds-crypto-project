"""Prepare the adopted TokenScout retrospective benchmark without fitting."""
from collections import Counter
from pathlib import Path

from packages.io import load_json, read_records, save_json, sha256_file
from packages.labeling import TOKENSCOUT_RETROSPECTIVE_POLICY
from .honeypot_graphs import _outcome
from .preparation import prepare_graph_dataset
from .rug_pull import _digest, _verified


def prepare_training(root, *, dry_run=False):
    root = Path(root)
    snapshot = root.parent.parent
    plan = _verified(root / "plan.json")
    if plan["recipe"].get("task_id") != "rug_pull":
        raise ValueError("rug_pull_training_requires_rug_pull_plan")
    sources = {"verification_manifest": "pools/verification_manifest.json",
        "verified_targets": "pools/verified_targets.jsonl", "verified_labels": "labels/verified_labels.jsonl"}
    _verified(snapshot / sources["verification_manifest"])
    for name, relative in sources.items():
        if sha256_file(snapshot / relative) != plan["recipe"]["source_hashes"][name]:
            raise ValueError("rug_pull_training_source_checksum_mismatch")
    manifest = load_json(root / "graph_manifest.json")
    if (manifest["plan_sha256"] != sha256_file(root / "plan.json")
            or manifest["graphs_sha256"] != sha256_file(root / "graphs.jsonl")):
        raise ValueError("rug_pull_training_graph_checksum_mismatch")
    original_targets = read_records(root / "targets.jsonl")
    labels = {r["sample_id"]: r for r in read_records(root / "candidate_labels.jsonl")}
    graphs, targets, evidence, excluded, outcomes = [], [], [], [], []
    for target in original_targets:
        sample = root / "samples" / target["sample_id"]
        result = None
        for stage, expected in (("verify", "verified"), ("collect", "collected"), ("build-graphs", "built")):
            result = _outcome(sample / f"{stage}.json", target)
            if result is None or result["status"] == "retryable_sample_failure":
                raise ValueError("rug_pull_collection_unfinished_run_build-graphs_before_prepare_training")
            outcomes.append(result)
            if result["status"] == "excluded_sample_failure":
                excluded.append({"sample_id": target["sample_id"], "stage": stage, "reason": result["failure"]})
                break
            if result["status"] != expected:
                raise ValueError("unexpected_rug_pull_collection_outcome")
        if result["status"] != "built":
            continue
        label = labels[target["sample_id"]]
        value = label["label"]
        if (label.get("source") != "tokenscout" or value not in (0, 1)
                or label.get("source_label") != ("rugpull" if value else "truthworthy")
                or label.get("token_address") != target["target"]
                or label.get("pool_addresses") != target["pools"] or label.get("cutoff") != target["cutoff"]
                or not label.get("pool_verified")
                or label.get("label_policy") != "tokenscout-source-defined-retrospective-1"):
            raise ValueError("invalid_tokenscout_training_label")
        graph = load_json(sample / "graph.json")
        scoped = load_json(sample / "collection/target.json")
        if graph["cutoff"] != target["cutoff"] or scoped["cutoff"] != target["cutoff"]:
            raise ValueError("rug_pull_training_cutoff_mismatch")
        graphs.append(graph)
        targets.append({**scoped, "role": "token_contract", "source_cohort": "tokenscout",
            "cutoff_basis": "source_coverage_end_not_incident_or_label_known_at"})
        evidence.append({"task_id": "rug_pull", "entity_id": target["target"], "role": "token_contract",
            "mapped_label": value, "label_status": "supported_positive" if value else "supported_negative",
            "source_id": "tokenscout", "source_label": label["source_label"],
            "source_sha256": plan["recipe"]["source_hashes"]["verified_labels"],
            "evidence_ref": label.get("evidence_ref") or str((snapshot / sources["verified_labels"]).resolve()),
            "pool_addresses": sorted(target["pools"]), "label_version": TOKENSCOUT_RETROSPECTIVE_POLICY,
            "audit_decision": "admitted", "audit_basis": "user_adopted_source_defined_retrospective_experiment",
            "independent_mechanism_validation": False, "valid_from": None, "valid_to": None,
            "label_available_at": None, "incident_onset": None, "incident_tx": None, "controller_evidence_ref": None})
    aggregate = read_records(root / "graphs.jsonl")
    if _digest(aggregate) != _digest(graphs) or len(graphs) != manifest["graph_count"]:
        raise ValueError("rug_pull_training_aggregate_graph_alignment_mismatch")
    config = load_json(Path(__file__).parent / "configs/rug_pull.json")
    config.update(config_version="tokenscout-rug-pull-recent-retrospective-1", graph=plan["recipe"]["graph"],
        seed=plan["recipe"]["graph"]["seed"], graph_view_version="token-v2-recent-1.0", training_as_of=None,
        source_label_policy=TOKENSCOUT_RETROSPECTIVE_POLICY,
        negative_meaning="TokenScout truthworthy source class; not independently verified universally benign",
        label_scope="TokenScout source-defined rugpull versus truthworthy; no independent incident validation",
        execution_status="prepared_not_trained", temporal_protocol="source_coverage_anchor_not_incident_or_label_known_at")
    inputs = {"plan": sha256_file(root / "plan.json"), "graph_manifest": sha256_file(root / "graph_manifest.json"),
        "graphs": sha256_file(root / "graphs.jsonl"), "sample_outcomes": _digest(outcomes),
        "source_hashes": plan["recipe"]["source_hashes"], "admission_evidence": _digest(evidence)}
    selection = {"requested": len(original_targets), "published": len(graphs), "excluded": excluded,
        "source_class_counts": dict(Counter(str(e["mapped_label"]) for e in evidence)),
        "label_policy": TOKENSCOUT_RETROSPECTIVE_POLICY, "independent_mechanism_validation": False,
        "temporal_limit": "unknown incident, validity and label availability times; no early-warning claim",
        "split_policy": "class-stratified 90/10 train/validation; token and selected-pool groups stay together"}
    destination = root / "prepared"
    if (destination / "dataset_manifest.json").exists():
        frozen = load_json(destination / "dataset_manifest.json")
        if frozen["inputs"] != inputs or frozen["selection"] != selection:
            raise ValueError("rug_pull_prepared_inputs_changed_use_new_graph_run")
        for name, digest in frozen["artifacts"].items():
            if sha256_file(destination / f"{name}.jsonl") != digest:
                raise ValueError("rug_pull_prepared_artifact_checksum_mismatch")
        config_path = destination / "training_config.json"
        if config_path.exists() and load_json(config_path) != frozen["config"]:
            raise ValueError("rug_pull_prepared_training_config_changed")
        if not config_path.exists() and not dry_run:
            save_json(config_path, frozen["config"])
        return frozen
    report = prepare_graph_dataset(graphs, targets, evidence, config, destination,
        inputs=inputs, selection=selection, dry_run=dry_run)
    if not dry_run:
        save_json(destination / "training_config.json", report["config"])
    return report
