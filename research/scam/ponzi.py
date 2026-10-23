"""Frozen XBlock/Unica Ponzi cohorts and bounded historical graph preparation."""
from collections import Counter, defaultdict
import copy
import csv
from datetime import datetime
import hashlib
import io
import math
from pathlib import Path

from packages.graph import RECENT_SAMPLING
from packages.io import atomic_bytes, load_json, read_records, sha256_file
from packages.labeling import import_labels
from packages.sources.ponzi import freeze_source_snapshot, inspect_source_snapshot
from .phishing import ETHEREUM_GENESIS_TIMESTAMP, STAGES, _check_settings, _freeze_json, _freeze_rows
from .recent import _collect_samples, _digest, _public_settings, prepare_collected_samples
from .storage import PONZI_SOURCE_SNAPSHOT, SHARED_OBSERVATIONS
from .training import validate_config

DEFAULT_SOURCES = PONZI_SOURCE_SNAPSHOT


def parse_cutoff(value):
    if isinstance(value, bool):
        raise ValueError("ponzi_cutoff_requires_timestamp")
    try:
        cutoff = int(value)
    except (ValueError, TypeError):
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("ponzi_cutoff_requires_timezone")
        cutoff = int(date.timestamp())
    if cutoff <= ETHEREUM_GENESIS_TIMESTAMP:
        raise ValueError("ponzi_cutoff_must_follow_ethereum_genesis")
    return cutoff


def build_ponzi_cohort(source, *, negative_count, seed, cutoffs):
    """Remove conflicts from both classes before label-blind negative sampling."""
    if not isinstance(negative_count, int) or isinstance(negative_count, bool) or negative_count < 10:
        raise ValueError("ponzi_negative_count_must_be_at_least_10")
    if set(cutoffs) != {"xblock_ponzi", "unica"}:
        raise ValueError("ponzi_requires_both_source_cutoffs")
    cutoffs = {name: parse_cutoff(value) for name, value in cutoffs.items()}
    source = Path(source)
    inspection, _ = inspect_source_snapshot(source)
    records = import_labels("xblock_ponzi", source / "Ponzi_label.csv", "ponzi")
    records += import_labels("unica", source / "cross_reference/unica_ponzi-addresses.csv", "ponzi")
    grouped = defaultdict(list)
    invalid = []
    for record in records:
        if record["entity_id"] is None or record["label_status"] == "invalid":
            invalid.append(record)
        else:
            grouped[record["entity_id"]].append(record)
    conflicts = sorted(entity for entity, rows in grouped.items() if len({r["mapped_label"] for r in rows}) > 1)
    invalid_entities = {r["entity_id"] for r in invalid if r["entity_id"]}
    excluded = set(conflicts) | invalid_entities
    positives = sorted(entity for entity, rows in grouped.items()
                       if entity not in excluded and any(r["mapped_label"] == 1 for r in rows))
    negatives = sorted(entity for entity, rows in grouped.items()
                       if entity not in excluded and any(r["source_id"] == "xblock_ponzi" and r["mapped_label"] == 0 for r in rows))
    if len(positives) < 10 or len(negatives) < negative_count:
        raise ValueError("insufficient_ponzi_positive_or_xblock_negative_addresses")
    rank = lambda entity: (_digest(["ponzi-negative", seed, entity]), entity)
    selected_negatives = sorted(negatives, key=rank)[:negative_count]
    source_sha = sha256_file(source / "manifest.json")
    cohort_id = "ponzi-" + _digest([source_sha, cutoffs, seed, negative_count, positives, selected_negatives])[:20]
    targets, evidence, negative_set = [], [], set(selected_negatives)
    seen_evidence = set()
    for entity in positives + selected_negatives:
        rows = grouped[entity]
        # Shared positives have one graph and use the primary labeled source.
        primary = "xblock_ponzi" if any(r["source_id"] == "xblock_ponzi" for r in rows) else "unica"
        targets.append({"sample_id": f"ponzi:1:{entity}", "task_id": "ponzi", "chain_id": 1,
                        "target": entity, "role": "target_contract", "cutoff": cutoffs[primary],
                        "cutoff_source": primary, "cohort_id": cohort_id, "source_snapshot": source_sha})
        for record in rows:
            key = (entity, record["source_id"], record["mapped_label"])
            if key in seen_evidence:
                continue
            seen_evidence.add(key)
            evidence.append(dict(record, audit_decision="admitted",
                label_status="supported_negative" if entity in negative_set else "supported_positive",
                label_version="ponzi-source-reviewed-1", source_file=record["source_id"],
                evidence_ref=f"{source_sha}:{record['source_id']}:row={record['source_row']}",
                audit_basis="user_adopted_source_defined_retrospective_contract_labels",
                valid_from=None, valid_to=None, label_available_at=None))
    report = {"version": "ponzi-cohort-1", "cohort_id": cohort_id, "source_sha256": source_sha,
              "seed": seed, "negative_count_requested": negative_count,
              "positive_union_before_conflict_exclusion": len({r["entity_id"] for r in records if r["mapped_label"] == 1 and r["entity_id"]}),
              "positive_count": len(positives), "negative_count": len(selected_negatives),
              "available_nonconflicting_xblock_negatives": len(negatives), "target_count": len(targets),
              "excluded_conflicting_addresses": conflicts,
              "invalid_source_records": [{k: r[k] for k in ("entity_id", "source_id", "source_row", "source_label", "audit_decision")} for r in invalid],
              "source_cutoffs": cutoffs, "cutoff_source_counts": dict(Counter(t["cutoff_source"] for t in targets)),
              "positive_cutoff_source_counts": dict(Counter(t["cutoff_source"] for t in targets if t["target"] not in negative_set)),
              "selection": "all distinct nonconflicting source positives; seeded hash sample of XBlock negatives before observing graphs",
              "cutoff_policy": "source-date UTC end-of-day retrospective anchors, not per-contract incident times",
              "duplicate_positive_policy": "one graph per entity; XBlock cutoff takes priority; retain both evidence sources",
              "label_semantics": "source-defined supervised Ponzi/non-Ponzi, with unknown per-contract validity and availability times",
              "source_inspection": inspection}
    return targets, evidence, report


def _address_exports(out, targets, evidence, *, dry_run):
    labels = {r["entity_id"]: r["mapped_label"] for r in evidence}
    content = {}
    for label, name in ((1, "scam_addresses.txt"), (0, "negative_addresses.txt")):
        content[name] = "\n".join(sorted(t["target"] for t in targets if labels[t["target"]] == label)) + "\n"
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["address", "training_target", "label_status", "cutoff_source", "cutoff"])
    for target in targets:
        label = labels[target["target"]]
        writer.writerow([target["target"], label, "supported_positive" if label else "supported_negative",
                         target["cutoff_source"], target["cutoff"]])
    content["address_labels.csv"] = stream.getvalue()
    hashes = {}
    for name, value in content.items():
        data = value.encode()
        path = out / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError("ponzi_address_export_changed")
        if not dry_run and not path.exists():
            atomic_bytes(path, data)
        # Match the normal SHA256 file checksum, not the JSON recipe digest.
        hashes[name] = hashlib.sha256(data).hexdigest()
    return hashes


def prepare_ponzi(out, config, *, stage="all", settings=None, source_snapshot=None,
                  negative_count=None, source_cutoffs=None, allow_network=False,
                  progress="auto", dry_run=False, drop_failed=False):
    if stage not in STAGES:
        raise ValueError("unsupported_ponzi_preparation_stage")
    out = Path(out)
    settings = copy.deepcopy(settings or {})
    _check_settings(settings)
    if set(settings) - {"collection", "observation_root"}:
        raise ValueError("unsupported_ponzi_settings")
    from .compaction import require_finished_compaction
    require_finished_compaction(out)
    frozen_path = out / "cohort/manifest.json"
    frozen = load_json(frozen_path) if frozen_path.exists() else None
    effective = validate_config(config)
    if effective["task_id"] != "ponzi" or effective["experiment_mode"] not in {"supervised", "supervised_binary"} or effective["training_as_of"] is not None:
        raise ValueError("ponzi_pipeline_requires_retrospective_supervised_config")
    cutoffs = dict(effective.get("source_cutoffs", {}))
    cutoffs.update(source_cutoffs or {})
    effective["source_cutoffs"] = {name: parse_cutoff(value) for name, value in cutoffs.items()}
    effective["negative_count"] = negative_count if negative_count is not None else effective.get("negative_count", 1000)
    if set(effective["source_cutoffs"]) != {"xblock_ponzi", "unica"}:
        raise ValueError("ponzi_requires_both_source_cutoffs")
    effective["graph"]["window_days"] = math.ceil((max(effective["source_cutoffs"].values()) - ETHEREUM_GENESIS_TIMESTAMP + 1) / 86400)
    graph = effective["graph"]
    collection = {**effective["collection"], **settings.get("collection", {})}
    if frozen:
        collection = {**frozen["collection"], **settings.get("collection", {})}
    collection.pop("shared_cache_dir", None)
    if (graph.get("sampling_mode") != RECENT_SAMPLING or graph["hops"] != 2
            or graph["rows_per_action"] != collection["page_size"]
            or graph["pages_per_action"] != collection["max_pages"]):
        raise ValueError("ponzi_recent_graph_collection_recipe_mismatch")
    source = Path(source_snapshot) if source_snapshot else (out / "sources" if (out / "sources/manifest.json").exists() else DEFAULT_SOURCES)
    freeze_source_snapshot(source, out / "sources", dry_run=dry_run)
    read_source = source if dry_run else out / "sources"
    paths = {name: str((out / name).resolve()) for name in ("sources", "cohort", "collection", "prepared")}
    if stage == "sources":
        return {"status": "planned" if dry_run else "sources_ready", "paths": paths, "fitting_performed": False}
    if stage in {"collect", "prepare"} and not frozen:
        raise ValueError("ponzi_address_cohort_required_run_stage_addresses_first")
    targets, evidence, cohort = build_ponzi_cohort(read_source, negative_count=effective["negative_count"],
        seed=effective["seed"], cutoffs=effective["source_cutoffs"])
    targets = [dict(t, observation_start=t["cutoff"] - graph["window_days"] * 86400) for t in targets]
    contract = {"version": "ponzi-recent-cohort-1", "config": effective, "cohort": cohort,
                "collection": _public_settings(collection),
                "fixtures_sha256": _digest(collection.get("fixtures")),
                "address_lists": _address_exports(out / "cohort", targets, evidence, dry_run=dry_run)}
    if frozen and frozen != contract:
        raise ValueError("ponzi_snapshot_inputs_changed_use_a_new_snapshot")
    for name, rows in (("targets", targets), ("evidence", evidence)):
        path = out / "cohort" / f"{name}.jsonl"
        if path.exists() and read_records(path) != rows:
            raise ValueError("ponzi_frozen_cohort_rows_changed")
        if not dry_run:
            _freeze_rows(path, rows)
    if not dry_run:
        _freeze_json(frozen_path, contract)
        _freeze_json(out / "cohort/training_config.json", effective)
    if dry_run and stage != "prepare":
        return {"status": "planned", "cohort": cohort, "paths": paths,
                "queries_per_sample_upper_bound": (1 + graph["fanouts"][0]) * 2 * graph["pages_per_action"],
                "network_performed": False, "fitting_performed": False}
    if stage == "cohort":
        return {"status": "cohort_ready", "cohort": cohort, "paths": paths, "fitting_performed": False}
    if stage in {"collect", "all"}:
        report = _collect_samples(out, targets, effective, collection, allow_network=allow_network,
            progress=progress, observation_root=settings.get("observation_root", SHARED_OBSERVATIONS))
        if not report["complete"] and not (drop_failed and stage == "all"):
            return {"status": "collection_incomplete", "collection": report, "paths": paths,
                    "resume": "repeat the same snapshot; preserve successful samples and failed scratch", "fitting_performed": False}
        if stage == "collect":
            return {"status": "collected", "collection": report, "paths": paths, "fitting_performed": False}
    result = prepare_collected_samples(out, targets, evidence, effective, collection, drop_failed=drop_failed, dry_run=dry_run)
    result["paths"] = paths
    return result
