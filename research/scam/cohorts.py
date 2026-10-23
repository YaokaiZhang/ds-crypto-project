"""Task-specific cohort admission, sampling and evidence assembly."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from packages.io import load_json, sha256_file
from packages.sources.phishing import parse_phishing_records


def build_reference_phishing_cohort(source_directory, *, per_class=None, seed=20261008):
    """All eligible Poison Hunter roots and an equal hash-selected Forta subset."""
    directory = Path(source_directory)
    manifest = load_json(directory / "manifest.json")
    records = []
    for source in manifest["files"]:
        path = directory / source["file"]
        if sha256_file(path) != source["sha256"]:
            raise ValueError("source_snapshot_checksum_mismatch")
        records.extend(parse_phishing_records(path.read_text(encoding="utf-8-sig"), source))
    positive = {r["entity_id"] for r in records if r["mapped_label"] == 1 and r["label_status"] != "invalid"}
    reference = {r["entity_id"] for r in records if r["source_file"] == "poison_hunter_background" and r["label_status"] == "unlabeled"} - positive
    eligible = {r["entity_id"] for r in records if r["label_status"] == "supported_positive" and r["training_positive"]}
    if per_class is not None and (not isinstance(per_class, int) or isinstance(per_class, bool) or per_class < 10):
        raise ValueError("per_class_must_be_at_least_10_for_80_10_10_split")
    count = min(len(reference), len(eligible), per_class if per_class is not None else len(reference))
    if count < 10:
        raise ValueError("insufficient_reference_background_or_positive_addresses")
    targets, evidence, report = build_phishing_cohort(directory, per_class=count, seed=seed)
    report.update(background_policy="poison_hunter_only", per_class_requested=per_class,
                  available_reference_background=len(reference),
                  selection="all eligible reference roots, or a seeded hash subset; equal Forta count; independent of graph availability")
    report["cohort_id"] = "phishing-reference-" + hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()[:16]
    targets = [dict(row, cohort_id=report["cohort_id"]) for row in targets]
    return targets, evidence, report

def build_phishing_cohort(source_directory: str | Path, *, per_class: int = 6000,
                          seed: int = 20261008, background_directory: str | Path | None = None) -> tuple[list[dict], list[dict], dict]:
    """Select fixed roots before looking at transactions or model outcomes."""
    if not isinstance(per_class, int) or isinstance(per_class, bool) or per_class < 10:
        raise ValueError("per_class_must_be_at_least_10_for_80_10_10_split")
    directory = Path(source_directory)
    manifest = load_json(directory / "manifest.json")
    records = []
    for source in manifest["files"]:
        path = directory / source["file"]
        if sha256_file(path) != source["sha256"]:
            raise ValueError("source_snapshot_checksum_mismatch")
        records.extend(parse_phishing_records(path.read_text(encoding="utf-8-sig"), source))
    background_manifest = None
    if background_directory is not None:
        from packages.sources.historical import load_background_records
        extra, background_manifest = load_background_records(background_directory, manifest["source_as_of"], task_id="phishing")
        records.extend(extra)
    public_positive = {row["entity_id"] for row in records if row["mapped_label"] == 1 and row["label_status"] != "invalid"}
    positive = {row["entity_id"] for row in records if row["label_status"] == "supported_positive"
                and row["source_id"] == manifest["positive_source"] and row["training_positive"]}
    background = {row["entity_id"] for row in records if row["label_status"] == "unlabeled"}
    overlaps = sorted(background & public_positive)
    background -= public_positive
    available_background = len(background)
    rank = lambda value: hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()
    count = min(per_class, len(positive))
    if count < 10:
        raise ValueError("insufficient_source_positive_addresses")
    if len(background) < count:
        raise ValueError(f"insufficient_background_addresses:{len(background)}<{count}; use --discover-background")
    reference = {row["entity_id"] for row in records if row["source_file"] == "poison_hunter_background"} & background
    selected_reference = sorted(reference, key=rank)[:count]
    positive = sorted(positive, key=rank)[:count]
    background = selected_reference + sorted(background - reference, key=rank)[:count - len(selected_reference)]
    cohort_id = "phishing-" + hashlib.sha256(json.dumps([manifest, background_manifest, seed, per_class], sort_keys=True).encode()).hexdigest()[:16]
    targets = [{"sample_id": f"phishing:1:{entity}", "task_id": "phishing", "chain_id": 1,
                "target": entity, "cutoff": manifest["source_as_of"], "background_selected": is_background,
                "cohort_id": cohort_id} for is_background, values in ((False, positive), (True, background)) for entity in values]
    positive_set, background_set = set(positive), set(background)
    evidence = [row for row in records if (row["entity_id"] in positive_set
                and row["source_id"] == manifest["positive_source"] and row["training_positive"])
                or (row["entity_id"] in background_set and row["label_status"] == "unlabeled"
                    and (row["entity_id"] not in reference or row["source_file"] == "poison_hunter_background"))]
    report = {"cohort_id": cohort_id, "per_class_requested": per_class, "per_class_selected": count,
              "seed": seed, "source_sha256": sha256_file(directory / "manifest.json"),
              "source_label_counts": dict(Counter(row["label_status"] for row in records)),
              "available_positive_addresses": len({row["entity_id"] for row in records if row["label_status"] == "supported_positive" and row["training_positive"]}),
              "available_background_addresses": available_background,
              "background_source_counts": {"poison_hunter_background": len(selected_reference), "historical_rpc": count - len(selected_reference)},
              "background_snapshot": background_manifest,
              "excluded_background_positive_overlap": overlaps, "cutoff": manifest["source_as_of"],
              "selection": "address hash only; no label-dependent transaction window or performance selection",
              "source_bias": "block-sampled transaction participants overrepresent active addresses; author-labelled addresses may overrepresent popular entities; neither is verified benign"}
    return targets, evidence, report
