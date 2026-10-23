"""Offline, lossless migration from duplicated replay inputs to shared gzip.

The durable plan contains original manifests, not transaction copies. Each item
can be replayed after interruption; no source is unlinked before both manifests
pin a verified gzip containing exactly the original bytes.
"""
import copy
import hashlib
import json
from pathlib import Path
import zlib

from packages.io import atomic_bytes, compress_file, gzip_content_sha256, load_json, sha256_file
from packages.observations import verify_observation
from .execution import snapshot_lock


JOURNAL = "storage_migrations/shared-gzip-v1"


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _save(path, value):
    atomic_bytes(path, _bytes(value))


def _sha(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def require_finished_compaction(out):
    journal = Path(out) / JOURNAL
    if (journal / "plan.json").exists() and not (journal / "complete.json").exists():
        raise ValueError("storage_compaction_unfinished_resume_scripts/scam/compact_storage.py")


def _check_files(directory, artifacts):
    for name, digest in artifacts.items():
        if name not in {"events.jsonl", "events.jsonl.gz", "graph.json", "target.json",
                        "normalization_audit.json", "coverage.json"}:
            raise ValueError("unsupported_compaction_artifact")
        if sha256_file(directory / name) != digest:
            raise ValueError("compaction_artifact_checksum_mismatch")


def _managed_bytes(out, entries):
    roots = {out / "collection/samples"}
    roots.update(Path(entry["shared_path"]) for entry in entries)
    return sum(p.stat().st_size for root in roots for p in root.rglob("*") if p.is_file())


def _plan(out, progress):
    if (out / "prepared/dataset_manifest.json").exists():
        raise ValueError("compaction_requires_pre_preparation_snapshot_preserve_published_training_provenance")
    collection_path = out / "collection/manifest.json"
    collection = load_json(collection_path)
    if collection.get("version") != "recent-collection-2":
        raise ValueError("compaction_requires_bounded_recent_collection")
    indexed = {entry["key"] for entry in collection["samples"]}
    published = {p.parent.name for p in (out / "collection/samples").glob("*/manifest.json")
                 if not p.parent.name.startswith(".")}
    if indexed != published:
        raise ValueError("recover_collection_index_before_compaction")
    entries, verified = [], {}
    for number, index in enumerate(collection["samples"], 1):
        key = index["key"]
        if Path(key).name != key or key in {".", ".."}:
            raise ValueError("invalid_compaction_sample_key")
        directory = out / "collection/samples" / key
        if sha256_file(directory / "manifest.json") != index["manifest_sha256"]:
            raise ValueError("collection_sample_manifest_mismatch")
        sample = load_json(directory / "manifest.json")
        _check_files(directory, sample["artifacts"])
        reference = sample.get("shared_observation")
        if not reference:
            raise ValueError("compaction_requires_existing_shared_observation")
        shared = Path(reference["path"]).resolve()
        if shared == directory.resolve() or directory.resolve() in shared.parents:
            raise ValueError("invalid_shared_observation_path")
        if str(shared) not in verified:
            observation, event_path = verify_observation(shared)
            logical_sha = (gzip_content_sha256(event_path) if event_path.suffix == ".gz"
                           else observation["artifacts"]["events.jsonl"])
            if event_path.suffix == ".gz" and logical_sha != observation["events_uncompressed_sha256"]:
                raise ValueError("shared_observation_logical_checksum_mismatch")
            verified[str(shared)] = observation, logical_sha
        observation, logical_sha = verified[str(shared)]
        local_events = sample["artifacts"].get("events.jsonl")
        current_observation_sha = sha256_file(shared / "manifest.json")
        if reference["manifest_sha256"] != current_observation_sha:
            # A different legacy snapshot may already have compacted this shared
            # object. Reconstruct its old storage manifest and prove the old pin;
            # never accept a general manifest mismatch just because rows match.
            legacy = copy.deepcopy(observation)
            if local_events is None or "events.jsonl.gz" not in legacy["artifacts"]:
                raise ValueError("shared_observation_manifest_checksum_mismatch")
            legacy.pop("storage_version", None)
            legacy.pop("events_uncompressed_sha256", None)
            legacy["artifacts"].pop("events.jsonl.gz")
            legacy["artifacts"]["events.jsonl"] = logical_sha
            legacy_sha = _sha(legacy)
            # The original publisher wrote events first. Some imported legacy
            # manifests wrote it last; accept only an exact old byte digest.
            legacy["artifacts"] = {name: legacy["artifacts"][name] for name in
                                   ("events.jsonl", "coverage.json", "normalization_audit.json")}
            if reference["manifest_sha256"] not in {legacy_sha, _sha(legacy)}:
                raise ValueError("shared_observation_manifest_checksum_mismatch")
        if local_events is not None and local_events != logical_sha:
            raise ValueError("compaction_local_shared_events_differ")
        if local_events is None and sample.get("event_storage") != "shared_observation":
            raise ValueError("unsupported_compaction_event_storage")
        entries.append({"key": key, "sample": sample, "sample_sha256": index["manifest_sha256"],
                        "shared_path": str(shared), "observation": observation,
                        "observation_sha256": current_observation_sha, "events_sha256": logical_sha})
        if progress:
            progress("verify", number, len(collection["samples"]))
    return {"version": "shared-gzip-v1", "snapshot": str(out.resolve()),
            "original_collection": collection, "original_collection_sha256": sha256_file(collection_path),
            "entries": entries, "before_managed_bytes": _managed_bytes(out, entries)}


def _compact_entry(out, entry):
    directory = out / "collection/samples" / entry["key"]
    shared = Path(entry["shared_path"])
    original = entry["observation"]
    compressed = shared / "events.jsonl.gz"
    logical_sha = entry["events_sha256"]
    # All untouched local inputs must still match the preflight plan.
    _check_files(directory, {k: v for k, v in entry["sample"]["artifacts"].items() if k != "events.jsonl"})
    _check_files(shared, {k: v for k, v in original["artifacts"].items() if not k.startswith("events.")})
    observation_sha = sha256_file(shared / "manifest.json")
    if observation_sha == entry["observation_sha256"] and "events.jsonl" in original["artifacts"]:
        _check_files(shared, {"events.jsonl": logical_sha})
        # An interrupted unpublished gzip can be regenerated from the intact source.
        if not compressed.exists():
            compress_file(shared / "events.jsonl", compressed)
        try:
            valid = gzip_content_sha256(compressed) == logical_sha
        except (OSError, EOFError, zlib.error):
            valid = False
        if not valid:
            compress_file(shared / "events.jsonl", compressed)
    if gzip_content_sha256(compressed) != logical_sha:
        raise ValueError("compaction_gzip_not_lossless")
    observation = copy.deepcopy(original)
    if "events.jsonl" in observation["artifacts"]:
        del observation["artifacts"]["events.jsonl"]
        observation["artifacts"]["events.jsonl.gz"] = sha256_file(compressed)
        observation.update(storage_version="gzip-events-1", events_uncompressed_sha256=logical_sha)
    if observation_sha not in {entry["observation_sha256"], _sha(observation)}:
        raise ValueError("compaction_shared_manifest_changed")
    if observation_sha != _sha(observation):
        _save(shared / "manifest.json", observation)
    reference = {"path": str(shared), "manifest_sha256": _sha(observation)}
    verify_observation(shared, reference)
    sample = copy.deepcopy(entry["sample"])
    sample.update(version="recent-sample-3", event_storage="shared_observation", shared_observation=reference)
    sample["artifacts"].pop("events.jsonl", None)
    sample_sha = sha256_file(directory / "manifest.json")
    if sample_sha not in {entry["sample_sha256"], _sha(sample)}:
        raise ValueError("compaction_sample_manifest_changed")
    if sample_sha != _sha(sample):
        _save(directory / "manifest.json", sample)
    # Publication and physical + logical verification precede every deletion.
    for source in (directory / "events.jsonl", shared / "events.jsonl"):
        if source.exists():
            if sha256_file(source) != logical_sha:
                raise ValueError("compaction_refusing_to_delete_changed_events")
            source.unlink()
    return _sha(sample)


def compact_snapshot(out, *, dry_run=False, progress=None):
    """Migrate before dataset preparation. Rerun the same command after a crash."""
    out = Path(out).resolve()
    if not (out / "collection/manifest.json").is_file():
        raise ValueError("collection_manifest_required_before_compaction")
    with snapshot_lock(out):
        journal = out / JOURNAL
        if (journal / "complete.json").exists():
            return {**load_json(journal / "complete.json"), "status": "already_compacted"}
        plan_path = journal / "plan.json"
        plan = load_json(plan_path) if plan_path.exists() else _plan(out, progress)
        if plan["snapshot"] != str(out):
            raise ValueError("compaction_snapshot_path_changed")
        if dry_run:
            return {"status": "planned", "samples": len(plan["entries"]),
                    "before_managed_bytes": plan["before_managed_bytes"], "network_performed": False}
        if not plan_path.exists():
            _save(plan_path, plan)
        collection = copy.deepcopy(plan["original_collection"])
        try:
            for number, (entry, index) in enumerate(zip(plan["entries"], collection["samples"]), 1):
                index["manifest_sha256"] = _compact_entry(out, entry)
                if progress:
                    progress("compact", number, len(plan["entries"]))
                if number % 25 == 0:
                    _save(journal / "progress.json", {"status": "running", "completed": number,
                                                       "total": len(plan["entries"])})
            collection_path = out / "collection/manifest.json"
            if sha256_file(collection_path) not in {plan["original_collection_sha256"], _sha(collection)}:
                raise ValueError("compaction_collection_manifest_changed")
            _save(collection_path, collection)
            report = {"status": "compacted", "samples": len(plan["entries"]),
                      "before_managed_bytes": plan["before_managed_bytes"],
                      "after_managed_bytes": _managed_bytes(out, plan["entries"]),
                      "collection_sha256": sha256_file(collection_path),
                      "graph_bytes_unchanged": True, "event_bytes_lossless": True,
                      "network_performed": False, "failed_scratch_retained": True}
            report["reclaimed_bytes"] = report["before_managed_bytes"] - report["after_managed_bytes"]
            _save(journal / "progress.json", report)
            _save(journal / "complete.json", report)
            return report
        except BaseException as error:
            _save(journal / "progress.json", {"status": "interrupted" if isinstance(error, KeyboardInterrupt) else "error",
                                              "error_type": type(error).__name__, "resume": "repeat the same compaction command"})
            raise
