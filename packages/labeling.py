"""Source-specific evidence imports and point-in-time supervision admission."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable
from xml.etree import ElementTree as ET

from .transactions import address, integer
from .tasks import canonical_task
from .token import TOKEN_TASKS
from .io import read_records

STATUSES = {"supported_positive", "supported_negative", "unlabeled", "disputed", "invalid", "temporally_unresolved"}
ROLES = {"phishing": {"attacker", "phishing_receiver", "phishing_address", "scammer", "phishing_attacker", "benign_address"},
         "ponzi": {"contract", "target_contract", "ponzi_contract"},
         "honeypot": {"token", "token_contract", "honeypot_token"},
         "rug_pull": {"token", "token_contract", "rug_pull_token"}}


def _task(value: Any) -> str:
    return canonical_task(str(value))


def _time(value: Any) -> int | None:
    if value in (None, "", "unknown", "null", "None"):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timestamp_requires_timezone")
        return int(parsed.timestamp())


def _csv_text(path: Path) -> str:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            candidates = [name for name in archive.namelist() if name.lower().endswith("ponzi_label.csv")]
            if len(candidates) != 1:
                raise ValueError("zip_requires_one_Ponzi_label.csv")
            return archive.read(candidates[0]).decode("utf-8-sig")
    return path.read_text(encoding="utf-8-sig")


def _xlsx_rows(path: Path) -> list[dict[str, str]]:
    """Read plain worksheet cells with stdlib; do not execute macros/formulas."""
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(item.itertext()) for item in root.findall("s:si", ns)]
        names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        if not names:
            raise ValueError("xlsx_has_no_worksheet")
        table = []
        for row in ET.fromstring(archive.read(names[0])).findall(".//s:row", ns):
            values: dict[int, str] = {}
            for cell in row.findall("s:c", ns):
                ref = cell.attrib.get("r", "A1")
                column = 0
                for char in ref:
                    if not char.isalpha():
                        break
                    column = column * 26 + ord(char.upper()) - ord("A") + 1
                raw = cell.find("s:v", ns)
                text = raw.text if raw is not None and raw.text else ""
                if cell.attrib.get("t") == "s":
                    text = strings[int(text)]
                elif cell.attrib.get("t") == "inlineStr":
                    text = "".join(cell.find("s:is", ns).itertext())
                values[column - 1] = text
            if values:
                table.append([values.get(i, "") for i in range(max(values) + 1)])
        if not table:
            return []
        header = table[0]
        return [dict(zip(header, row + [""] * max(0, len(header) - len(row)))) for row in table[1:]]


def _base(task: str, entity: Any, raw_label: Any, source: str, row: int, checksum: str) -> dict[str, Any]:
    return {"task_id": task, "entity_id": address(entity), "source_label": str(raw_label),
            "mapped_label": None, "label_status": "temporally_unresolved", "role": "unknown",
            "valid_from": None, "valid_to": None, "label_available_at": None,
            "evidence_ref": None, "source_id": source,
            "label_version": "scam-labels-0.1", "audit_decision": "pending_review",
            "evidence_strength": "source_label", "source_row": row, "source_sha256": checksum}


def _token_mapping(path: str | Path | None) -> dict[str, str]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError("token_mapping_requires_json_object")
    result = {}
    for key, value in payload.items():
        if address(value):
            result[str(key)] = address(value)
        elif address(key) and isinstance(value, (str, int)):
            result[str(value)] = address(key)
    if not result:
        raise ValueError("token_mapping_has_no_address_id_pairs")
    return result


def _map_forta(row: dict[str, Any], task: str, mapping: dict[str, str]) -> dict[str, Any]:
    if task != "phishing" or not {"address", "etherscan_labels"}.issubset(row):
        raise ValueError("forta_requires_phishing_csv_schema")
    return {"source_label": row["etherscan_labels"],
            "mapped_label": 1 if "phish" in str(row["etherscan_labels"]).lower() else None}


def _map_ponzi(row: dict[str, Any], task: str, mapping: dict[str, str]) -> dict[str, Any]:
    if task != "ponzi" or not {"contract", "ponzi"}.issubset(row):
        raise ValueError("xblock_requires_Contract_Ponzi_schema")
    value = str(row["ponzi"])
    changes = {"entity_id": address(row["contract"]), "source_label": value, "role": "target_contract"}
    if value in ("0", "1"):
        changes["mapped_label"] = int(value)
    else:
        changes.update(label_status="invalid", audit_decision="invalid_source_label")
    return changes


def _map_unica(row: dict[str, Any], task: str, mapping: dict[str, str]) -> dict[str, Any]:
    if task != "ponzi":
        raise ValueError("unica_is_ponzi_only")
    return {"source_label": "1", "mapped_label": 1, "role": "target_contract"}


def _map_tokenscout(row: dict[str, Any], task: str, mapping: dict[str, str]) -> dict[str, Any]:
    if not {"tokens", "t2-labels"}.issubset(row):
        raise ValueError("tokenscout_requires_tokens_t2_labels")
    label = row["t2-labels"]
    expected = {"honeypot": "honeypot", "rug_pull": "rugpull", "ponzi": "ponzi"}.get(task)
    return {"entity_id": mapping.get(str(row["tokens"])), "source_entity_id": str(row["tokens"]),
            "source_label": label, "mapped_label": 1 if label == expected else None,
            "role": "token_contract", "evidence_strength": "weak_source_label"}


def _map_crpwarner(row: dict[str, Any], task: str, mapping: dict[str, str]) -> dict[str, Any]:
    pattern = str(row.get("pattern", ""))
    expected = {"rug_pull": "withdrawing liquidity", "honeypot": "limiting sell order"}.get(task)
    changes = {"source_label": pattern, "role": "token_contract", "evidence_strength": "report_candidate"}
    if pattern.strip().lower() == expected:
        changes["mapped_label"] = 1
    else:
        changes.update(label_status="unlabeled", audit_decision="outside_task_mechanism")
    return changes


def _map_audited(row: dict[str, Any], task: str, mapping: dict[str, str]) -> dict[str, Any]:
    value = row.get("mapped_label", row.get("label", ""))
    changes = {"mapped_label": int(value) if str(value) in ("0", "1") else None,
               "role": row.get("role") or "unknown", "audit_decision": row.get("audit_decision") or "pending_review"}
    status = row.get("label_status")
    if status in STATUSES:
        changes["label_status"] = status
    elif changes["mapped_label"] is None:
        changes["label_status"] = "unlabeled"
    if status in ("supported_positive", "supported_negative") and changes["audit_decision"] not in ("admitted", "approved", "accepted", "reviewed"):
        changes.update(label_status="temporally_unresolved", audit_decision="missing_admission_review")
    if row.get("task_id") and _task(row["task_id"]) != task:
        changes.update(label_status="invalid", audit_decision="wrong_task")
    return changes


def _pool_addresses(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value) if value else []
    if not isinstance(value, list) or any(address(pool) is None for pool in value):
        raise ValueError("label_requires_pool_address_list")
    return sorted(set(address(pool) for pool in value))


def _map_honeypot_snapshot(row: dict[str, Any], task: str, mapping: dict[str, str]) -> dict[str, Any]:
    if task != "honeypot":
        raise ValueError("honeypot_snapshot_requires_honeypot_task")
    response, query = row.get("response", {}), row.get("request", {})
    if not isinstance(response, dict) or not isinstance(query, dict):
        raise ValueError("invalid_honeypot_snapshot_structure")
    checksum = hashlib.sha256(json.dumps(response, sort_keys=True).encode()).hexdigest()
    if row.get("response_sha256") != checksum:
        raise ValueError("honeypot_snapshot_checksum_mismatch")
    token = address(query.get("address"))
    pool = address(query.get("pair"))
    detected = _time(row.get("checked_at"))
    if any(not isinstance(response.get(key, {}), dict) for key in ("token", "chain", "pair", "honeypotResult")):
        raise ValueError("invalid_honeypot_snapshot_structure")
    response_pool = response.get("pair", {}).get("pair", {})
    if not isinstance(response_pool, dict):
        raise ValueError("invalid_honeypot_pair_structure")
    if (not token or not pool or detected is None or integer(query.get("chainID")) != 1
            or address(response.get("token", {}).get("address")) != token
            or integer(response.get("chain", {}).get("id")) != 1
            or address(response_pool.get("address")) != pool
            or response_pool.get("type") != "UniswapV2"):
        return {"entity_id": token, "label_status": "invalid", "audit_decision": "snapshot_scope_unresolved"}
    value = response.get("honeypotResult", {}).get("isHoneypot")
    # A successful simulation supports either polarity. Other-source positive
    # evidence can be reviewed, but failed simulations never create negatives.
    usable = isinstance(value, bool) and (response.get("simulationSuccess") is True or value is True)
    reviewed = row.get("audit_decision") in {"admitted", "approved", "accepted", "reviewed"}
    return {"entity_id": token, "role": "token_contract", "mapped_label": int(value) if usable else None,
            "source_label": str(value), "label_status": ("supported_positive" if value else "supported_negative")
            if usable and reviewed else "temporally_unresolved" if usable else "unlabeled",
            "audit_decision": row.get("audit_decision", "pending_review") if usable else "missing_or_ambiguous_detection",
            "valid_from": detected, "valid_to": detected, "label_available_at": detected,
            "pool_addresses": [pool], "evidence_ref": row.get("evidence_ref"),
            "evidence_strength": "api_defined_sell_restriction",
            "label_version": "honeypot-is-snapshot-1.0", "api_response_sha256": checksum}


def _map_rug_incident(row: dict[str, Any], task: str, mapping: dict[str, str]) -> dict[str, Any]:
    if task != "rug_pull":
        raise ValueError("rug_incidents_requires_rug_pull_task")
    changes = _map_audited(row, task, mapping)
    changes.update(pool_addresses=_pool_addresses(row.get("pool_addresses")),
                   chain_id=row.get("chain_id"), incident_tx=row.get("incident_tx"),
                   controller_evidence_ref=row.get("controller_evidence_ref"),
                   mechanism=row.get("mechanism"), label_version="rug-incidents-v2-1.0")
    if str(row.get("chain_id")) != "1" or row.get("mechanism") != "malicious_liquidity_withdrawal_v2":
        changes.update(label_status="invalid", audit_decision="outside_task_scope")
    if changes["mapped_label"] == 1 and (not row.get("incident_tx") or not row.get("controller_evidence_ref")):
        changes.update(label_status="temporally_unresolved", audit_decision="missing_incident_attribution")
    return changes


def _map_xblock_phishing(row: dict[str, Any], task: str, mapping: dict[str, str]) -> dict[str, Any]:
    if task != "phishing":
        raise ValueError("xblock_phishing_requires_phishing_task")
    value = str(row.get("isp", row.get("label", row.get("mapped_label", ""))))
    if value == "1":
        return {"source_label": value, "mapped_label": 1}
    if value == "0":
        return {"source_label": value, "mapped_label": None, "label_status": "unlabeled",
                "audit_decision": "source_zero_is_unlabeled"}
    return {"source_label": value, "label_status": "invalid", "audit_decision": "invalid_source_label"}


@dataclass(frozen=True)
class SourceAdapter:
    mapper: Callable[[dict[str, Any], str, dict[str, str]], dict[str, Any]]
    file_format: str = "csv"
    needs_mapping: bool = False


SOURCE_ADAPTERS = MappingProxyType({
    "forta": SourceAdapter(_map_forta), "xblock_ponzi": SourceAdapter(_map_ponzi),
    "unica": SourceAdapter(_map_unica, file_format="headerless_csv"),
    "tokenscout": SourceAdapter(_map_tokenscout, needs_mapping=True),
    "crpwarner": SourceAdapter(_map_crpwarner, file_format="xlsx_or_csv"),
    "audited": SourceAdapter(_map_audited), "csv": SourceAdapter(_map_audited),
    "xblock_phishing": SourceAdapter(_map_xblock_phishing),
    "honeypot_is": SourceAdapter(_map_honeypot_snapshot, file_format="jsonl"),
    "rug_incidents": SourceAdapter(_map_rug_incident, file_format="jsonl_or_csv"),
})


def import_labels(source: str, path: str | Path, task: str,
                  mapping_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Import evidence without silently admitting source labels as supervision."""
    path = Path(path)
    task = _task(task)
    if task not in ROLES:
        raise ValueError("unsupported_task")
    source = source.lower().replace("-", "_")
    source = {"xblock": "xblock_ponzi", "ponzi": "xblock_ponzi", "forta_phishing": "forta",
              "unica_ponzi": "unica", "audited_csv": "audited", "tokenscout_labels": "tokenscout"}.get(source, source)
    if source not in SOURCE_ADAPTERS:
        raise ValueError("unsupported_label_source")
    adapter = SOURCE_ADAPTERS[source]
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    if adapter.file_format == "jsonl" or adapter.file_format == "jsonl_or_csv" and path.suffix.lower() in {".jsonl", ".parquet"}:
        rows = read_records(path)
    elif adapter.file_format == "xlsx_or_csv" and path.suffix.lower() == ".xlsx":
        rows = _xlsx_rows(path)
    elif adapter.file_format == "headerless_csv":
        rows = [{"address": row[0], "name": row[1] if len(row) > 1 else ""}
                for row in csv.reader(io.StringIO(_csv_text(path))) if row]
    else:
        rows = list(csv.DictReader(io.StringIO(_csv_text(path))))
    token_mapping = _token_mapping(mapping_path) if adapter.needs_mapping else {}
    result = []
    for number, row in enumerate(rows, 1):
        lower = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items() if k is not None}
        entity = lower.get("entity_id") or lower.get("address") or lower.get("contract") or lower.get("token_address")
        original = lower.get("source_label", lower.get("label", ""))
        record = _base(task, entity, original, source, number, checksum)
        record["raw_record"] = row
        record["evidence_ref"] = lower.get("evidence_ref") or lower.get("source") or f"{path.resolve()}#row={number}"
        record.update(adapter.mapper(lower, task, token_mapping))
        record["evidence_ref"] = record.get("evidence_ref") or f"{path.resolve()}#row={number}"
        try:
            for key in ("valid_from", "valid_to", "label_available_at"):
                record[key] = _time(record.get(key) if source == "honeypot_is" else lower.get(key, record.get(key)))
            if task in TOKEN_TASKS:
                record["pool_addresses"] = _pool_addresses(record.get("pool_addresses", lower.get("pool_addresses")))
                for key in ("incident_tx", "controller_evidence_ref", "mechanism"):
                    record[key] = record.get(key, lower.get(key))
        except ValueError:
            record.update(label_status="invalid", audit_decision="invalid_evidence_timestamp")
        if record["entity_id"] is None:
            record.update(label_status="invalid", audit_decision="missing_or_invalid_entity_mapping")
        result.append(record)
    return result


TOKENSCOUT_RETROSPECTIVE_POLICY = "tokenscout-rug-pull-source-adopted-1"


def _tokenscout_retrospective(record, task, policy):
    """Narrow opt-in for the adopted source benchmark, never incident evidence."""
    checksum = str(record.get("source_sha256") or "")
    return (policy == TOKENSCOUT_RETROSPECTIVE_POLICY and task == "rug_pull"
        and record.get("source_id") == "tokenscout"
        and record.get("label_version") == TOKENSCOUT_RETROSPECTIVE_POLICY
        and record.get("audit_basis") == "user_adopted_source_defined_retrospective_experiment"
        and record.get("independent_mechanism_validation") is False
        and record.get("source_label") == ("rugpull" if record.get("mapped_label") == 1 else "truthworthy")
        and len(checksum) == 64 and all(c in "0123456789abcdef" for c in checksum)
        and bool(record.get("evidence_ref"))
        and all(record.get(k) is None for k in ("valid_from", "valid_to", "label_available_at",
            "incident_onset", "incident_tx", "controller_evidence_ref")))


def reconcile_labels(records: Iterable[dict[str, Any]], targets: Iterable[dict[str, Any]],
                     training_as_of: Any = None, *, source_label_policy: str | None = None) -> list[dict[str, Any]]:
    """Admit reviewed labels for a specific root, historical cutoff and role."""
    training_time = _time(training_as_of)
    if source_label_policy not in (None, TOKENSCOUT_RETROSPECTIVE_POLICY):
        raise ValueError("unsupported_source_label_admission_policy")
    if source_label_policy and training_time is not None:
        raise ValueError("retrospective_source_policy_has_no_label_availability_time")
    by_entity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        by_entity.setdefault((_task(record.get("task_id")), str(record.get("entity_id") or "").lower()), []).append(record)
    output = []
    for target in targets:
        task = _task(target.get("task_id"))
        entity = address(target.get("target") or target.get("entity_id"))
        cutoff = _time(target.get("cutoff"))
        coverage = target.get("coverage") or {}
        quality = target.get("quality") or {}
        data_eligible = bool(entity and cutoff is not None and target.get("chain_id", 1) == 1
                             and coverage.get("complete") is not False and quality.get("complete") is not False
                             and target.get("data_eligible") is not False
                             and target.get("status") not in ("data_incomplete", "invalid", "insufficient_history")
                             and task in ROLES
                             and (not target.get("role") or target["role"] in ROLES[task]))
        entry = {"sample_id": target.get("sample_id"), "task_id": task, "entity_id": entity,
                 "chain_id": target.get("chain_id", 1),
                 "label_status": "unlabeled", "observed_target": None, "eligible": False,
                 "data_eligible": data_eligible, "background_selected": bool(target.get("background_selected")),
                 "cohort_id": target.get("cohort_id"), "cutoff": cutoff, "reason": "unlabeled",
                 "evidence_refs": [], "source_ids": []}
        for key in ("group_id", "verified_group_id", "group_ids", "group_verified",
                    "group_ref", "group_evidence_ref", "source_cohort", "cutoff_basis"):
            if key in target:
                entry[key] = target[key]
        entry.update(label_version=None, label_available_at=None, valid_from=None,
                     valid_to=None, audit_decision="not_admitted", source_checksums={})
        if task in TOKEN_TASKS:
            entry["pool_addresses"] = sorted(address(pool) for pool in target.get("pools", []) if address(pool))
        candidates = by_entity.get((task, entity or ""), [])
        conflict_candidates = candidates
        if task in TOKEN_TASKS:
            conflict_candidates = [record for record in candidates
                                   if record.get("pool_addresses") == entry["pool_addresses"]
                                   and cutoff is not None
                                   and (record.get("valid_from") is None or _time(record["valid_from"]) <= cutoff)
                                   and (record.get("valid_to") is None or cutoff <= _time(record["valid_to"]))]
        values = {record.get("mapped_label") for record in conflict_candidates
                  if record.get("mapped_label") in (0, 1) and record.get("label_status") != "invalid"}
        entry["evidence_refs"] = sorted({str(record.get("evidence_ref")) for record in candidates if record.get("evidence_ref")})
        entry["source_ids"] = sorted({str(record.get("source_id")) for record in candidates if record.get("source_id")})
        entry["source_checksums"] = {str(record.get("source_id")): record.get("source_sha256") for record in candidates if record.get("source_id")}
        if not data_eligible:
            entry["reason"] = "data_incomplete_or_invalid_target"
        elif len(values) > 1 or any(record.get("label_status") == "disputed" for record in conflict_candidates):
            entry.update(label_status="disputed", reason="source_label_conflict")
        else:
            admitted = []
            rejection = None
            for record in candidates:
                status = record.get("label_status")
                if status in ("unlabeled", "invalid"):
                    continue
                if status not in ("supported_positive", "supported_negative"):
                    rejection = "label_not_reviewed_or_temporally_resolved"
                    continue
                if record.get("audit_decision") not in ("admitted", "approved", "accepted", "reviewed"):
                    rejection = "missing_admission_review"
                    continue
                if record.get("role") not in ROLES.get(task, set()):
                    rejection = "unknown_or_inapplicable_role"
                    continue
                if task in TOKEN_TASKS and (not record.get("pool_addresses")
                        or sorted(record["pool_addresses"]) != entry["pool_addresses"]):
                    rejection = "label_pool_scope_mismatch"
                    continue
                if task == "rug_pull" and record.get("mapped_label") == 1 and not _tokenscout_retrospective(record, task, source_label_policy):
                    tx = str(record.get("incident_tx") or "")
                    valid_tx = len(tx) == 66 and tx.startswith("0x") and all(char in "0123456789abcdefABCDEF" for char in tx[2:])
                    if not valid_tx or not record.get("controller_evidence_ref"):
                        rejection = "missing_rug_incident_evidence"
                        continue
                if task == "phishing" and status == "supported_positive" and record.get("role") == "benign_address":
                    rejection = "role_incompatible_with_positive_label"
                    continue
                valid_from, valid_to = _time(record.get("valid_from")), _time(record.get("valid_to"))
                if (valid_from is not None and cutoff < valid_from
                        or valid_to is not None and cutoff > valid_to):
                    rejection = "unknown_or_inapplicable_valid_period"
                    continue
                available = _time(record.get("label_available_at"))
                if training_time is not None and (available is None or available > training_time):
                    rejection = "label_unavailable_at_training_as_of"
                    continue
                value = record.get("mapped_label")
                if value not in (0, 1) or (status == "supported_positive") != (value == 1):
                    rejection = "inconsistent_label_status"
                    continue
                admitted.append(record)
            if admitted:
                chosen = admitted[0]
                entry.update(label_status=chosen["label_status"], observed_target=chosen["mapped_label"],
                             eligible=True, reason="admitted_reviewed_label", audit_decision="admitted")
                if _tokenscout_retrospective(chosen, task, source_label_policy):
                    entry.update(reason="admitted_source_defined_retrospective_label",
                        label_policy=TOKENSCOUT_RETROSPECTIVE_POLICY,
                        audit_basis=chosen["audit_basis"], independent_mechanism_validation=False,
                        source_label=chosen["source_label"], incident_onset=None,
                        incident_tx=None, controller_evidence_ref=None)
                versions = sorted({str(record.get("label_version")) for record in admitted})
                entry["label_version"] = versions[0] if len(versions) == 1 else "mixed"
                entry["label_versions"] = versions
                availability = [_time(record.get("label_available_at")) for record in admitted]
                entry["label_available_at"] = max(availability) if all(value is not None for value in availability) else None
                lower = [_time(record["valid_from"]) for record in admitted if record.get("valid_from") is not None]
                entry["valid_from"] = max(lower) if lower else None
                upper = [_time(record.get("valid_to")) for record in admitted if record.get("valid_to") is not None]
                entry["valid_to"] = min(upper) if upper else None
            elif rejection:
                entry.update(label_status="temporally_unresolved", reason=rejection)
            elif candidates and all(record.get("label_status") == "invalid" for record in candidates):
                entry.update(label_status="invalid", reason="invalid_source_records")
        output.append(entry)
    return output
