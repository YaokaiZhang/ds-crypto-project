"""Collect the frozen TokenScout cohort through the existing token graph engine."""
from collections import Counter
import math
from pathlib import Path

from packages.io import read_records, save_json, sha256_file, write_records
from packages.token import TOKEN_RECENT_SAMPLING, token_scope
from .honeypot_graphs import graph_root, process_graph_stage, _outcome
from .phishing import ETHEREUM_GENESIS_TIMESTAMP, _check_settings
from .rug_pull import _digest, _manifest, _verified
from .storage import checked_name

STAGES = ("plan", "collect", "build-graphs")


def plan_graphs(out, root, settings, *, limit=None, dry_run=False):
    out, root = Path(out), Path(root)
    source = out / "pools/verification_manifest.json"
    manifest = _verified(source)
    path = root / "plan.json"
    previous = _verified(path) if path.exists() else None
    if limit is None and previous:
        limit = previous["recipe"]["limit"]
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("graph_limit_must_be_positive")
    targets = read_records(out / "pools/verified_targets.jsonl")
    labels = read_records(out / "labels/verified_labels.jsonl")
    ids = [t["sample_id"] for t in targets]
    by_id = {r["sample_id"]: r for r in labels}
    if (not targets or len(set(ids)) != len(ids) or len(by_id) != len(labels)
            or set(ids) != set(by_id) or manifest["verified_tokens"] != len(targets)):
        raise ValueError("rug_pull_verified_cohort_mismatch")
    for target in targets:
        checked_name(target["sample_id"])
        label = by_id[target["sample_id"]]
        if (target.get("task_id") != "rug_pull" or target.get("chain_id") != 1
                or any(k in target for k in ("label", "mapped_label", "candidate_label"))
                or label.get("label") not in (0, 1)
                or label.get("token_address") != target["target"]
                or label.get("pool_addresses") != target["pools"]
                or label.get("cutoff") != target["cutoff"] or not label.get("pool_verified")):
            raise ValueError("rug_pull_verified_target_label_mismatch")
        token_scope(target)
    targets = targets[:limit] if limit else targets
    labels = [{**by_id[t["sample_id"]], "training_eligible": False} for t in targets]
    overrides = settings.get("graph_pipeline", {})
    if set(overrides) - {"rows_per_action", "pages_per_action", "max_nodes", "max_edges", "hops", "fanouts", "seed"}:
        raise ValueError("unsupported_rug_pull_graph_pipeline_setting")
    graph = {"builder_name": "token_v2", "sampling_mode": TOKEN_RECENT_SAMPLING,
        "window_days": math.ceil((max(t["cutoff"] for t in targets) - ETHEREUM_GENESIS_TIMESTAMP + 1) / 86400),
        "hops": 2, "fanouts": [32, 16], "max_nodes": 512, "max_edges": 4096,
        "seed": 20261020, "rows_per_action": 100, "pages_per_action": 3, **overrides}
    if (any(type(graph[k]) is not int or graph[k] < 1 for k in
            ("window_days", "max_nodes", "max_edges", "hops", "rows_per_action", "pages_per_action"))
            or graph["rows_per_action"] > 1000 or graph["pages_per_action"] > 10
            or not isinstance(graph["fanouts"], list) or len(graph["fanouts"]) != graph["hops"]
            or any(type(v) is not int or v < 1 for v in graph["fanouts"])):
        raise ValueError("invalid_rug_pull_graph_budget")
    recipe = {"version": "rug-pull-graph-plan-1", "task_id": "rug_pull", "limit": limit, "graph": graph,
        "source_hashes": {"verification_manifest": sha256_file(source),
            "verified_targets": sha256_file(out / "pools/verified_targets.jsonl"),
            "verified_labels": sha256_file(out / "labels/verified_labels.jsonl")},
        "candidate_targets_sha256": _digest(targets), "candidate_labels_sha256": _digest(labels)}
    result = {"status": "planned", "recipe": recipe, "target_count": len(targets),
        "label_counts": dict(Counter(str(r["label"]) for r in labels)), "training_eligible": 0}
    if previous and previous["recipe"] != recipe:
        raise ValueError("rug_pull_graph_inputs_changed_use_a_new_--graph-run")
    if dry_run:
        return result
    if not previous:
        write_records(root / "targets.jsonl", targets)
        write_records(root / "candidate_labels.jsonl", labels)
        previous = _manifest(path, [root / "targets.jsonl", root / "candidate_labels.jsonl"], **result)
    # Replay existing metadata verification, without an RPC call or new cutoff.
    # A partial plan publication is resumable; existing evidence is checked first.
    for target in targets:
        sample = root / "samples" / target["sample_id"]
        record = sample / "verify.json"
        outcome = _outcome(record, target)
        if outcome:
            if outcome["status"] != "verified":
                raise ValueError("rug_pull_preverified_target_outcome_mismatch")
            continue
        save_json(sample / "verified_target.json", target)
        _manifest(record, [sample / "verified_target.json"], sample_id=target["sample_id"],
            input_sha256=_digest(target), status="verified", verification_source_sha256=sha256_file(source))
    return previous


def run_graphs(out, *, stage, settings=None, graph_run="recent-v1", limit=None,
               allow_network=False, dry_run=False, drop_failed=True, progress="auto"):
    if stage not in (*STAGES, "graphs"):
        raise ValueError("unsupported_rug_pull_collection_stage")
    settings = dict(settings or {})
    for section in ("collection", "graph_pipeline"):
        _check_settings({k: v for k, v in settings.get(section, {}).items() if k not in {"transport", "fixtures"}})
    root = graph_root(out, graph_run)
    planned = plan_graphs(out, root, settings, limit=limit, dry_run=dry_run)
    stages = list(STAGES) if stage == "graphs" else [stage]
    if dry_run:
        return {"status": "planned", "stages": stages, "target_count": planned["target_count"],
            "label_counts": planned["label_counts"], "recipe": planned["recipe"],
            "network_performed": False, "training_started": False, "output": str(root)}
    if stage == "plan":
        return {"status": "graph_plan_prepared", "target_count": planned["target_count"],
            "label_counts": planned["label_counts"], "output": str(root)}
    for current in (STAGES[1:] if stage == "graphs" else [stage]):
        result = process_graph_stage(root, current, settings, allow_network=allow_network,
            drop_failed=drop_failed, progress=progress)
        if result["status"] == "collection_incomplete":
            break
    return {**result, "training_started": False}
