"""Content-addressed, task-neutral candidate address pools."""
from pathlib import Path
import re
import tempfile

from ..io import atomic_bytes, load_json, read_records, save_json, sha256_file, write_records
from ..transactions import address


def load_address_pool(directory):
    directory = Path(directory)
    manifest = load_json(directory / "manifest.json")
    if manifest.get("version") != "unlabeled-address-pool-1" or manifest.get("chain_id") != 1:
        raise ValueError("unsupported_shared_address_pool")
    if set(manifest.get("artifacts", {})) != {"source.txt", "addresses.txt", "addresses.jsonl"}:
        raise ValueError("shared_address_pool_artifacts_missing")
    for name, digest in manifest["artifacts"].items():
        if name not in {"source.txt", "addresses.txt", "addresses.jsonl"} or sha256_file(directory / name) != digest:
            raise ValueError("shared_address_pool_checksum_mismatch")
    rows = read_records(directory / "addresses.jsonl")
    if len(rows) != manifest["addresses"] or any(row.get("label_status") != "unlabeled" or "task_id" in row for row in rows):
        raise ValueError("invalid_shared_address_pool_records")
    return rows, manifest


def freeze_address_pool(input_path, source, shared_root):
    """Preserve all valid candidates; task-specific exclusions belong to cohorts."""
    if not re.fullmatch(r"[a-z0-9_-]+", source["source_id"]):
        raise ValueError("invalid_address_pool_source_id")
    data = Path(input_path).read_bytes()
    if sha256_file(input_path) != source["sha256"]:
        raise ValueError("address_pool_source_checksum_mismatch")
    directory = Path(shared_root) / f"{source['source_id']}-{source['sha256'][:20]}"
    if not (directory / "manifest.json").exists():
        values = sorted({entity for line in data.decode("utf-8-sig").splitlines() if (entity := address(line.strip()))})
        if not values:
            raise ValueError("empty_shared_address_pool")
        directory.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".address-pool-", dir=directory.parent) as temporary:
            build = Path(temporary) / "pool"
            atomic_bytes(build / "source.txt", data)
            atomic_bytes(build / "addresses.txt", ("\n".join(values) + "\n").encode())
            write_records(build / "addresses.jsonl", [{"chain_id": 1, "address": value,
                          "source_id": source["source_id"], "label_status": "unlabeled"} for value in values])
            save_json(build / "manifest.json", {"version": "unlabeled-address-pool-1", "chain_id": 1,
                      "source_id": source["source_id"], "source_sha256": source["sha256"],
                      "source_url": source["url"], "source_commit": source.get("commit"),
                      "first_retrieved_at": source.get("observed_at"), "addresses": len(values),
                      "meaning": "source-listed unlabeled candidates; no task label or universal benign claim",
                      "artifacts": {name: sha256_file(build / name) for name in ("source.txt", "addresses.txt", "addresses.jsonl")}})
            build.rename(directory)
    _, manifest = load_address_pool(directory)
    if manifest["source_sha256"] != source["sha256"]:
        raise ValueError("shared_address_pool_source_mismatch")
    return {"path": str(directory.resolve()), "manifest_sha256": sha256_file(directory / "manifest.json"),
            "source_sha256": source["sha256"], "addresses": manifest["addresses"]}
