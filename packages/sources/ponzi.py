"""Verify and reuse immutable XBlock/Unica source files without network access."""
from collections import Counter, defaultdict
import csv
import io
from pathlib import Path
import zipfile

from ..io import atomic_bytes, load_json, sha256_file
from ..labeling import import_labels
from ..transactions import address


def freeze_source_snapshot(source, destination, *, dry_run=False):
    """Copy verified source bytes once; resumes verify the complete source tree."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    summary, records = inspect_source_snapshot(source)
    manifest = load_json(source / "manifest.json")
    if (destination / "manifest.json").exists():
        if sha256_file(destination / "manifest.json") != sha256_file(source / "manifest.json"):
            raise ValueError("ponzi_source_snapshot_changed_use_a_new_snapshot")
        inspect_source_snapshot(destination)
        return summary, records
    if not dry_run:
        for name in [*manifest["files"], "manifest.json"]:
            data = (source / name).read_bytes()
            path = destination / name
            if path.exists() and path.read_bytes() != data:
                raise ValueError("ponzi_source_file_changed_use_a_new_snapshot")
            if not path.exists():
                atomic_bytes(path, data)
        inspect_source_snapshot(destination)
    return summary, records


def inspect_source_snapshot(source):
    source = Path(source).resolve()
    manifest = load_json(source / "manifest.json")
    for name, item in manifest["files"].items():
        path = source / name
        if not path.resolve().is_relative_to(source):
            raise ValueError("source_manifest_path_outside_snapshot")
        if sha256_file(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise ValueError(f"source_checksum_or_size_mismatch:{name}")
        if "archive" in item:
            with zipfile.ZipFile(source / item["archive"]) as archive:
                if archive.read(item["member"]) != path.read_bytes():
                    raise ValueError(f"archive_member_differs_from_extracted_file:{name}")
    metadata = load_json(source / "kaggle_metadata.json")
    if metadata["currentVersionNumber"] != manifest["kaggle_dataset_version"]:
        raise ValueError("kaggle_version_mismatch")
    if load_json(source / "cross_reference/unica_commit.json")["sha"] != manifest["unica_commit"]:
        raise ValueError("unica_commit_mismatch")
    data = (source / "Ponzi_label.csv").read_bytes()
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    if reader.fieldnames != ["Contract", "Ponzi"]:
        raise ValueError("unexpected_xblock_schema")
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("malformed_xblock_csv_row")
    records, by_address = [], defaultdict(list)
    for line, row in enumerate(rows, 2):
        entity = address(row["Contract"])
        label = row["Ponzi"]
        record = {"csv_line": line, "source_address": row["Contract"], "address": entity,
                  "source_label": label, "mapped_label": int(label) if label in {"0", "1"} else None,
                  "checks": {"valid_address": entity is not None, "binary_source_label": label in {"0", "1"}},
                  "training_admission": "pending_collection_protocol"}
        records.append(record)
        if entity:
            by_address[entity].append(record)
    duplicates = {key: [r["csv_line"] for r in value] for key, value in by_address.items() if len(value) > 1}
    conflicts = {key: value for key, value in duplicates.items()
                 if len({r["source_label"] for r in by_address[key]}) > 1}
    unica_rows = list(csv.reader((source / "cross_reference/unica_ponzi-addresses.csv").read_text().splitlines()))
    unica = defaultdict(list)
    invalid_unica = []
    for line, row in enumerate(unica_rows, 1):
        entity = address(row[0]) if row else None
        if entity:
            unica[entity].append({"csv_line": line, "name": row[1] if len(row) > 1 else None})
        else:
            invalid_unica.append({"csv_line": line, "raw_record": row})
    overlaps = [dict(record, unica_records=unica[record["address"]])
                for record in records if record["address"] in unica]
    adapter = import_labels("xblock_ponzi", source / "Ponzi_label.csv", "ponzi")
    if len(adapter) != len(records) or any(a["entity_id"] != r["address"] or a["mapped_label"] != r["mapped_label"]
                                         for a, r in zip(adapter, records)):
        raise ValueError("existing_adapter_mapping_mismatch")
    summary = {
        "version": "ponzi-source-inspection-1", "source_manifest_sha256": sha256_file(source / "manifest.json"),
        "source_snapshot": manifest["snapshot"], "source_columns": reader.fieldnames,
        "source_rows": len(rows), "source_label_counts": dict(Counter(r["source_label"] for r in records)),
        "valid_binary_row_count": sum(r["checks"]["valid_address"] and r["checks"]["binary_source_label"] for r in records),
        "invalid_address_count": sum(not r["checks"]["valid_address"] for r in records),
        "duplicate_address_count": len(duplicates), "duplicates": duplicates, "source_conflicts": conflicts,
        "nonbinary_rows": [r for r in records if not r["checks"]["binary_source_label"]],
        "timestamp_columns": [], "transaction_data_bundled": False,
        "adapter_record_count": len(adapter), "adapter_status_counts": dict(Counter(r["label_status"] for r in adapter)),
        "cross_reference": {"source": "Unica", "commit": manifest["unica_commit"],
                            "source_rows": len(unica_rows), "unique_valid_addresses": len(unica),
                            "invalid_rows": invalid_unica,
                            "duplicates": {a: rs for a, rs in unica.items() if len(rs) > 1},
                            "overlap_by_xblock_label": dict(Counter(r["source_label"] for r in overlaps)),
                            "disagreements": [r for r in overlaps if r["source_label"] != "1"],
                            "policy": "record disagreements; neither source automatically overrides the other"},
        "collection_parameters_frozen": False, "etherscan_requests_performed": 0,
        "training_supervision_published": False, "training_performed": False,
    }
    return summary, records
