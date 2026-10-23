"""Frozen Trapdoor evidence and a separate, contemporary token-label cohort.

This workflow prepares evidence, not graphs or automatically admitted labels.
Historical source labels never inherit the API capture time of another cohort.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import time

from packages.collection import CollectionError, EtherscanClient, _now
from packages.io import atomic_bytes, load_json, read_records, save_json, sha256_file, write_records
from packages.labeling import import_labels
from packages.sources.phishing import _download
from packages.token import UNISWAP_V2_FACTORY
from packages.token_sources import SnapshotClient
from packages.transactions import address, decode_v2_log, integer

REPOSITORY = "bsdp2023/trapdoor_data"
SOURCE_FILES = {"positive": "trapdoor_list.csv", "negative": "non_malicious_list.csv"}
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
PAIR_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
STAGES = ("sources", "audit", "discover", "label", "prepare", "all")
CSV_FIELDS = ("sample_id", "task_id", "chain_id", "token_address", "pair_address",
              "source", "source_label", "candidate_label", "label_status", "audit_decision",
              "checked_at", "cutoff", "valid_from", "valid_to", "label_available_at",
              "simulation_success", "evidence_ref", "failure_reason", "training_eligible")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _freeze(path, value):
    if path.exists():
        if load_json(path) != value:
            raise ValueError("honeypot_snapshot_inputs_changed_use_a_new_snapshot")
    else:
        save_json(path, value)


def _manifest(path, artifacts, **metadata):
    value = {**metadata, "artifacts": {str(p.relative_to(path.parent)): sha256_file(p) for p in artifacts}}
    _freeze(path, value)
    return value


def _verified(path):
    manifest = load_json(path)
    for relative, expected in manifest["artifacts"].items():
        if sha256_file(path.parent / relative) != expected:
            raise ValueError("honeypot_artifact_checksum_mismatch")
    return manifest


def _csv(path, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in CSV_FIELDS})
    atomic_bytes(path, stream.getvalue().encode())


def freeze_sources(out, settings, allow_network):
    directory = out / "sources"
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        manifest = _verified(manifest_path)
        for name, filename in settings.get("source_files", {}).items():
            if name not in SOURCE_FILES or sha256_file(filename) != manifest["artifacts"][SOURCE_FILES[name]]:
                raise ValueError("honeypot_source_file_changed")
        return manifest
    local = settings.get("source_files", {})
    if local and set(local) != set(SOURCE_FILES):
        raise ValueError("trapdoor_source_files_require_positive_and_negative")
    if not local and not allow_network:
        raise ValueError("trapdoor_download_requires_allow_network_or_source_files")
    # Pin both source files to the same repository revision before downloading.
    revision = None
    if not local:
        metadata = json.loads(_download(f"https://api.github.com/repos/{REPOSITORY}/commits/main"))
        revision = metadata["sha"]
        if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
            raise ValueError("invalid_trapdoor_revision")
    files = []
    for name, filename in SOURCE_FILES.items():
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/{filename}" if revision else None
        data = Path(local[name]).read_bytes() if local else _download(url)
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        required = {"token_address", "pool_address"} | ({"type"} if name == "positive" else set())
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("invalid_trapdoor_source_schema")
        destination = directory / filename
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError("partial_trapdoor_source_changed_use_a_new_snapshot")
        atomic_bytes(destination, data)
        files.append(destination)
    return _manifest(manifest_path, files, version="trapdoor-sources-1", repository=REPOSITORY,
                     revision=revision, retrieved_at=_now(), transport="local" if local else "https",
                     historical_label_time=None, license_status="not_established")


def audit_sources(out):
    source = _verified(out / "sources/manifest.json")
    directory = out / "historical"
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        result = _verified(manifest_path)
        if result["source_manifest_sha256"] != sha256_file(out / "sources/manifest.json"):
            raise ValueError("trapdoor_audit_source_changed")
        return result
    rows, rejected, by_token = [], [], defaultdict(list)
    seen, counts = set(), Counter()
    for polarity, filename in SOURCE_FILES.items():
        with (out / "sources" / filename).open(encoding="utf-8-sig", newline="") as stream:
            for number, raw in enumerate(csv.DictReader(stream), 2):
                counts[f"{polarity}_source_rows"] += 1
                token, pool = address(raw.get("token_address")), address(raw.get("pool_address"))
                if not token or not pool or token == pool:
                    rejected.append({"file": filename, "line": number, "reason": "invalid_token_or_pool", "raw": raw})
                    continue
                identity = (polarity, token, pool, raw.get("type"))
                if identity in seen:
                    counts["exact_duplicates"] += 1
                    continue
                seen.add(identity)
                row = {"sample_id": "trapdoor-" + _digest([token, pool])[:24], "task_id": "honeypot",
                       "chain_id": 1, "token_address": token, "pair_address": pool,
                       "source": "trapdoor", "source_label": polarity, "candidate_label": int(polarity == "positive"),
                       "mechanism": raw.get("type"), "label_status": "source_label_time_unresolved",
                       "audit_decision": "pending_temporal_and_mechanism_review", "checked_at": None,
                       "cutoff": None, "valid_from": None, "valid_to": None, "label_available_at": None,
                       "training_eligible": False,
                       "evidence_ref": str((out / "sources" / filename).resolve()) + f":{number}"}
                rows.append(row)
                by_token[token].append(row)
    conflicts = {token for token, values in by_token.items() if len({v["candidate_label"] for v in values}) > 1}
    for row in rows:
        if row["token_address"] in conflicts:
            row.update(candidate_label=None, label_status="source_conflict", audit_decision="excluded_conflicting_labels")
    counts.update({"unique_positive_tokens": sum(all(r["source_label"] == "positive" for r in values)
                                                   for values in by_token.values()),
                   "unique_negative_tokens": sum(all(r["source_label"] == "negative" for r in values)
                                                   for values in by_token.values()),
                   "unique_tokens": len(by_token), "conflicting_tokens": len(conflicts),
                   "invalid_rows": len(rejected), "pool_records": len(rows), "training_eligible": 0})
    write_records(directory / "labels.jsonl", rows)
    _csv(directory / "labels.csv", rows)
    write_records(directory / "rejected.jsonl", rejected)
    # Include every valid address, including conflicts, in later anti-overlap checks.
    write_records(directory / "tokens.jsonl", [{"token_address": t} for t in sorted(by_token)])
    report = {"counts": dict(counts), "mechanism_counts": dict(Counter(r.get("mechanism") for r in rows if r.get("mechanism"))),
              "checks": {"source_bytes_pinned": True, "address_format_checked": True,
                         "cross_label_conflicts_checked": True, "historical_time_available": False,
                         "independent_truth_validation_performed": False, "pool_identity_verified_on_chain": False},
              "blockers": ["historical_cutoff_and_label_validity_missing", "mechanism_and_negative_definition_review",
                           "historical_pool_verification", "source_usage_terms_unresolved"],
              "policy": "Source dates/retrieval times are not incident times. Never use today's API label to backdate these rows."}
    save_json(directory / "quality_audit.json", report)
    markdown = ("# Trapdoor label quality audit\n\n" +
                "\n".join(f"- {key}: {value}" for key, value in counts.items()) +
                "\n\nSource labels are candidates. The CSV supplies no per-sample detection time, validity interval or incident block. "
                "No historical cutoff has been invented; no sample is admitted to training. "
                "The audit checks source structure and conflicts, not independent ground truth.\n\n" +
                "Required before historical graph collection: reviewed temporal evidence or a separately approved retrospective "
                "observation-anchor protocol, mechanism/negative review, and pool verification. "
                "Do not overwrite historical labels with contemporary API detections.\n")
    atomic_bytes(directory / "quality_audit.md", markdown.encode())
    return _manifest(manifest_path, list(directory.glob("*.jsonl")) + [directory / "labels.csv", directory / "quality_audit.json", directory / "quality_audit.md"],
                     version="trapdoor-audit-1", source_manifest_sha256=sha256_file(out / "sources/manifest.json"),
                     counts=dict(counts), source_revision=source["revision"])


def discover_candidates(out, settings, allow_network, count=None, progress="auto"):
    _verified(out / "historical/manifest.json")
    historical = {r["token_address"] for r in read_records(out / "historical/tokens.jsonl")}
    directory = out / "discovery"
    recipe_path = directory / "recipe.json"
    options = settings.get("discovery", {})
    previous = load_json(recipe_path) if recipe_path.exists() else {}
    recipe = {"version": "honeypot-weth-pairs-1", "chain_id": 1, "factory": UNISWAP_V2_FACTORY, "quote_token": WETH,
              "candidate_count": count if count is not None else previous.get("candidate_count", 1000),
              "seed": options.get("seed", previous.get("seed", 20261020)),
              "lookback_days": options.get("lookback_days", previous.get("lookback_days", 180)),
              "as_of": options.get("as_of", previous.get("as_of", int(time.time()))),
              "provider_endpoint": settings.get("collection", {}).get("endpoint", "https://api.etherscan.io/v2/api"),
              "historical_manifest_sha256": sha256_file(out / "historical/manifest.json")}
    for key in ("candidate_count", "seed", "lookback_days", "as_of"):
        if type(recipe[key]) is not int or recipe[key] < (0 if key == "seed" else 1):
            raise ValueError("invalid_honeypot_discovery_" + key)
    _freeze(recipe_path, recipe)
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        return _verified(manifest_path)
    chain_settings = dict(settings.get("collection", {}))
    chain_settings["allow_network"] = allow_network
    client = EtherscanClient(directory, chain_settings)
    if progress != "off":
        last_report = [0.0]
        def report(value):
            now = time.monotonic()
            if now - last_report[0] >= 15:
                last_report[0] = now
                query = value.get("query", {})
                print(f"[honeypot discovery] requests={value.get('requests', 0)} cache_hits={value.get('cache_hits', 0)} "
                      f"blocks={query.get('fromBlock', '?')}..{query.get('toBlock', '?')} page={query.get('page', '?')}",
                      file=sys.stderr, flush=True)
        client.on_progress = report
    bounds_path = directory / "block_range.json"
    if bounds_path.exists():
        bounds = load_json(bounds_path)
    else:
        bounds = {"start_block": client.block_by_time(recipe["as_of"] - recipe["lookback_days"] * 86400, "after"),
                  "end_block": client.block_by_time(recipe["as_of"], "before")}
        _freeze(bounds_path, bounds)
    if bounds["start_block"] > bounds["end_block"]:
        raise ValueError("invalid_honeypot_block_range")
    pairs, coverage = {}, []
    for position in (1, 2):
        extra = {"topic0": PAIR_TOPIC, f"topic{position}": "0x" + WETH[2:].rjust(64, "0"),
                 f"topic0_{position}_opr": "and"}
        logs, covered = client.history("getLogs", UNISWAP_V2_FACTORY, **bounds, **extra)
        coverage.append(covered)
        save_json(directory / "coverage.json", coverage)
        if not covered.get("complete") or covered.get("gaps"):
            raise CollectionError("honeypot_discovery_coverage_incomplete")
        for raw in logs:
            if address(raw.get("address")) != UNISWAP_V2_FACTORY:
                raise ValueError("honeypot_discovery_wrong_emitter")
            event = decode_v2_log(raw)
            if not event or event["relation"] != "pair_created" or WETH not in (event["token0"], event["token1"]):
                raise ValueError("honeypot_discovery_wrong_event")
            token = event["token1"] if event["token0"] == WETH else event["token0"]
            if token in historical or token == WETH:
                continue
            row = {"sample_id": "hp-api-" + _digest([token, event["pool"]])[:24], "task_id": "honeypot",
                   "chain_id": 1, "target": token, "pools": [event["pool"]], "token0": event["token0"],
                   "token1": event["token1"], "pair_created_block": integer(raw.get("blockNumber")),
                   "pair_created_at": integer(raw.get("timeStamp")), "creation_tx": raw.get("transactionHash"),
                   "factory": UNISWAP_V2_FACTORY, "evidence_ref": raw.get("raw_path"),
                   "sampling_rank": _digest([recipe["seed"], token])}
            if token in pairs and pairs[token]["pools"] != row["pools"]:
                raise ValueError("conflicting_canonical_weth_pair")
            pairs[token] = row
    all_rows = sorted(pairs.values(), key=lambda r: (r["sampling_rank"], r["target"]))
    write_records(directory / "eligible_candidates.jsonl", all_rows)
    if len(all_rows) < recipe["candidate_count"]:
        save_json(directory / "insufficient_candidates.json", {"available": len(all_rows), "required": recipe["candidate_count"],
                  "resolution": "Use a new snapshot with a longer discovery.lookback_days; never replace based on label results."})
        raise ValueError("honeypot_insufficient_candidates_expand_range_in_new_snapshot")
    selected = all_rows[:recipe["candidate_count"]]
    write_records(directory / "targets.jsonl", selected)
    stream = io.StringIO(newline="")
    fields = ["sample_id", "chain_id", "token_address", "pair_address", "pair_created_block", "pair_created_at", "sampling_rank"]
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows({**r, "token_address": r["target"], "pair_address": r["pools"][0]} for r in selected)
    atomic_bytes(directory / "candidates.csv", stream.getvalue().encode())
    return _manifest(manifest_path, [recipe_path, bounds_path, directory / "coverage.json", directory / "eligible_candidates.jsonl",
                     directory / "targets.jsonl", directory / "candidates.csv"], version="honeypot-discovery-1",
                     candidate_count=len(selected), eligible_unique_tokens=len(all_rows), excluded_historical_tokens=len(historical),
                     selection="fixed_seed_hash_sample_of_complete_WETH_PairCreated_range_before_API_labels",
                     candidate_meaning="unlabeled; not assumed negatives")


def capture_labels(out, settings, allow_network, progress="auto"):
    _verified(out / "discovery/manifest.json")
    directory = out / "contemporary"
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        return _verified(manifest_path)
    settings = dict(settings.get("honeypot", {}))
    # Independent provider limit; defaults to one request per second, finite retries.
    settings.setdefault("rate_limit_rps", 1)
    settings["allow_network"] = allow_network
    workers = settings.pop("workers", 1 if settings.get("transport") or settings.get("fixtures") else 4)
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("honeypot_workers_must_be_between_1_and_8")
    _freeze(directory / "recipe.json", {"discovery_manifest_sha256": sha256_file(out / "discovery/manifest.json"),
            "failure_policy": "record_and_drop_sample_local_failures_after_finite_retries_no_replacements",
            "review_policy": "structural_checks_only_manual_truth_review_pending"})
    client = SnapshotClient(directory, settings)
    targets = read_records(out / "discovery/targets.jsonl")
    results, snapshots, detection_targets, imported = [], [], [], []
    def capture_one(target):
        result_path = directory / "results" / (target["sample_id"] + ".json")
        query = {"sample_id": target["sample_id"], "address": target["target"], "chainID": 1, "pair": target["pools"][0]}
        if result_path.exists():
            item = load_json(result_path)
            if item["request"] != query or item["outcome_sha256"] != _digest(item["outcome"]):
                raise ValueError("honeypot_outcome_checksum_mismatch")
            if item.get("snapshot"):
                # Verify the immutable capture too, without making a new request.
                bundle = client.request("honeypot_is", query)
                if _digest(bundle) != _digest(item["snapshot"]):
                    raise ValueError("honeypot_outcome_snapshot_mismatch")
        else:
            base = {"sample_id": target["sample_id"], "task_id": "honeypot", "chain_id": 1,
                    "token_address": target["target"], "pair_address": target["pools"][0], "source": "honeypot_is",
                    "audit_decision": "pending_review", "training_eligible": False}
            bundle = None
            try:
                bundle = client.request("honeypot_is", query)
            except CollectionError as error:
                reason = str(error)
                lower = reason.lower()
                if any(s in lower for s in ("checksum", "invalid_snapshot_cache", "request_budget", "network_disabled", "401", "403", "429", "api key", "api-key", "unauthorized", "forbidden", "rate limit", "quota")):
                    raise
                base.update(candidate_label=None, label_status="excluded_query_failure", failure_reason=reason)
            else:
                response = bundle["response"]
                one = directory / "pending" / (target["sample_id"] + ".jsonl")
                write_records(one, [bundle])
                try:
                    label = import_labels("honeypot_is", one, "honeypot")[0]
                except (ValueError, TypeError, KeyError) as error:
                    label = {"mapped_label": None, "label_status": "invalid", "audit_decision": type(error).__name__}
                finally:
                    one.unlink(missing_ok=True)
                base.update(candidate_label=label.get("mapped_label"), label_status=label["label_status"],
                            source_label=label.get("source_label"), checked_at=bundle["checked_at"], cutoff=bundle["checked_at"],
                            valid_from=bundle["checked_at"], valid_to=bundle["checked_at"], label_available_at=bundle["checked_at"],
                            simulation_success=response.get("simulationSuccess"), evidence_ref=bundle["evidence_ref"],
                            structural_decision=label.get("audit_decision"), imported_label=label)
            item = {"request": query, "snapshot": bundle, "outcome": base, "outcome_sha256": _digest(base)}
            save_json(result_path, item)
        return target, item

    completed = {}
    def retain(index, target, item):
        completed[target["sample_id"]] = (target, item)
        row = item["outcome"]
        results.append(row)
        if progress != "off" and (index == 1 or index % 10 == 0 or index == len(targets)):
            print(f"[honeypot] checked {index}/{len(targets)}; candidate labels {dict(Counter(r.get('candidate_label') for r in results))}", file=sys.stderr, flush=True)
        save_json(directory / "progress.json", {"attempted": index, "total": len(targets),
                  "candidate_label_counts": dict(Counter(str(r.get("candidate_label")) for r in results)),
                  "status_counts": dict(Counter(r["label_status"] for r in results))})
    if workers == 1:
        for index, target in enumerate(targets, 1):
            retain(index, *capture_one(target))
    else:
        pool = ThreadPoolExecutor(max_workers=workers)
        futures = [pool.submit(capture_one, target) for target in targets]
        try:
            for index, future in enumerate(as_completed(futures), 1):
                retain(index, *future.result())
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
    # Canonical output order is independent of HTTP completion order.
    results = []
    for original in targets:
        target, item = completed[original["sample_id"]]
        row = item["outcome"]
        results.append(row)
        if item.get("snapshot"):
            snapshots.append(item["snapshot"])
        if row.get("candidate_label") in (0, 1) and row.get("label_status") != "invalid":
            detection_targets.append({**target, "cutoff": row["cutoff"], "source_snapshot": row["evidence_ref"]})
            imported.append(row["imported_label"])
    write_records(directory / "labels.jsonl", results)
    _csv(directory / "labels.csv", results)
    write_records(directory / "honeypot_snapshots.jsonl", snapshots)
    write_records(directory / "detection_targets.jsonl", detection_targets)
    write_records(directory / "pending_supervision.jsonl", imported)
    return _manifest(manifest_path, [directory / name for name in ("recipe.json", "labels.jsonl", "labels.csv", "honeypot_snapshots.jsonl",
                     "detection_targets.jsonl", "pending_supervision.jsonl")] + sorted((directory / "results").glob("*.json"))
                     + sorted((directory / "raw_requests").glob("*.json")),
                     version="honeypot-api-cohort-1", attempted=len(results),
                     candidate_label_counts=dict(Counter(str(r.get("candidate_label")) for r in results)),
                     status_counts=dict(Counter(r["label_status"] for r in results)), training_eligible=0,
                     excluded_query_failures=sum(r["label_status"] == "excluded_query_failure" for r in results))


def prepare_honeypot(out, *, stage="all", settings=None, candidate_count=None,
                     allow_network=False, dry_run=False, progress="auto", graph_run="recent-v1",
                     graph_cohort=None, historical_cutoff=None, graph_limit=None, strict_collection=False):
    from .honeypot_graphs import GRAPH_STAGES, run_graphs
    if stage == "prepare-training":
        from .honeypot_graphs import graph_root
        from .honeypot_training import prepare_training
        return prepare_training(graph_root(out, graph_run), dry_run=dry_run)
    if stage in {*GRAPH_STAGES, "graphs"}:
        return run_graphs(out, stage=stage, settings=settings, graph_run=graph_run, cohort=graph_cohort,
                          historical_cutoff=historical_cutoff, limit=graph_limit, allow_network=allow_network,
                          dry_run=dry_run, drop_failed=not strict_collection, progress=progress)
    if stage not in STAGES:
        raise ValueError("unsupported_honeypot_evidence_stage")
    if candidate_count is not None and (type(candidate_count) is not int or candidate_count < 1):
        raise ValueError("invalid_honeypot_candidate_count")
    out, settings = Path(out), dict(settings or {})
    if set(settings) - {"source_files", "discovery", "collection", "honeypot", "verification", "graph_pipeline", "graph_selection", "observation_root"}:
        raise ValueError("unsupported_honeypot_settings")
    from .phishing import _check_settings
    _check_settings({section: {key: value for key, value in options.items() if key not in {"fixtures", "transport"}}
                     for section, options in settings.items() if isinstance(options, dict)})
    frozen_recipe = out / "discovery/recipe.json"
    if not dry_run and candidate_count is not None and frozen_recipe.exists():
        if load_json(frozen_recipe)["candidate_count"] != candidate_count:
            raise ValueError("honeypot_snapshot_inputs_changed_use_a_new_snapshot")
    # Runtime transports/fixtures may contain synthetic strings; settings are
    # never dumped wholesale into a manifest or status record.
    if dry_run:
        return {"status": "planned", "task_id": "honeypot", "stage": stage, "network_performed": False,
                "candidate_count": candidate_count or 1000, "output": str(out.resolve()),
                "stages": list(STAGES[:-1]) if stage == "all" else [stage],
                "scope": "source_audit_and_API_label_evidence_only_no_graph_collection_or_training"}
    stages = list(STAGES[:-1]) if stage == "all" else [stage]
    result = {}
    for name in stages:
        if name == "sources":
            result[name] = freeze_sources(out, settings, allow_network)
        elif name == "audit":
            result[name] = audit_sources(out)
        elif name == "discover":
            result[name] = discover_candidates(out, settings, allow_network, candidate_count, progress)
        elif name == "label":
            result[name] = capture_labels(out, settings, allow_network, progress)
        else:
            historic = _verified(out / "historical/manifest.json")
            current = _verified(out / "contemporary/manifest.json")
            outcomes = {r["sample_id"]: r for r in read_records(out / "contemporary/labels.jsonl")}
            positive_reasons, unknown_errors, positive_simulations = Counter(), Counter(), Counter()
            for capture in read_records(out / "contemporary/honeypot_snapshots.jsonl"):
                row = outcomes[capture["request"]["sample_id"]]
                response = capture["response"]
                if row.get("candidate_label") == 1:
                    detected = response.get("honeypotResult", {})
                    positive_reasons[str(detected.get("honeypotReason", "not_reported"))] += 1
                    positive_simulations[str(response.get("simulationSuccess"))] += 1
                elif row.get("candidate_label") is None:
                    unknown_errors[str(response.get("simulationError", "not_reported"))] += 1
            readiness = {"historical_counts": historic["counts"], "contemporary_candidate_label_counts": current["candidate_label_counts"],
                         "contemporary_status_counts": current["status_counts"],
                         "contemporary_attempted": current["attempted"],
                         "contemporary_excluded_query_failures": current["excluded_query_failures"],
                         "API_positive_reasons": dict(positive_reasons.most_common()),
                         "API_positive_simulation_success": dict(positive_simulations),
                         "API_unknown_errors": dict(unknown_errors.most_common()),
                         "training_eligible": 0, "historical_collection_ready": False,
                         "contemporary_collection_ready": False,
                         "blockers": ["historical_labels_have_no_reviewed_time_anchor", "API_labels_require_admission_review",
                                      "verify_selected_pools_at_each_reviewed_cutoff", "do_not_silently_merge_historical_and_current_cohorts"],
                         "next_steps": "Review source mechanisms and time evidence; review raw API captures; use verify-token-targets then collect with reviewed targets. No fitting is started."}
            save_json(out / "readiness.json", readiness)
            counts = current["candidate_label_counts"]
            report = ("# Honeypot evidence preparation\n\n"
                      "| Cohort | Positive source/candidate labels | Negative source/candidate labels | Unknown/invalid/failed |\n"
                      "|---|---:|---:|---:|\n"
                      f"| Historical Trapdoor (unique tokens) | {historic['counts']['unique_positive_tokens']} | "
                      f"{historic['counts']['unique_negative_tokens']} | {historic['counts']['invalid_rows']} invalid source rows |\n"
                      f"| Contemporary API (distinct tokens) | {counts.get('1', 0)} | {counts.get('0', 0)} | {counts.get('None', 0)} |\n\n"
                      f"API sample-local query failures excluded: {current['excluded_query_failures']}. "
                      "Historical and contemporary rows remain separate and are not summed into a training cohort.\n\n"
                      "Historical source CSVs lack per-sample temporal evidence. Review historical anchors/mechanisms and "
                      "API admission, then verify each selected pool at its cutoff before chain collection. "
                      "Structural scope checks do not independently establish ground truth. No graph collection or training ran.\n")
            report += "\n## API-reported positive reasons\n\n" + "\n".join(
                f"- {reason.replace(chr(10), ' ')}: {count}" for reason, count in positive_reasons.most_common()) + "\n"
            atomic_bytes(out / "readiness.md", report.encode())
            result[name] = readiness
    return {"status": "evidence_prepared" if stage in {"all", "prepare"} else "evidence_" + stage,
            "task_id": "honeypot", "output": str(out.resolve()),
            "summary": {name: {k: v for k, v in value.items() if k != "artifacts"} for name, value in result.items()}}
