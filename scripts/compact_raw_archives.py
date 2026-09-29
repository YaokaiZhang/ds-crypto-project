#!/usr/bin/env python3
"""Compact per-request raw JSON files into verified gzip JSONL bundles."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from pathlib import Path
from typing import Any

# Allow execution as ``python scripts/compact_raw_archives.py`` from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.week1_audit import archive_integrity, json_dump, read_json, read_jsonl, sha256_bytes


def verify_payload(payload: dict[str, Any]) -> None:
    response = payload.get("response", {})
    expected = response.get("body_sha256")
    actual = sha256_bytes(json_dump(response.get("body")).encode("utf-8"))
    if expected != actual:
        raise ValueError(
            f"raw response checksum mismatch: expected={expected!r} actual={actual!r}"
        )


def is_bundle_path(value: str) -> bool:
    return value.endswith(".jsonl.gz")


def compact_dataset(dataset: Path, *, cleanup: bool) -> dict[str, Any]:
    manifest_path = dataset / "manifests" / "request_log.jsonl"
    raw_dir = dataset / "raw"
    if not manifest_path.exists():
        return {"dataset": str(dataset), "status": "skipped_no_manifest"}
    rows = read_jsonl(manifest_path)
    if not rows:
        return {"dataset": str(dataset), "status": "skipped_empty_manifest"}
    raw_dir.mkdir(parents=True, exist_ok=True)

    bundle_rows = [row for row in rows if is_bundle_path(str(row.get("raw_path") or ""))]
    old_rows = [row for row in rows if not is_bundle_path(str(row.get("raw_path") or ""))]
    if bundle_rows and old_rows:
        raise ValueError(f"mixed bundled and per-file manifest rows: {dataset}")

    old_paths = {
        str(dataset / row["raw_path"])
        for row in old_rows
        if row.get("raw_path")
    }
    if not old_rows:
        removed = 0
        if cleanup:
            for path in raw_dir.glob("*.json"):
                if str(path) not in old_paths:
                    path.unlink()
                    removed += 1
        integrity = archive_integrity(dataset)
        return {
            "dataset": str(dataset),
            "status": "already_bundled",
            "manifest_rows": len(rows),
            "removed_unreferenced_json": removed,
            "integrity": integrity,
        }

    for row in old_rows:
        raw_path = dataset / str(row["raw_path"])
        if not raw_path.exists():
            raise FileNotFoundError(raw_path)

    bundle_path = raw_dir / "responses-compacted-000001.jsonl.gz"
    suffix = 1
    while bundle_path.exists():
        suffix += 1
        bundle_path = raw_dir / f"responses-compacted-{suffix:06d}.jsonl.gz"
    temporary_bundle = bundle_path.with_name(bundle_path.name + ".part")
    temporary_manifest = manifest_path.with_name(manifest_path.name + ".part")
    if temporary_bundle.exists():
        temporary_bundle.unlink()
    if temporary_manifest.exists():
        temporary_manifest.unlink()

    compacted_rows: list[dict[str, Any]] = []
    with gzip.open(temporary_bundle, "wt", encoding="utf-8") as handle:
        for line_number, row in enumerate(old_rows, start=1):
            payload = read_json(dataset / str(row["raw_path"]))
            verify_payload(payload)
            handle.write(json_dump(payload) + "\n")
            compacted = dict(row)
            compacted["raw_path"] = str(bundle_path.relative_to(dataset))
            compacted["raw_line"] = line_number
            compacted["raw_format"] = "jsonl.gz"
            compacted_rows.append(compacted)

    with gzip.open(temporary_bundle, "rt", encoding="utf-8") as handle:
        written = 0
        for line in handle:
            verify_payload(json.loads(line))
            written += 1
    if written != len(compacted_rows):
        raise ValueError(f"bundle line count mismatch for {dataset}: {written} != {len(compacted_rows)}")

    os.replace(temporary_bundle, bundle_path)
    with temporary_manifest.open("w", encoding="utf-8") as handle:
        for row in compacted_rows:
            handle.write(json_dump(row) + "\n")
    os.replace(temporary_manifest, manifest_path)

    integrity = archive_integrity(dataset)
    if integrity["missing_raw_files"] or integrity["checksum_failures"]:
        raise ValueError(f"post-compaction integrity failure for {dataset}: {integrity}")

    removed = 0
    if cleanup:
        for raw_path_value in old_paths:
            raw_path = Path(raw_path_value)
            if raw_path.exists():
                raw_path.unlink()
                removed += 1
    final_integrity = archive_integrity(dataset)
    return {
        "dataset": str(dataset),
        "status": "compacted",
        "manifest_rows": len(rows),
        "bundle": str(bundle_path.relative_to(dataset)),
        "removed_json_files": removed,
        "integrity": final_integrity,
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--dataset", action="append")
    parser.add_argument("--cleanup", action="store_true")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    if args.dataset:
        datasets = [Path(value).resolve() for value in args.dataset]
    else:
        root = Path(args.data_root).resolve()
        datasets = sorted({path.parent.parent for path in root.glob("*/manifests/request_log.jsonl")})
    try:
        for dataset in datasets:
            print(json.dumps(compact_dataset(dataset, cleanup=args.cleanup), sort_keys=True))
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
