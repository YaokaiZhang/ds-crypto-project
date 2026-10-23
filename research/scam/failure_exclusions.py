"""Freeze audited collection failures without changing cohort or graph inputs."""
import hashlib
from pathlib import Path

from packages.collection import _now
from packages.io import atomic_bytes, load_json, save_json, sha256_file


def sample_key(target):
    return hashlib.sha256(target["sample_id"].encode()).hexdigest()[:24]


def _paths(out):
    root = Path(out) / "collection"
    return root, root / "failure_exclusions.json", root / "pre_exclusion_manifest.json"


def load_exclusions(out, targets, expected):
    root, path, original = _paths(out)
    if not path.exists():
        return []
    ledger = load_json(path)
    current = load_json(root / "manifest.json")
    if current.get("failure_exclusions_sha256") not in (None, sha256_file(path)):
        raise ValueError("failure_exclusions_manifest_checksum_mismatch")
    if ledger.get("version") != "collection-failure-exclusions-1":
        raise ValueError("unsupported_failure_exclusions_version")
    if sha256_file(Path(out) / "cohort/manifest.json") != ledger["cohort_sha256"]:
        raise ValueError("failure_exclusions_cohort_checksum_mismatch")
    if sha256_file(original) != ledger["source_collection_sha256"]:
        raise ValueError("failure_exclusions_source_checksum_mismatch")
    source = load_json(original)
    published = {row["sample_id"] for row in source["samples"]}
    failures = {row["sample_id"]: row for row in source.get("coverage", [])}
    target_map = {sample_key(t): t for t in targets}
    seen = set()
    for row in ledger["excluded"]:
        key = row["key"]
        target = target_map.get(key)
        if key in seen or target is None or row["sample_id"] != target["sample_id"] or row["target"] != target["target"]:
            raise ValueError("failure_exclusions_target_mismatch")
        seen.add(key)
        if row["input_sha256"] != expected[key]:
            raise ValueError("failure_exclusions_inputs_changed")
        if row["sample_id"] in published or (root / "samples" / key / "manifest.json").exists():
            raise ValueError("cannot_exclude_published_sample")
        failure = failures.get(row["sample_id"])
        if not failure or failure["failure"] != row["failure"] or failure["target"] != row["target"]:
            raise ValueError("failure_exclusions_source_failure_mismatch")
        failure_path = root / "failures" / f"{key}.json"
        if sha256_file(failure_path) != row["failure_record_sha256"]:
            raise ValueError("failure_exclusions_failure_checksum_mismatch")
    return ledger["excluded"]


def freeze_exclusions(out, targets, expected, *, dry_run=False):
    root, path, original = _paths(out)
    if path.exists():
        return load_exclusions(out, targets, expected)
    report = load_json(root / "manifest.json")
    target_map = {t["sample_id"]: t for t in targets}
    published = {row["sample_id"] for row in report["samples"]}
    if len(published) != len(report["samples"]) or not published <= set(target_map):
        raise ValueError("collection_sample_index_invalid")
    # An interruption after publication can leave an old index; it must be
    # recovered before it can be used as evidence that a target failed.
    for index in report["samples"]:
        target = target_map[index["sample_id"]]
        if index["key"] != sample_key(target) or sha256_file(root / "samples" / index["key"] / "manifest.json") != index["manifest_sha256"]:
            raise ValueError("collection_sample_manifest_mismatch")
    failures = {row["sample_id"]: row for row in report.get("coverage", [])}
    excluded = []
    forbidden = ("checksum", "invalid_cached", "cached_provider", "invalid api", "invalid api-key",
                 "missing_etherscan", "missing_fixture", "authentication", "unauthorized", "forbidden", "api key", "api-key",
                 "rate limit", "rate_limit", "daily limit", "quota")
    for target in targets:
        if target["sample_id"] in published:
            continue
        key = sample_key(target)
        if (root / "samples" / key / "manifest.json").exists():
            raise ValueError("recover_collection_index_before_dropping_failures")
        failure = failures.get(target["sample_id"])
        if not failure or failure.get("target") != target["target"]:
            raise ValueError("cannot_drop_unattempted_or_unrecorded_target")
        reason = failure["failure"]
        if any(word in reason.lower() for word in forbidden):
            raise ValueError("cannot_drop_provider_or_integrity_failure")
        failure_path = root / "failures" / f"{key}.json"
        if load_json(failure_path) != failure:
            raise ValueError("collection_failure_record_mismatch")
        excluded.append({"sample_id": target["sample_id"], "target": target["target"], "key": key,
                         "input_sha256": expected[key], "status": "excluded_collection_failure",
                         "failure": reason, "failure_record_sha256": sha256_file(failure_path)})
    if not excluded:
        return []
    if (Path(out) / "prepared/dataset_manifest.json").exists():
        raise ValueError("cannot_change_failures_after_preparation_use_a_new_dataset_version")
    if dry_run:
        return excluded
    source_sha = sha256_file(root / "manifest.json")
    atomic_bytes(original, (root / "manifest.json").read_bytes(), immutable=True)
    if sha256_file(original) != source_sha:
        raise ValueError("failure_exclusions_source_checksum_mismatch")
    save_json(path, {"version": "collection-failure-exclusions-1", "created_at": _now(),
                     "policy": "explicit_drop_recorded_sample_failures_no_replacement_roots",
                     "cohort_sha256": sha256_file(Path(out) / "cohort/manifest.json"),
                     "source_collection_sha256": source_sha, "excluded": excluded})
    return load_exclusions(out, targets, expected)


def resolve_report(out, report, exclusions):
    if not exclusions:
        return report
    _, path, _ = _paths(out)
    digest = sha256_file(path)
    if report.get("failure_exclusions_sha256") not in (None, digest):
        raise ValueError("failure_exclusions_manifest_checksum_mismatch")
    dropped = {row["sample_id"] for row in exclusions}
    if dropped & {row["sample_id"] for row in report["samples"]}:
        raise ValueError("cannot_exclude_published_sample")
    remaining = report["target_count"] - report["sample_count"] - len(exclusions)
    if remaining < 0:
        raise ValueError("collection_exclusion_counts_invalid")
    active = [row for row in report.get("coverage", []) if row["sample_id"] not in dropped]
    return {**report, "version": "recent-collection-3", "complete": remaining == 0,
            "download_complete": report["sample_count"] == report["target_count"],
            "remaining_count": remaining, "failed_count": len(active), "coverage": active,
            "failure_excluded_count": len(exclusions), "excluded_failures": exclusions,
            "failure_exclusions_sha256": digest}
