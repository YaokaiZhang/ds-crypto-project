"""Reference-balanced Phishing cohorts and restartable per-root graph production."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
import threading
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import tempfile
import time

from packages.collection import CollectionError, _safe_error, _now
from packages.collection_recent import RecentHistoryCollector
from packages.graph import RECENT_SAMPLING, build_graph_sample, graph_is_usable, validate_graph_sample
from packages.io import load_json, read_records, save_json, sha256_file, write_records
from packages.progress import NestedSampleProgress
from packages.provider_access import etherscan_key, REQUESTS_PER_SECOND, REQUESTS_PER_24H
from packages.sources.phishing import fetch_phishing_labels
from packages.sources.address_pools import freeze_address_pool, load_address_pool
from packages.observations import ObservationStore, verify_observation
from .cohorts import build_reference_phishing_cohort
from .phishing import ETHEREUM_GENESIS_TIMESTAMP, STAGES, _check_settings, _freeze_json, _freeze_rows, _address_lists
from .preparation import prepare_graph_dataset
from .training import validate_config
from .storage import SHARED_ADDRESS_POOLS, SHARED_OBSERVATIONS
from .failure_exclusions import sample_key as _sample_key, load_exclusions, freeze_exclusions, resolve_report


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _public_settings(settings):
    return {k: v for k, v in settings.items() if k not in {"fixtures", "transport", "allow_network", "progress"}}


def _verify_sample(directory, expected):
    manifest = load_json(directory / "manifest.json")
    if manifest["input_sha256"] != expected:
        raise ValueError("sample_inputs_changed_use_a_new_snapshot")
    for name, digest in manifest["artifacts"].items():
        if sha256_file(directory / name) != digest:
            raise ValueError("sample_artifact_checksum_mismatch")
    if manifest.get("event_storage") == "shared_observation":
        reference = manifest["shared_observation"]
        verify_observation(reference["path"], reference)
    validate_graph_sample(load_json(directory / "graph.json"))
    return manifest


def _clean_work(work):
    # Only scratch directories owned by this pipeline may be removed. Published
    # samples, old snapshots and shared provider caches are never cleanup targets.
    if work.parent.name != ".work":
        raise ValueError("invalid_sample_cleanup_path")
    if work.exists():
        shutil.rmtree(work)


def _mark_recovered(destination, key):
    failure = destination / 'failures' / f'{key}.json'
    if failure.exists():
        save_json(destination / 'failures/recovered' / failure.name,
                  {**load_json(failure), 'status': 'recovered', 'recovered_at': _now()})
        failure.unlink()


def _collect_samples(out, targets, config, settings, *, allow_network, progress, observation_root):
    destination = out / "collection"
    samples = destination / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    graph = config["graph"]
    observations = ObservationStore(observation_root, settings)
    recipe = {"graph": graph, "collection": _public_settings(settings)}
    expected = {_sample_key(t): _digest([t, recipe]) for t in targets}
    exclusions = load_exclusions(out, targets, expected)
    dropped = {row["key"] for row in exclusions}
    pending = []
    manifests = []
    for target in targets:
        key = _sample_key(target)
        if key in dropped:
            continue
        if (samples / key / "manifest.json").exists():
            manifests.append(_verify_sample(samples / key, expected[key]))
            _clean_work(destination / ".work" / key)
            _mark_recovered(destination, key)
        else:
            pending.append(target)
    if pending and not (settings.get("fixtures") or settings.get("fixture_dir") or settings.get("transport")):
        if not allow_network:
            raise ValueError("transaction_collection_requires_allow_network_or_fixtures")
        if not etherscan_key(settings.get("api_key_env", "ETHERSCAN_API_KEY")):
            raise ValueError("set_ETHERSCAN_API_KEY_in_local_secrets.py_before_collection")
    display = NestedSampleProgress(len(targets) - len(exclusions), len(manifests), mode=progress)
    active_roots = set()
    progress_lock = threading.Lock()
    last_report = 0.0
    started = time.monotonic()
    failures = []

    def observer(stats, query):
        nonlocal last_report
        with progress_lock:
            now = time.monotonic()
            if now - last_report < 1:
                return
            last_report = now
            report = {**stats, "updated_at": _now(), "samples_complete": len(manifests), "samples_total": len(targets) - len(exclusions),
                      "cohort_total": len(targets), "failure_excluded_count": len(exclusions),
                      "active_roots": sorted(active_roots), "active_samples": display.snapshot(),
                      "query": query, "elapsed_seconds": now - started}
            save_json(destination / "progress.json", report)

    collector = RecentHistoryCollector({**settings, "allow_network": allow_network}, observer=observer,
                                       sample_observer=display.observe)
    collector.budget.notify = display.message
    cancelled = True
    try:
        cutoff_blocks = {}
        all_cutoffs = {target["cutoff"] for target in targets}
        for cutoff in sorted({target["cutoff"] for target in pending}):
            # Preserve the legacy single-cutoff file and work path for Phishing.
            cutoff_path = (destination / "cutoff.json" if len(all_cutoffs) == 1
                           else destination / "cutoffs" / f"{cutoff}.json")
            if cutoff_path.exists():
                frozen = load_json(cutoff_path)
                if frozen["cutoff"] != cutoff:
                    raise ValueError("collection_cutoff_changed")
                end_block = frozen["end_block"]
            else:
                work = destination / ".work" / ("cutoff" if len(all_cutoffs) == 1 else f"cutoff-{cutoff}")
                end_block = collector.cutoff_block(cutoff, work)
                response = next((work / "raw_requests").glob("*.json"))
                cached = load_json(response)
                save_json(cutoff_path, {"cutoff": cutoff, "end_block": end_block,
                    "response_sha256": cached["response_sha256"], "query": cached["request"],
                    "retrieved_at": cached["retrieved_at"]})
                _clean_work(work)
            cutoff_blocks[cutoff] = end_block
        def process_sample(target):
            current = target["target"]
            end_block = cutoff_blocks[target["cutoff"]]
            with progress_lock:
                active_roots.add(current)
            display.start(target['sample_id'], current)
            key = _sample_key(target)
            final = samples / key
            work = destination / ".work" / key
            sample_start = time.monotonic()
            try:
                spec = observations.specification(target, graph, end_block)
                shared = observations.read(spec)
                reused = shared is not None
                if reused:
                    display.phase(target['sample_id'], 'shared cache')
                if shared is None:
                    events, coverage, audit = collector.collect(target, graph, end_block, work)
                    shared = observations.publish(spec, events, coverage, audit)
                events, coverage, audit, observation_ref = shared
                if sum(r["response_bytes"] for s in coverage["sources"] for r in s["requests"]) > int(settings.get("max_sample_bytes", 16 * 1024 * 1024)):
                    raise CollectionError("sample_byte_budget_exhausted")
                enriched = dict(target, coverage=coverage)
                display.phase(target['sample_id'], 'graph')
                sample = build_graph_sample(enriched, events, **graph)
                # Pin shared replay inputs before publishing the task graph.
                with tempfile.TemporaryDirectory(prefix=".sample-build-", dir=samples) as temporary:
                    display.phase(target['sample_id'], 'publish')
                    build = Path(temporary) / "sample"
                    build.mkdir()
                    artifact_names = ["graph.json", "target.json", "normalization_audit.json"]
                    if observation_ref is None:
                        # Injected transports cannot enter the shared store.
                        write_records(build / "events.jsonl.gz", events)
                        artifact_names.append("events.jsonl.gz")
                    save_json(build / "graph.json", sample)
                    save_json(build / "target.json", enriched)
                    save_json(build / "normalization_audit.json", audit)
                    requests = [request for source in coverage["sources"] for request in source["requests"]]
                    history_queries = sum('address' in r['query'] and r['query']['action'] in {'txlist', 'txlistinternal'} for r in requests)
                    manifest = {"version": "recent-sample-3", "sample_id": target["sample_id"], "target": current,
                        "event_storage": "shared_observation" if observation_ref else "local_gzip",
                        "input_sha256": expected[key], "status": "usable" if graph_is_usable(sample) else "excluded",
                        "quality_status": sample["quality"]["status"], "query_count": len(requests),
                        "history_query_count": history_queries, "verification_query_count": len(requests)-history_queries,
                        "http_attempts": 0 if reused else sum(row["http_attempts"] for row in coverage["sources"]),
                        "cache_hits": 0 if reused else sum(row["cache_hits"] for row in coverage["sources"]),
                        "shared_observation": observation_ref, "observation_cache_hit": reused,
                        "elapsed_seconds": time.monotonic() - sample_start,
                        "event_count": len(events), "nodes": len(sample["node_refs"]),
                        "raw_bytes": sum(r["response_bytes"] for r in requests),
                        "edges": len(sample["relation_ids"]), "graph_bytes": (build / "graph.json").stat().st_size,
                        "raw_retention": "deleted_after_atomic_sample_publication",
                        "artifacts": {name: sha256_file(build / name) for name in artifact_names}}
                    save_json(build / "manifest.json", manifest)
                    build.rename(final)
                # A restart after publication but before cleanup validates the
                # saved sample first, then finishes this cleanup without HTTP.
                display.phase(target['sample_id'], 'cleanup')
                _clean_work(work)
                _mark_recovered(destination, key)
                return manifest
            finally:
                with progress_lock:
                    active_roots.discard(current)

        sample_workers = int(settings.get("sample_workers", 4))
        if not 1 <= sample_workers <= 8:
            raise ValueError("sample_workers_must_be_between_1_and_8")
        root_pool = ThreadPoolExecutor(max_workers=sample_workers, thread_name_prefix="graph-sample")
        jobs = {root_pool.submit(process_sample, target): target for target in pending}
        try:
            for future in as_completed(jobs):
                target = jobs[future]
                try:
                    manifest = future.result()
                    with progress_lock:
                        manifests.append(manifest)
                        display.finish(target['sample_id'])
                except CancelledError:
                    continue
                except CollectionError as error:
                    failure = {"sample_id": target["sample_id"], "target": target["target"],
                               "failure": _safe_error(error, [etherscan_key()])}
                    failures.append(failure)
                    save_json(destination / "failures" / f"{_sample_key(target)}.json", failure)
                    display.finish(target['sample_id'], success=False)
                    display.message(f"[collect] sample {target['target']} failed: {failure['failure']}; scratch retained")
                    # Data errors affect this root. Finish unrelated roots before
                    # reporting incomplete; only account-wide failures cancel all.
                    if any(word in failure["failure"].lower() for word in ("invalid api", "invalid api-key", "missing_etherscan")):
                        collector.budget.cancel()
                        for job in jobs:
                            job.cancel()
        except BaseException:
            collector.budget.cancel()
            raise
        finally:
            root_pool.shutdown(wait=True, cancel_futures=True)
        cancelled = False
    finally:
        collector.close(cancel=cancelled)
        display.close()
    by_sample = {m["sample_id"]: m for m in manifests}
    ordered = [by_sample[t["sample_id"]] for t in targets if t["sample_id"] in by_sample]
    report = {"version": "recent-collection-2", "complete": len(ordered) == len(targets),
              "target_count": len(targets), "sample_count": len(ordered), "coverage": failures,
              "remaining_count": len(targets) - len(ordered), "failed_count": len(failures),
              "quality_counts": dict(Counter(m["quality_status"] for m in ordered)),
              "provider_policy": {"workers": collector.workers, "sample_workers": int(settings.get("sample_workers", 4)), "rate_limit_rps": collector.budget.rate,
                                  "rolling_24h_limit": REQUESTS_PER_24H, "scope": "shared_in_process",
                                  "max_sample_bytes": int(settings.get("max_sample_bytes", 16 * 1024 * 1024))},
              "current_run": collector.stats(),
              "samples": [{"sample_id": t["sample_id"], "key": _sample_key(t),
                           "manifest_sha256": sha256_file(samples / _sample_key(t) / "manifest.json")}
                          for t in targets if t["sample_id"] in by_sample]}
    if ordered:
        report["statistics"] = {"median_queries_per_sample": statistics.median(m["query_count"] for m in ordered),
                                "median_raw_bytes": statistics.median(m["raw_bytes"] for m in ordered),
                                "median_graph_bytes": statistics.median(m["graph_bytes"] for m in ordered),
                                "max_queries_per_sample": max(m["query_count"] for m in ordered)}
    report = resolve_report(out, report, exclusions)
    manifest_path = destination / "manifest.json"
    if manifest_path.exists() and load_json(manifest_path).get("complete") is True:
        previous = load_json(manifest_path)
        if previous["samples"] != report["samples"]:
            raise ValueError("published_collection_changed")
        if previous.get("failure_exclusions_sha256") != report.get("failure_exclusions_sha256"):
            raise ValueError("published_collection_exclusions_changed")
        report = previous
    else:
        save_json(manifest_path, report)
    save_json(destination / "progress.json", {"status": "complete" if report["complete"] else "incomplete",
              "samples_complete": len(ordered), "samples_total": len(targets) - len(exclusions),
              "cohort_total": len(targets), "failure_excluded_count": len(exclusions), "updated_at": _now(),
              "current_run": collector.stats()})
    return report


def prepare_recent_phishing(out, config, *, stage="all", settings=None, positive_source="forta",
                            per_class=None, source_as_of=None, discover=False, background_blocks=384,
                            progress="auto", allow_network=False, dry_run=False, drop_failed=False):
    if stage not in STAGES:
        raise ValueError("unsupported_phishing_preparation_stage")
    config = validate_config(config)
    if config["task_id"] != "phishing" or config["experiment_mode"] != "known_positive_vs_unlabeled" or config["training_as_of"] is not None:
        raise ValueError("recent_pipeline_requires_retrospective_phishing_P_U_config")
    if discover or (settings or {}).get("background_snapshot"):
        raise ValueError("recent_pipeline_uses_only_poison_hunter_background_remove_discovery_options")
    settings = copy.deepcopy(settings or {})
    _check_settings(settings)
    out = Path(out)
    from .compaction import require_finished_compaction
    require_finished_compaction(out)
    if stage in {"collect", "prepare"} and not (out / "cohort/manifest.json").exists():
        raise ValueError("address_cohort_required_run_stage_addresses_first")
    paths = {name: str((out / name).resolve()) for name in ("sources", "cohort", "collection", "prepared")}
    source_path = out / "sources"
    if dry_run and not (source_path / "manifest.json").exists():
        if stage in {"collect", "prepare"}:
            raise ValueError("address_cohort_required_before_collection")
        fetch_phishing_labels(source_path, dry_run=True)
        return {"status": "planned", "stage": stage, "paths": paths, "network_performed": False,
                "background_policy": "poison_hunter_only", "fitting_performed": False,
                "queries_per_sample_upper_bound": (1 + config["graph"]["fanouts"][0]) * 2 * config["graph"]["pages_per_action"]}
    source_manifest = fetch_phishing_labels(source_path, allow_network=allow_network and not dry_run,
        local_files=settings.get("label_files"), positive_source=positive_source,
        source_as_of=source_as_of, source_snapshot=settings.get("source_snapshot"))
    if stage == "sources":
        return {"status": "sources_ready", "paths": paths, "fitting_performed": False}
    targets, evidence, cohort = build_reference_phishing_cohort(source_path, per_class=per_class, seed=config["seed"])
    reference = next(row for row in source_manifest["files"] if row["name"] == "poison_hunter_background")
    pool_root = Path(settings.get("address_pool_root", SHARED_ADDRESS_POOLS))
    if not dry_run:
        background_ref = freeze_address_pool(source_path / reference["file"], reference, pool_root)
        pool_rows, _ = load_address_pool(background_ref["path"])
        if not {t["target"] for t in targets if t["background_selected"]} <= {r["address"] for r in pool_rows}:
            raise ValueError("cohort_background_not_in_shared_address_pool")
        _freeze_json(out / "background_ref.json", background_ref)
        paths["background_pool"] = background_ref["path"]
    elif (out / "background_ref.json").exists():
        background_ref = load_json(out / "background_ref.json")
        load_address_pool(background_ref["path"])
        if sha256_file(Path(background_ref["path"]) / "manifest.json") != background_ref["manifest_sha256"]:
            raise ValueError("shared_address_pool_manifest_changed")
        paths["background_pool"] = background_ref["path"]
    cutoff = cohort["cutoff"]
    if cutoff <= ETHEREUM_GENESIS_TIMESTAMP:
        raise ValueError("source_cutoff_must_follow_ethereum_genesis")
    effective = copy.deepcopy(config)
    effective["graph"]["window_days"] = math.ceil((cutoff - ETHEREUM_GENESIS_TIMESTAMP + 1) / 86400)
    graph = effective["graph"]
    collection = {**effective["collection"], **settings.get("collection", {})}
    collection.pop("shared_cache_dir", None)
    if (graph.get("sampling_mode") != RECENT_SAMPLING or graph["hops"] != 2
            or graph["rows_per_action"] != collection["page_size"]
            or graph["pages_per_action"] != collection["max_pages"]):
        raise ValueError("recent_graph_collection_sampling_recipe_mismatch")
    targets = [dict(t, observation_start=cutoff - graph["window_days"] * 86400,
                    source_snapshot=sha256_file(source_path / "manifest.json")) for t in targets]
    contract = {"version": "recent-cohort-2", "config": effective, "cohort": cohort,
                "collection": _public_settings(collection),
                "fixtures_sha256": _digest(collection.get("fixtures"))}
    if dry_run:
        if (out / "cohort/manifest.json").exists():
            frozen = load_json(out / "cohort/manifest.json")
            if {k: v for k, v in frozen.items() if k != "address_lists"} != contract:
                raise ValueError("snapshot_inputs_changed_use_a_new_snapshot")
            for name, digest in frozen["address_lists"].items():
                if sha256_file(out / "cohort" / name) != digest:
                    raise ValueError("address_list_checksum_mismatch")
            if read_records(out / "cohort/targets.jsonl") != targets or read_records(out / "cohort/evidence.jsonl") != evidence:
                raise ValueError("frozen_cohort_rows_changed")
        drop_plan = (freeze_exclusions(out, targets,
                     {_sample_key(t): _digest([t, {"graph": graph, "collection": _public_settings(collection)}]) for t in targets},
                     dry_run=True) if drop_failed and (out / "collection/manifest.json").exists() else [])
        return {"status": "planned", "stage": stage, "paths": paths, "network_performed": False,
                "planned_failure_exclusions": drop_plan,
                "cohort": cohort, "provider_policy": {"workers": collection["workers"],
                    "rate_limit_rps": min(REQUESTS_PER_SECOND, collection["rate_limit_rps"]), "rolling_24h_limit": REQUESTS_PER_24H},
                "queries_per_sample_upper_bound": (1 + graph["fanouts"][0]) * 2 * graph["pages_per_action"],
                "fitting_performed": False}
    contract["address_lists"] = _address_lists(out / "cohort", targets, evidence)
    _freeze_json(out / "cohort/manifest.json", contract)
    _freeze_rows(out / "cohort/targets.jsonl", targets)
    _freeze_rows(out / "cohort/evidence.jsonl", evidence)
    _freeze_json(out / "cohort/training_config.json", effective)
    if stage == "cohort":
        return {"status": "cohort_ready", "cohort": cohort, "paths": paths, "fitting_performed": False}
    if stage in {"collect", "all"}:
        report = _collect_samples(out, targets, effective, collection, allow_network=allow_network, progress=progress,
                                  observation_root=settings.get("observation_root", SHARED_OBSERVATIONS))
        if not report["complete"] and not (drop_failed and stage == "all"):
            return {"status": "collection_incomplete", "collection": report, "paths": paths,
                    "resume": "repeat the same snapshot; published samples skip HTTP and failed samples reuse scratch requests",
                    "fitting_performed": False}
        if stage == "collect":
            return {"status": "collected", "collection": report, "paths": paths, "fitting_performed": False}
    result = prepare_collected_samples(out, targets, evidence, effective, collection, drop_failed=drop_failed)
    result["paths"] = paths
    return result


def prepare_collected_samples(out, targets, evidence, effective, collection, *, drop_failed=False, dry_run=False):
    """Verify and assemble complete per-root address graphs for either task."""
    graph = effective["graph"]
    paths = {name: str((out / name).resolve()) for name in ("sources", "cohort", "collection", "prepared")}
    collected = load_json(out / "collection/manifest.json")
    expected = {_sample_key(t): _digest([t, {"graph": graph, "collection": _public_settings(collection)}]) for t in targets}
    exclusions = (freeze_exclusions(out, targets, expected, dry_run=dry_run) if drop_failed
                  else load_exclusions(out, targets, expected))
    if dry_run and exclusions and not (out / "collection/failure_exclusions.json").exists():
        return {"status": "planned", "paths": paths, "planned_failure_exclusions": exclusions,
                "fitting_performed": False}
    resolved = resolve_report(out, collected, exclusions)
    if resolved != collected and not dry_run:
        save_json(out / "collection/manifest.json", resolved)
    collected = resolved
    dropped = {row["key"] for row in exclusions}
    retained_targets = [t for t in targets if _sample_key(t) not in dropped]
    if not collected["complete"] or len(collected["samples"]) != len(retained_targets):
        raise ValueError("complete_collection_required_before_preparation")
    graphs, enriched = [], []
    for target, entry in zip(retained_targets, collected["samples"]):
        directory = out / "collection/samples" / _sample_key(target)
        if entry["sample_id"] != target["sample_id"] or entry["key"] != _sample_key(target) or sha256_file(directory / "manifest.json") != entry["manifest_sha256"]:
            raise ValueError("collection_sample_manifest_mismatch")
        _verify_sample(directory, _digest([target, {"graph": graph, "collection": _public_settings(collection)}]))
        graphs.append(load_json(directory / "graph.json"))
        enriched.append(load_json(directory / "target.json"))
    inputs = {"collection": sha256_file(out / "collection/manifest.json"),
              "targets": sha256_file(out / "cohort/targets.jsonl"), "evidence": sha256_file(out / "cohort/evidence.jsonl")}
    if exclusions:
        inputs["failure_exclusions"] = sha256_file(out / "collection/failure_exclusions.json")
    prepared = out / "prepared"
    if (prepared / "dataset_manifest.json").exists():
        report = load_json(prepared / "dataset_manifest.json")
        if report["inputs"] != inputs or report["config"] != effective:
            raise ValueError("prepared_dataset_inputs_changed")
        for name, digest in report["artifacts"].items():
            if sha256_file(prepared / f"{name}.jsonl") != digest:
                raise ValueError("prepared_dataset_checksum_mismatch")
    else:
        report = prepare_graph_dataset(graphs, enriched, evidence, effective, prepared, inputs=inputs,
            selection={"cohort_target_count": len(targets), "published_outcome_count": len(retained_targets),
                       "collection_failure_excluded_count": len(exclusions),
                       "policy": "frozen_recorded_failure_exclusions" if exclusions else "all_cohort_roots_published"},
            dry_run=dry_run)
    if not dry_run:
        _freeze_json(prepared / "training_config.json", effective)
    elif (prepared / "training_config.json").exists() and load_json(prepared / "training_config.json") != effective:
        raise ValueError("prepared_training_config_changed")
    return {"status": "validated" if dry_run else "prepared", "paths": paths, "dataset": report, "fitting_performed": False}
