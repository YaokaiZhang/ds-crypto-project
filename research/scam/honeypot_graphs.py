"""Source-specific cutoff plans and resumable Honeypot token graphs, no fitting."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil
import threading
import math
import json
from pathlib import Path
import sys
import time
import uuid

from packages.collection import CollectionError, EtherscanClient, _safe_error, transient_network_error
from packages.graph import build_graph_sample, graph_is_usable, graph_recipe
from packages.io import load_json, read_records, save_json, sha256_file, write_records
from packages.token import TOKEN_RECENT_SAMPLING
from packages.token_recent import collect_token_recent
from packages.token_sources import SnapshotClient, verify_token_targets
from packages.provider_access import SerialRequestBudget, REQUESTS_PER_SECOND
from packages.progress import NestedSampleProgress
from packages.observations import ObservationStore, verify_observation
from .honeypot import _digest, _freeze, _manifest, _verified
from .phishing import ETHEREUM_GENESIS_TIMESTAMP
from .storage import checked_name, SHARED_ETHERSCAN_CACHE, SHARED_OBSERVATIONS

GRAPH_STAGES = ("plan", "verify", "collect", "build-graphs")


def parse_time(value):
    if isinstance(value, bool):
        raise ValueError("historical_cutoff_requires_unix_or_timezone_aware_ISO")
    try:
        stamp = int(value)
    except (ValueError, TypeError):
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("historical_cutoff_requires_timezone")
        stamp = int(date.timestamp())
    if stamp <= ETHEREUM_GENESIS_TIMESTAMP:
        raise ValueError("historical_cutoff_must_follow_ethereum_genesis")
    return stamp


def _fatal(error):
    if isinstance(error, json.JSONDecodeError):
        return True
    text = str(error).lower()
    return any(word in text for word in ("checksum", "inputs_changed", "invalid_cached", "snapshot_cache", "cached_provider",
        "missing_ethereum_rpc", "missing_etherscan", "network_disabled", "401", "403", "429", "quota", "rate limit",
        "request_budget", "api key", "api-key", "unauthor", "forbidden", "nodename nor servname", "name resolution",
        "missing trie node", "historical state", "archive node", "method not found", "invalid params", "invalid argument",
        "ethereum_mainnet_only", "missing_rpc_result", "cutoff_block_header_mismatch", "-32601", "-32602",
        "compute unit", "capacity exceeded", "throughput", "too many requests", "payment required"))


def graph_root(out, run):
    return Path(out) / "graph_runs" / checked_name(run)


def plan_graphs(out, root, settings, *, cohort=None, historical_cutoff=None, limit=None, dry_run=False):
    path = root / "plan.json"
    previous = _verified(path) if path.exists() else None
    old = previous["recipe"] if previous else {}
    selected = cohort or old.get("cohort", settings.get("graph_selection", {}).get("cohort", "contemporary"))
    if selected not in {"contemporary", "historical", "both"}:
        raise ValueError("unsupported_honeypot_graph_cohort")
    historical = historical_cutoff if historical_cutoff is not None else old.get("historical_cutoff", settings.get("graph_selection", {}).get("historical_cutoff"))
    historical = parse_time(historical) if historical is not None else None
    if selected in {"historical", "both"} and historical is None:
        raise ValueError("Trapdoor_has_no_label_timestamp_supply_--historical-cutoff_as_explicit_retrospective_anchor")
    limit = limit if limit is not None else old.get("limit")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("graph_limit_must_be_positive")
    rows, labels, skipped, evidence = [], [], [], {}
    if selected in {"contemporary", "both"}:
        _verified(Path(out) / "contemporary/manifest.json")
        evidence["contemporary_manifest_sha256"] = sha256_file(Path(out) / "contemporary/manifest.json")
        outcomes = {r["sample_id"]: r for r in read_records(Path(out) / "contemporary/labels.jsonl")}
        for target in read_records(Path(out) / "discovery/targets.jsonl"):
            row = outcomes[target["sample_id"]]
            if row.get("candidate_label") not in (0, 1) or row.get("label_status") == "invalid":
                skipped.append({"sample_id": row["sample_id"], "reason": "API_unknown_invalid_or_query_failure"})
                continue
            cutoff = parse_time(row["checked_at"])
            rows.append({"sample_id": target["sample_id"], "task_id": "honeypot", "chain_id": 1,
                         "target": target["target"], "pools": target["pools"], "cutoff": cutoff,
                         "source_cohort": "contemporary", "cutoff_basis": "frozen_API_capture_time",
                         "source_snapshot": row["evidence_ref"]})
            labels.append({**row, "graph_cutoff": cutoff, "training_eligible": False})
    if selected in {"historical", "both"}:
        _verified(Path(out) / "historical/manifest.json")
        evidence["historical_manifest_sha256"] = sha256_file(Path(out) / "historical/manifest.json")
        for row in read_records(Path(out) / "historical/labels.jsonl"):
            if row.get("candidate_label") not in (0, 1):
                skipped.append({"sample_id": row["sample_id"], "reason": "historical_source_conflict"})
                continue
            rows.append({"sample_id": row["sample_id"], "task_id": "honeypot", "chain_id": 1,
                         "target": row["token_address"], "pools": [row["pair_address"]], "cutoff": historical,
                         "source_cohort": "historical", "cutoff_basis": "explicit_retrospective_observation_anchor_not_incident_time",
                         "source_snapshot": row["evidence_ref"]})
            labels.append({**row, "graph_cutoff": historical, "training_eligible": False})
    if len({r["sample_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate_honeypot_graph_sample_id")
    if limit is not None:
        rows, labels = rows[:limit], labels[:limit]
    if not rows:
        raise ValueError("no_honeypot_graph_targets_with_usable_source_labels")
    overrides = settings.get("graph_pipeline", {})
    if set(overrides) - {"rows_per_action", "pages_per_action", "max_nodes", "max_edges", "hops", "fanouts", "seed"}:
        raise ValueError("unsupported_honeypot_graph_pipeline_setting")
    graph = {"builder_name": "token_v2", "sampling_mode": TOKEN_RECENT_SAMPLING,
             "window_days": math.ceil((max(r["cutoff"] for r in rows) - ETHEREUM_GENESIS_TIMESTAMP + 1) / 86400),
             "hops": 2, "fanouts": [32, 16], "max_nodes": 512, "max_edges": 4096, "seed": 20261020,
             "rows_per_action": 100, "pages_per_action": 3, **overrides}
    if (any(type(graph[k]) is not int or graph[k] < 1 for k in ("max_nodes", "max_edges", "hops", "rows_per_action", "pages_per_action"))
            or not 1 <= graph["rows_per_action"] <= 1000 or not 1 <= graph["pages_per_action"] <= 10
            or len(graph["fanouts"]) != graph["hops"] or any(type(v) is not int or v < 1 for v in graph["fanouts"])):
        raise ValueError("invalid_honeypot_graph_budget")
    recipe = {"version": "honeypot-graph-plan-1", "cohort": selected, "historical_cutoff": historical,
              "limit": limit, "graph": graph, "source_hashes": evidence,
              "candidate_targets_sha256": _digest(rows), "candidate_labels_sha256": _digest(labels)}
    if previous:
        if old != recipe:
            raise ValueError("honeypot_graph_inputs_changed_use_a_new_--graph-run")
        return previous
    result = {"status": "planned", "recipe": recipe, "target_count": len(rows),
              "unique_tokens": len({r["target"] for r in rows}), "skipped_count": len(skipped),
              "source_cohort_counts": dict(Counter(r["source_cohort"] for r in rows)), "training_eligible": 0}
    if dry_run:
        return result
    write_records(root / "targets.jsonl", rows)
    write_records(root / "candidate_labels.jsonl", labels)
    write_records(root / "excluded_labels.jsonl", skipped)
    return _manifest(path, [root / "targets.jsonl", root / "candidate_labels.jsonl", root / "excluded_labels.jsonl"], **result)


def _outcome(path, target):
    if not path.exists():
        return None
    result = load_json(path)
    if result["input_sha256"] != _digest(target):
        raise ValueError("honeypot_graph_sample_inputs_changed")
    if result.get("artifacts"):
        _verified(path)
        if result.get("shared_observation"):
            ref = result["shared_observation"]
            verify_observation(ref["path"], ref)
    elif result.get("outcome_sha256") != _digest({k: v for k, v in result.items() if k != "outcome_sha256"}):
        raise ValueError("honeypot_graph_failure_checksum_mismatch")
    return result


def _failure(path, target, error, phase, drop):
    if transient_network_error(error):
        raise CollectionError("transient_provider_network_failure: " + str(error)) from error
    if _fatal(error):
        raise CollectionError(str(error))
    row = {"sample_id": target["sample_id"], "input_sha256": _digest(target), "phase": phase,
           "status": "excluded_sample_failure" if drop else "retryable_sample_failure",
           "failure": _safe_error(error, [])}
    row["outcome_sha256"] = _digest(row)
    save_json(path, row)
    return row


def process_graph_stage(root, stage, settings, *, allow_network, drop_failed, progress):
    plan = _verified(root / "plan.json")
    targets = read_records(root / "targets.jsonl")
    graph = plan["recipe"]["graph"]
    collection = {**settings.get("collection", {}), "allow_network": allow_network}
    workers = collection.get("sample_workers", 4)
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("sample_workers_must_be_between_1_and_8")
    budget = SerialRequestBudget(rate=min(REQUESTS_PER_SECOND, float(collection.get("rate_limit_rps", REQUESTS_PER_SECOND))))
    stop = threading.Event()
    collection.update(request_budget=budget, cancel_event=stop)
    compact = collection.get("retention", "compact_events_and_graph_delete_raw") == "compact_events_and_graph_delete_raw"
    if compact:
        # Only private per-sample raw scratch may be removed after publication.
        collection.pop("shared_cache_dir", None)
    else:
        collection.setdefault("shared_cache_dir", str(SHARED_ETHERSCAN_CACHE))
    verification = {"max_requests": 100000, "rate_limit_rps": 3, **settings.get("verification", {}),
                    "allow_network": allow_network, "rpc_cache_dir": str(root / "rpc_cache"), "cancel_event": stop}
    rpc = SnapshotClient(root / "rpc_cache", verification)
    verification["_client"] = rpc
    store = ObservationStore(settings.get("observation_root", SHARED_OBSERVATIONS),
        {**collection, "actions": ["getLogs", "txlist", "txlistinternal"]})
    lock = threading.Lock()
    active, finished = {}, {}
    last_update = [0.0]
    cutoff_lock, cutoff_blocks = threading.Lock(), {}
    stage_status = ["running"]

    def report(force=False):
        # Caller holds the progress lock, so concurrent roots cannot race writes.
        now = time.monotonic()
        if not force and now - last_update[0] < 10:
            return
        last_update[0] = now
        counts = dict(Counter(r["status"] for r in finished.values()))
        save_json(root / "progress.json", {"stage": stage, "processed": len(finished), "total": len(targets),
            "status_counts": counts, "active_samples": dict(active), "sample_workers": workers,
            "rate_limit_rps": budget.rate, "stage_status": stage_status[0],
            "quota_file": str(budget.path.resolve()),
            "updated_at": datetime.now().astimezone().isoformat(),
            "sample_progress": display.snapshot()})

    def cutoff_block(target, sample):
        # One indexed lookup for every distinct timestamp; most Trapdoor roots share one.
        with cutoff_lock:
            cutoff = target["cutoff"]
            if cutoff not in cutoff_blocks:
                cutoff_blocks[cutoff] = EtherscanClient(sample / "blocks", collection).block_by_time(cutoff, "before")
            return cutoff_blocks[cutoff]

    def cleanup(sample, outcome):
        if compact and outcome.get("shared_observation"):
            ref = outcome["shared_observation"]
            verify_observation(ref["path"], ref)
            # Manifests already pin the shared replay events. Never remove shared caches.
            shutil.rmtree(sample / "collection/raw_requests", ignore_errors=True)
            (sample / "collection/events.jsonl.gz").unlink(missing_ok=True)

    # Resume counters immediately and avoid submitting thousands of cached roots.
    # Recover only legacy transport/cancellation exclusions before publication.
    recovered = []
    for target in targets:
        sample = root / "samples" / target["sample_id"]
        record = sample / f"{stage}.json"
        result = _outcome(record, target)
        if (result and result["status"] == "excluded_sample_failure"
                and transient_network_error(result.get("failure", ""))
                and not (root / "graph_manifest.json").exists() and not (root / "prepared").exists()):
            archived = sample / "attempts" / f"{stage}-transport-recovery-{uuid.uuid4().hex}.json"
            archived.parent.mkdir(parents=True, exist_ok=True)
            digest = sha256_file(record)
            record.replace(archived)
            recovered.append({"sample_id": target["sample_id"], "previous_sha256": digest,
                              "archived": str(archived.relative_to(root)), "reason": result["failure"]})
            result = None
        if result and result["status"] != "retryable_sample_failure":
            cleanup(sample, result)
            finished[target["sample_id"]] = result
    if recovered:
        save_json(root / "recovery" / f"transport-{uuid.uuid4().hex}.json", {
            "policy": "reopen_prepublication_legacy_transport_exclusions_preserve_originals",
            "stage": stage, "records": recovered})
    display = NestedSampleProgress(len(targets), len(finished), mode=progress,
        initial_failed=sum(r["status"] == "excluded_sample_failure" for r in finished.values()))
    budget.notify = display.message
    with lock:
        report(force=True)

    def process(target):
        if stop.is_set():
            raise InterruptedError("honeypot_stage_cancelled")
        sample = root / "samples" / target["sample_id"]
        record = sample / f"{stage}.json"
        result = _outcome(record, target)
        if result and result["status"] != "retryable_sample_failure":
            cleanup(sample, result)
            return result
        if result:
            archived = sample / "attempts" / f"{stage}-{uuid.uuid4().hex}.json"
            archived.parent.mkdir(parents=True, exist_ok=True)
            record.replace(archived)
        with lock:
            display.start(target["sample_id"], target["target"])
            active[target["sample_id"]] = {"sample_id": target["sample_id"], "target": target["target"],
                "phase": stage, "completed_queries": 0, "total_queries": 0, "http_attempts": 0, "cache_hits": 0}
        def observe(state):
            with lock:
                current = active[target["sample_id"]]
                phase = state.get("phase", "")
                if phase == "query":
                    current["total_queries"] += 1
                elif phase in {"received", "cache"}:
                    current["completed_queries"] += 1
                    current["total_queries"] = max(current["total_queries"], current["completed_queries"])
                elif phase not in {"request", "error"}:
                    current["phase"] = phase
                if state.get("query"):
                    current.update(query=state["query"], action=state["query"].get("action"))
                for key in ("http_attempts", "cache_hits", "requests"):
                    if key in state:
                        current[key] = state[key]
                display.observe(dict(current))
                report()
        try:
            if stage == "verify":
                bounded = dict(target, cutoff_block=cutoff_block(target, sample))
                verify_token_targets([bounded], sample / "verification", {**verification, "on_progress": observe})
                verified = read_records(sample / "verification/verified_targets.jsonl")[0]
                save_json(sample / "verified_target.json", verified)
                return _manifest(record, [sample / "verified_target.json"], sample_id=target["sample_id"],
                    input_sha256=_digest(target), status="verified")
            previous = _outcome(sample / "verify.json", target)
            if not previous:
                raise ValueError("run_verify_stage_before_collection")
            if previous["status"] != "verified":
                return previous
            verified = load_json(sample / "verified_target.json")
            if stage == "collect":
                spec = store.specification(verified, graph, verified["cutoff_block"])
                spec.update(version="bounded-token-observation-1", selected_pools=sorted(verified["pools"]),
                    cutoff_block_hash=verified.get("cutoff_block_hash"),
                    token_decimals=verified["token_metadata"]["decimals"])
                display.phase(target["sample_id"], "shared cache")
                shared = store.read(spec)
                if shared is None:
                    collect_token_recent(verified, sample / "collection", graph,
                                         {**collection, "on_progress": observe})
                    events = read_records(sample / "collection/events.jsonl.gz")
                    coverage = load_json(sample / "collection/coverage.json")
                    audit = load_json(sample / "collection/normalization_audit.json")
                    shared = store.publish(spec, events, coverage, audit)
                display.phase(target["sample_id"], "publish")
                events, coverage, audit, reference = shared
                directory = sample / "collection"
                save_json(directory / "target.json", {**verified, "coverage": coverage})
                save_json(directory / "coverage.json", coverage)
                save_json(directory / "normalization_audit.json", audit)
                names = ["target.json", "coverage.json", "normalization_audit.json"]
                if reference:
                    save_json(directory / "observation_ref.json", reference)
                    names.append("observation_ref.json")
                else:
                    write_records(directory / "events.jsonl.gz", events)
                    names.append("events.jsonl.gz")
                result = _manifest(record, [directory / name for name in names],
                    sample_id=target["sample_id"], input_sha256=_digest(target), status="collected",
                    shared_observation=reference, event_count=len(events), stop_reason=coverage["stop_reason"])
                cleanup(sample, result)
                return result
            previous = _outcome(sample / "collect.json", target)
            if not previous:
                raise ValueError("run_collect_stage_before_build-graphs")
            if previous["status"] != "collected":
                return previous
            scoped = load_json(sample / "collection/target.json")
            reference = previous.get("shared_observation")
            if reference:
                _, events_path = verify_observation(reference["path"], reference)
            else:
                events_path = sample / "collection/events.jsonl.gz"
            display.phase(target["sample_id"], "graph")
            built = build_graph_sample(scoped, read_records(events_path), **graph)
            if not graph_is_usable(built):
                raise ValueError("honeypot_graph_quality_failed")
            graph_recipe(built)
            save_json(sample / "graph.json", built)
            return _manifest(record, [sample / "graph.json"], sample_id=target["sample_id"],
                input_sha256=_digest(target), status="built", nodes=len(built["node_refs"]), edges=len(built["edge_index"][0]))
        except (CollectionError, ValueError, TypeError, KeyError) as error:
            if "run_verify_stage" in str(error) or "run_collect_stage" in str(error):
                raise
            return _failure(record, target, error, stage, drop_failed)
        finally:
            with lock:
                active.pop(target["sample_id"], None)

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="honeypot-sample")
    futures = {}
    try:
        futures = {pool.submit(process, target): target["sample_id"] for target in targets
                   if target["sample_id"] not in finished}
        for future in as_completed(futures):
            result = future.result()
            with lock:
                finished[futures[future]] = result
                display.finish(futures[future], success=result["status"] != "excluded_sample_failure",
                               excluded=result["status"] == "excluded_sample_failure")
                report(force=len(finished) == len(targets))
    except BaseException as error:
        stage_status[0] = "interrupted" if isinstance(error, KeyboardInterrupt) else "error"
        stop.set()
        budget.cancel()
        for future in futures:
            future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        # Other in-flight roots may have published before cancellation. Include
        # them in terminal status without converting cancellations into failures.
        with lock:
            for future, sample_id in futures.items():
                if sample_id not in finished and future.done() and not future.cancelled() and future.exception() is None:
                    result = future.result()
                    finished[sample_id] = result
                    display.finish(sample_id, success=result["status"] != "excluded_sample_failure",
                                   excluded=result["status"] == "excluded_sample_failure")
            for state in display.snapshot():
                display.discard(state["sample_id"])
            active.clear()
            if stage_status[0] == "running":
                stage_status[0] = "complete"
            report(force=True)
        display.close()
    index = [finished[t["sample_id"]] for t in targets]
    pending = [r for r in index if r["status"] == "retryable_sample_failure"]
    write_records(root / f"{stage}_outcomes.jsonl", index)
    built_files = []
    if stage == "build-graphs":
        built_files = [root / "samples" / r["sample_id"] / "graph.json" for r in index if r["status"] == "built"]
        write_records(root / "graphs.jsonl", [load_json(p) for p in built_files])
        task_id = plan["recipe"].get("task_id", "honeypot")
        save_json(root / "graph_manifest.json", {"version": f"{task_id}-graphs-1", "plan_sha256": sha256_file(root / "plan.json"),
            "graphs_sha256": sha256_file(root / "graphs.jsonl"), "graph_count": len(built_files),
            "target_count": len(targets), "status_counts": dict(Counter(r["status"] for r in index)),
            "graph_view_version": "token-v2-recent-1.0", "training_performed": False,
            "supervision_admitted": False, "source_cohorts_kept_in_plan": True})
        if not built_files:
            raise ValueError("no_usable_honeypot_graphs_inspect_recorded_outcomes")
    return {"status": "collection_incomplete" if pending else "graphs_" + stage,
        "target_count": len(targets), "status_counts": dict(Counter(r["status"] for r in index)),
        "graph_count": len(built_files) if stage == "build-graphs" else None,
        "collection": {"coverage": pending}, "output": str(root)}


def run_graphs(out, *, stage, settings=None, graph_run="recent-v1", cohort=None,
               historical_cutoff=None, limit=None, allow_network=False, dry_run=False,
               drop_failed=True, progress="auto"):
    settings = dict(settings or {})
    root = graph_root(out, graph_run)
    from .phishing import _check_settings
    for section in ("collection", "verification", "graph_pipeline"):
        _check_settings({k: v for k, v in settings.get(section, {}).items() if k not in {"transport", "fixtures"}})
    if dry_run:
        planned = plan_graphs(out, root, settings, cohort=cohort, historical_cutoff=historical_cutoff,
                              limit=limit, dry_run=True)
        return {"status": "planned", "stages": list(GRAPH_STAGES) if stage == "graphs" else [stage],
                "network_performed": False, "target_count": planned["target_count"], "graph_run": graph_run,
                "recipe": planned["recipe"], "output": str(root)}
    plan_graphs(out, root, settings, cohort=cohort, historical_cutoff=historical_cutoff, limit=limit)
    if stage == "plan":
        return {"status": "graph_plan_prepared", "output": str(root)}
    stages = GRAPH_STAGES[1:] if stage == "graphs" else [stage]
    result = {}
    for current in stages:
        result = process_graph_stage(root, current, settings, allow_network=allow_network,
                                     drop_failed=drop_failed, progress=progress)
        if result["status"] == "collection_incomplete":
            break
    return result
