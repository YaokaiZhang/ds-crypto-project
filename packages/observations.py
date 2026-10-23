"""Reusable compact chain observations, independent of labels and task weights."""
import hashlib
import json
from pathlib import Path
import tempfile

from .io import gzip_content_sha256, load_json, read_records, save_json, sha256_file, write_records


def verify_observation(directory, reference=None):
    """Validate a pinned replay dependency without materializing event records."""
    directory = Path(directory)
    if reference and sha256_file(directory / "manifest.json") != reference["manifest_sha256"]:
        raise ValueError("shared_observation_manifest_checksum_mismatch")
    manifest = load_json(directory / "manifest.json")
    names = set(manifest.get("artifacts", {}))
    event_name = "events.jsonl.gz" if "events.jsonl.gz" in names else "events.jsonl"
    if names != {event_name, "coverage.json", "normalization_audit.json"}:
        raise ValueError("shared_observation_artifacts_missing")
    if event_name.endswith(".gz") and not manifest.get("events_uncompressed_sha256"):
        raise ValueError("shared_observation_logical_checksum_missing")
    for name, digest in manifest["artifacts"].items():
        if sha256_file(directory / name) != digest:
            raise ValueError("shared_observation_checksum_mismatch")
    return manifest, directory / event_name


def read_sample_events(directory):
    """Resolve old local JSONL, local gzip, or the pinned shared observation."""
    directory = Path(directory)
    manifest = load_json(directory / "manifest.json")
    if manifest.get("event_storage") == "shared_observation":
        reference = manifest["shared_observation"]
        _, path = verify_observation(reference["path"], reference)
    else:
        name = "events.jsonl.gz" if "events.jsonl.gz" in manifest["artifacts"] else "events.jsonl"
        path = directory / name
        if sha256_file(path) != manifest["artifacts"][name]:
            raise ValueError("sample_artifact_checksum_mismatch")
    return read_records(path)


class ObservationStore:
    def __init__(self, root, collection):
        self.root = Path(root)
        self.collection = collection
        self.enabled = not bool(collection.get("transport"))
        fixtures = collection.get("fixtures")
        if collection.get("fixture_dir"):
            fixture_files = {p.name: sha256_file(p) for p in sorted(Path(collection["fixture_dir"]).glob("*.json"))}
            fixtures = {"inline": fixtures, "files": fixture_files}
        self.origin = ("fixture-" + hashlib.sha256(json.dumps(fixtures, sort_keys=True).encode()).hexdigest()
                       if fixtures else "etherscan-network")

    def specification(self, target, graph, end_block):
        return {"version": "bounded-eth-observation-1", "chain_id": 1,
                "address": target["target"], "cutoff": target["cutoff"], "cutoff_block": end_block,
                "graph_query_recipe": graph, "origin": self.origin,
                "endpoint": self.collection.get("endpoint", "https://api.etherscan.io/v2/api"),
                "actions": sorted(self.collection["actions"])}

    def path(self, specification):
        digest = hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()
        return self.root / digest

    def read(self, specification):
        if not self.enabled:
            return None
        directory = self.path(specification)
        if not (directory / "manifest.json").exists():
            return None
        manifest, events_path = verify_observation(directory)
        if manifest.get("specification") != specification:
            raise ValueError("shared_observation_specification_mismatch")
        return (read_records(events_path), load_json(directory / "coverage.json"),
                load_json(directory / "normalization_audit.json"),
                {"path": str(directory.resolve()), "manifest_sha256": sha256_file(directory / "manifest.json")})

    def publish(self, specification, events, coverage, audit):
        if not coverage.get("complete") or not audit.get("complete"):
            raise ValueError("cannot_share_incomplete_chain_observation")
        if any(set(event) & {"task_id", "sample_id", "label", "mapped_label", "label_status", "cohort_id"} for event in events):
            raise ValueError("task_labels_must_not_enter_shared_observations")
        if not self.enabled:
            return events, coverage, audit, None
        directory = self.path(specification)
        self.root.mkdir(parents=True, exist_ok=True)
        if not (directory / "manifest.json").exists():
            with tempfile.TemporaryDirectory(prefix=".observation-build-", dir=self.root) as temporary:
                build = Path(temporary) / "observation"
                write_records(build / "events.jsonl.gz", events)
                save_json(build / "coverage.json", coverage)
                save_json(build / "normalization_audit.json", audit)
                save_json(build / "manifest.json", {"specification": specification,
                    "storage_version": "gzip-events-1",
                    "events_uncompressed_sha256": gzip_content_sha256(build / "events.jsonl.gz"),
                    "retention": "normalized_replay_inputs_only_no_raw_responses",
                    "artifacts": {name: sha256_file(build / name) for name in
                        ("events.jsonl.gz", "coverage.json", "normalization_audit.json")}})
                build.rename(directory)
        return self.read(specification)
