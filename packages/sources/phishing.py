"""Frozen public phishing labels and deterministic background cohorts."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..io import atomic_bytes, load_json, save_json, sha256_file
from ..transactions import address


SOURCE_FILES = {
    "forta": ("forta-network/labelled-datasets", "labels/1/phishing_scams.csv", "forta", 1),
    "poison_hunter_background": ("DS2L/Poison-Hunter", "benign_addresses_on_etherscan.txt", "poison_hunter", None),
}


def _download(url: str, limit: int = 5 * 1024 * 1024) -> bytes:
    request = Request(url, headers={"User-Agent": "scam-phishing-data/0.1", "Accept": "application/json,text/plain"})
    try:
        with urlopen(request, timeout=30) as response:
            data = response.read(limit + 1)
    except OSError as error:
        raise ValueError(f"public_label_download_failed: {error}") from error
    if len(data) > limit:
        raise ValueError("label_download_size_limit")
    return data


def fetch_phishing_labels(out: str | Path, *, allow_network: bool = False,
                          local_files: dict | None = None,
                          positive_source: str = "forta",
                          source_as_of: int | None = None, dry_run: bool = False,
                          source_snapshot: str | Path | None = None) -> dict:
    """Freeze file bytes, source commits and hashes; never infer incident dates.

    The author-provided normal addresses remain an unlabeled background pool.
    Only Forta positives and Poison Hunter's ordinary-address list are used.
    """
    out = Path(out)
    local_files = dict(local_files or {})
    if positive_source != "forta":
        raise ValueError("unsupported_phishing_positive_source")
    if set(local_files) - set(SOURCE_FILES):
        raise ValueError("phishing_sources_only_accept_forta_and_poison_hunter_background")
    names = list(SOURCE_FILES)
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        if (manifest["source_names"] != names or manifest["positive_source"] != positive_source
                or source_as_of is not None and manifest["source_as_of"] != source_as_of):
            raise ValueError("source_snapshot_options_changed_use_a_new_snapshot")
        for item in manifest["files"]:
            if sha256_file(out / item["file"]) != item["sha256"]:
                raise ValueError("source_snapshot_checksum_mismatch")
            if item["name"] in local_files and sha256_file(local_files[item["name"]]) != item["sha256"]:
                raise ValueError("local_label_file_changed_use_a_new_snapshot")
        return manifest
    if dry_run:
        return {"status": "planned", "source_names": names, "network_performed": False,
                "output": str(out.resolve())}
    if source_snapshot is not None:
        if local_files:
            raise ValueError("source_snapshot_and_local_files_are_mutually_exclusive")
        original = Path(source_snapshot)
        previous = load_json(original / "manifest.json")
        if source_as_of is not None and source_as_of != previous["source_as_of"]:
            raise ValueError("reused_source_cutoff_must_match")
        files = []
        for name in names:
            item = next(row for row in previous["files"] if row["name"] == name)
            data = (original / item["file"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("source_snapshot_checksum_mismatch")
            parse_phishing_records(data.decode("utf-8-sig"), item)
            out.mkdir(parents=True, exist_ok=True)
            destination = out / item["file"]
            if destination.exists() and destination.read_bytes() != data:
                raise ValueError("source_file_changed_use_a_new_snapshot")
            atomic_bytes(destination, data)
            files.append(item)
        manifest = {"version": "phishing-source-snapshot-2", "source_names": names, "files": files,
                    "source_as_of": previous["source_as_of"], "positive_source": "forta",
                    "observed_at": previous["observed_at"],
                    "background_meaning": "author-labelled normal addresses treated as unlabeled; not guaranteed benign"}
        save_json(manifest_path, manifest)
        return manifest
    if not allow_network and any(name not in local_files for name in names):
        raise ValueError("label_download_requires_allow_network_or_local_files")
    files, cutoffs = [], []
    observed_at = datetime.now(timezone.utc).isoformat()
    for name in names:
        repo, source_path, source, polarity = SOURCE_FILES[name]
        commit, commit_at = None, None
        if name in local_files:
            data = Path(local_files[name]).read_bytes()
            url = f"https://github.com/{repo}"
            cutoff = source_as_of if source_as_of is not None else int(datetime.fromisoformat(observed_at).timestamp())
            basis = "explicit_source_as_of" if source_as_of is not None else "local_snapshot_capture"
        else:
            metadata_url = f"https://api.github.com/repos/{repo}/commits?path={quote(source_path, safe='')}&per_page=1"
            commits = json.loads(_download(metadata_url))
            if not isinstance(commits, list) or not commits:
                raise ValueError("missing_label_file_commit")
            commit = commits[0]["sha"]
            if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
                raise ValueError("invalid_label_file_commit")
            commit_at = commits[0]["commit"]["committer"]["date"]
            url = f"https://raw.githubusercontent.com/{repo}/{commit}/{source_path}"
            data = _download(url)
            cutoff = source_as_of if source_as_of is not None else int(datetime.fromisoformat(commit_at.replace("Z", "+00:00")).timestamp())
            basis = "explicit_source_as_of" if source_as_of is not None else "source_file_commit"
        if cutoff < 0 or len(data) > 5 * 1024 * 1024:
            raise ValueError("invalid_source_snapshot")
        filename = name + (".csv" if name == "forta" else ".txt")
        item = {"name": name, "source_id": source, "polarity": polarity, "file": filename,
                "url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "commit": commit, "file_committed_at": commit_at, "observed_at": observed_at,
                "data_as_of": cutoff, "as_of_basis": basis, "transport": "local" if name in local_files else "https"}
        # Verify text/schema before persisting a source snapshot.
        parse_phishing_records(data.decode("utf-8-sig"), item)
        out.mkdir(parents=True, exist_ok=True)
        destination = out / filename
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError("source_file_changed_use_a_new_snapshot")
        atomic_bytes(destination, data)
        files.append(item)
        if name == "forta":
            cutoffs.append(cutoff)
    manifest = {"version": "phishing-source-snapshot-2", "source_names": names, "files": files,
                "source_as_of": source_as_of if source_as_of is not None else min(cutoffs),
                "positive_source": positive_source,
                "observed_at": observed_at,
                "background_meaning": "author-labelled normal addresses treated as unlabeled; not guaranteed benign"}
    save_json(manifest_path, manifest)
    return manifest


def parse_phishing_records(text: str, source: dict) -> list[dict]:
    name = source["name"]
    if name == "forta":
        reader = csv.DictReader(io.StringIO(text))
        if not {"address", "etherscan_tag", "etherscan_labels", "is_contract"}.issubset(reader.fieldnames or []):
            raise ValueError("invalid_forta_label_schema")
        rows = list(reader)
    else:
        rows = [{"address": value.strip()} for value in text.splitlines() if value.strip()]
    result = []
    for number, row in enumerate(rows, 1):
        entity = address(row.get("address"))
        polarity = source["polarity"]
        accepted = bool(entity)
        training_positive = True
        if name == "forta":
            # Broad phish-hack tags can include affected legitimate contracts.
            # Named phishing tags provide an explicit source role; retain all
            # other entries for conflict/background exclusion only.
            accepted = accepted and "phish" in str(row["etherscan_labels"]).lower()
            training_positive = bool(re.match(r"^(?:fake[_ ]phishing|phishing)[_ ]?\d+$", str(row["etherscan_tag"]).strip(), re.I))
        result.append({"task_id": "phishing", "entity_id": entity, "mapped_label": polarity,
                       "label_status": "supported_positive" if accepted and polarity == 1 else "unlabeled" if accepted else "invalid",
                       "role": "phishing_address" if polarity == 1 else "unknown",
                       "audit_decision": "accepted" if accepted else "invalid_source_address_or_label",
                       "admission_basis": "published_source_label", "evidence_ref": source["url"] + f"#row={number}",
                       "source_id": source["source_id"], "source_row": number, "source_sha256": source["sha256"],
                       "label_version": source.get("commit") or source["sha256"],
                       "label_available_at": None, "valid_from": None, "valid_to": None,
                       "raw_record": row, "source_file": name, "training_positive": training_positive})
    if not result:
        raise ValueError("empty_label_source")
    return result
