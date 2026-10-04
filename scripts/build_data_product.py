#!/usr/bin/env python3
"""Build normalized Parquet and DuckDB-ready tables from JSONL source runs.

Censored rows remain in audit tables but are excluded from the supervised
model table. Features are computed only from t0 through the recorded cutoff.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.participant_fields import normalize_canonical_participants  # noqa: E402

TABLE_FIELDS = {
    "tokens": [
        ("token_address", "str"), ("source_dataset", "str"), ("launch_period", "str"),
        ("sampling_rank", "int"), ("first_observed_block", "int"),
        ("first_observed_timestamp", "str"), ("t0", "str"), ("cutoff", "str"),
        ("followup_end", "str"), ("pool_count", "int"),
        ("pool_scope_complete", "bool"), ("pool_scope_reason", "str"),
        ("activity_collected", "bool"), ("activity_collection_reason", "str"),
        ("primary_label", "str"),
    ],
    "pools": [
        ("token_address", "str"), ("source_dataset", "str"), ("pool_address", "str"),
        ("protocol", "str"), ("token0", "str"), ("token1", "str"),
        ("token0_symbol", "str"), ("token1_symbol", "str"),
        ("creation_block", "int"), ("creation_timestamp", "str"),
        ("creation_transaction_hash", "str"), ("source", "str"),
        ("pool_scope_complete", "bool"), ("pool_scope_reason", "str"),
    ],
    "events": [
        ("token_address", "str"), ("source_dataset", "str"), ("protocol", "str"),
        ("pool_address", "str"), ("token0", "str"), ("token1", "str"),
        ("event_type", "str"), ("event_id", "str"), ("block_number", "int"),
        ("block_hash", "str"), ("block_timestamp", "str"),
        ("transaction_hash", "str"), ("log_index", "int"), ("topics", "list_str"),
        ("data", "str"), ("amount_usd", "str"), ("source_request_id", "str"),
        ("source", "str"), ("swap_sender", "str"), ("swap_recipient", "str"),
        ("transaction_from", "str"),
    ],
    "outcomes": [
        ("token_address", "str"), ("source_dataset", "str"),
        ("label_definition", "str"), ("label", "str"), ("t0", "str"),
        ("cutoff", "str"), ("followup_days", "int"), ("followup_end", "str"),
        ("volume_threshold_usd", "str"), ("volume_source", "str"),
        ("observation_days", "int"), ("observation_swap_count", "int"),
        ("total_swap_count", "int"), ("followup_swap_count", "int"),
        ("followup_event_count", "int"), ("followup_volume_usd", "str"),
        ("pool_count", "int"), ("pool_scope_complete", "bool"),
        ("activity_collected", "bool"), ("volume_complete", "bool"),
        ("cutoff_event_id", "str"), ("evidence_event_ids", "list_str"),
        ("followup_evidence_event_ids", "list_str"),
        ("missing_volume_event_ids", "list_str"), ("censoring_reason", "str"),
        ("exclusion_reason", "str"), ("retrieved_at", "str"),
    ],
    "sensitivity_outcomes": [
        ("token_address", "str"), ("source_dataset", "str"),
        ("label_definition", "str"), ("label", "str"), ("t0", "str"),
        ("cutoff", "str"), ("followup_end", "str"),
        ("observation_swap_count", "int"), ("followup_event_count", "int"),
        ("pool_count", "int"), ("pool_scope_complete", "bool"),
        ("activity_collected", "bool"), ("cutoff_event_id", "str"),
        ("evidence_event_ids", "list_str"),
        ("followup_evidence_event_ids", "list_str"),
        ("censoring_reason", "str"), ("exclusion_reason", "str"),
    ],
    "censoring": [
        ("token_address", "str"), ("source_dataset", "str"),
        ("label_definition", "str"), ("reason", "str"), ("retrieved_at", "str"),
    ],
    "candidates": [
        ("token_address", "str"), ("source_dataset", "str"),
        ("candidate_source_file", "str"), ("launch_period", "str"),
        ("launch_band", "str"), ("sampling_rank", "int"),
        ("selection_rank", "int"), ("selection_stratum", "str"),
        ("pool_count_stratum", "str"), ("early_volume_stratum", "str"),
        ("inclusion_probability", "str"), ("sampling_weight", "str"),
        ("eligible_in_stratum", "int"), ("selected_in_stratum", "int"),
        ("screen_eligible", "bool"), ("screen_activity_complete", "bool"),
        ("pool_scope_complete", "bool"), ("first_observed_block", "int"),
        ("first_observed_timestamp", "str"), ("sampling_label_inspected", "bool"),
    ],
    "sampling": [
        ("token_address", "str"), ("source_dataset", "str"),
        ("primary_label", "str"), ("censoring_status", "bool"),
        ("censoring_reason", "str"), ("selection_probability", "str"),
        ("selection_stratum", "str"), ("launch_period", "str"),
        ("cohort_role", "str"), ("quota_selection_reason", "str"),
        ("inclusion_weight", "str"), ("case_control_weight", "str"),
        ("overlap_group", "str"),
    ],
    "splits": [
        ("token_address", "str"), ("source_dataset", "str"), ("t0", "str"),
        ("cutoff", "str"), ("followup_end", "str"), ("label", "str"),
        ("censoring_status", "bool"), ("censoring_reason", "str"),
        ("overlap_group", "str"), ("partition", "str"),
        ("exclusion_reason", "str"), ("split_frozen_before_test_labels", "bool"),
        ("split_freeze_evidence", "str"),
    ],
    "features": [
        ("token_address", "str"), ("source_dataset", "str"), ("t0", "str"),
        ("cutoff", "str"), ("observation_days", "int"), ("event_count", "int"),
        ("swap_count", "int"), ("mint_count", "int"), ("burn_count", "int"),
        ("pre_cutoff_volume_usd", "str"),
        ("pre_cutoff_missing_swap_usd_count", "int"),
        ("active_day_count", "int"), ("pool_count", "int"),
        ("protocol_count", "int"), ("first_event_timestamp", "str"),
        ("last_event_timestamp", "str"), ("feature_complete", "bool"),
        ("feature_status", "str"),
    ],
    "feature_audit": [
        ("token_address", "str"), ("source_dataset", "str"), ("t0", "str"),
        ("cutoff", "str"), ("raw_event_count", "int"),
        ("pre_t0_event_count", "int"), ("post_cutoff_event_count", "int"),
        ("missing_timestamp_count", "int"), ("feature_complete", "bool"),
        ("feature_status", "str"),
    ],
    "request_log": [
        ("source_dataset", "str"), ("request_id", "str"),
        ("response_id", "str"), ("retrieved_at", "str"), ("method", "str"),
        ("url", "str"), ("status", "int"), ("attempt", "int"),
        ("incomplete", "bool"), ("error", "str"), ("raw_path", "str"),
        ("raw_line", "int"), ("params_json", "str"),
    ],
}

PRIMARY_LABELS = {"low_volume_dead", "continued_activity"}


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"expected object at {path}:{line_number}")
            yield row


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_time(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def token_of(row: dict[str, Any]) -> str:
    return str(row.get("token_address") or "").lower()


def text(value: Any) -> str | None:
    return None if value is None else str(value)


def integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected integer, got {value!r}") from exc


def boolean(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if str(value).lower() in {"true", "1", "yes"}:
        return True
    if str(value).lower() in {"false", "0", "no"}:
        return False
    raise ValueError(f"expected boolean, got {value!r}")


def string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def load_report(source: Path) -> dict[str, Any]:
    for filename in ("graph_free_pilot_report.json", "wallet_graph_collection_report.json"):
        path = source / filename
        if not path.exists():
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    return {}


def load_source(source: Path) -> dict[str, Any]:
    entities: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(source / "token_entities.jsonl"):
        token = token_of(row)
        if not token or token in entities:
            raise ValueError(f"duplicate or missing token entity in {source}")
        entities[token] = row
    for row in iter_jsonl(source / "outcomes.jsonl"):
        token = token_of(row)
        if not token or token in outcomes:
            raise ValueError(f"duplicate or missing outcome in {source}")
        outcomes[token] = row
    if set(entities) != set(outcomes):
        raise ValueError(f"entity/outcome token mismatch in {source}")
    return {"path": source, "name": source.name, "entities": entities,
            "outcomes": outcomes, "report": load_report(source)}


def load_candidates(paths: list[Path]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for path in paths:
        for row in iter_jsonl(path):
            token = token_of(row)
            if not token:
                raise ValueError(f"candidate has no token address: {path}")
            candidate = dict(row)
            candidate["token_address"] = token
            candidate["_candidate_source_file"] = str(path)
            previous = candidates.get(token)
            if previous is not None:
                left = {k: v for k, v in previous.items() if k != "_candidate_source_file"}
                right = {k: v for k, v in candidate.items() if k != "_candidate_source_file"}
                if json.dumps(left, sort_keys=True) != json.dumps(right, sort_keys=True):
                    raise ValueError(f"conflicting candidate rows for {token}")
                continue
            candidates[token] = candidate
    return candidates


def load_frozen_splits(path: Path | None) -> dict[tuple[str, str], tuple[str, None]]:
    if path is None:
        return {}
    result: dict[tuple[str, str], tuple[str, None]] = {}
    for row in iter_jsonl(path):
        token = token_of(row)
        source = text(row.get("source_dataset"))
        partition = text(row.get("partition"))
        if not token or not source or partition not in {"train", "validation", "test"}:
            raise ValueError(f"invalid frozen split row in {path}: {row}")
        key = (token, source)
        if key in result:
            raise ValueError(f"duplicate frozen split row: {key}")
        result[key] = partition, None
    return result


def normalize_event(row: dict[str, Any], source_name: str) -> dict[str, Any]:
    token = token_of(row)
    if not token:
        raise ValueError(f"event has no token address in {source_name}")
    transaction_hash = text(row.get("transaction_hash")) or text(row.get("event_id"))
    if not transaction_hash:
        raise ValueError(f"event has no transaction identity for {token}")
    participants = normalize_canonical_participants(row)
    return {
        "token_address": token, "source_dataset": source_name,
        "protocol": text(row.get("protocol")), "pool_address": text(row.get("pool_address")),
        "token0": text(row.get("token0")), "token1": text(row.get("token1")),
        "event_type": text(row.get("event_type")), "event_id": text(row.get("event_id")),
        "block_number": integer(row.get("block_number")), "block_hash": text(row.get("block_hash")),
        "block_timestamp": text(row.get("block_timestamp")),
        "transaction_hash": transaction_hash.lower(), "log_index": integer(row.get("log_index")),
        "topics": string_list(row.get("topics")), "data": text(row.get("data")),
        "amount_usd": text(row.get("amount_usd")), "source_request_id": text(row.get("source_request_id")),
        "source": text(row.get("source")),
        **participants,
    }


def event_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return row["token_address"], row["transaction_hash"], int(row["log_index"] or 0)


class EventKeyIndex:
    def __init__(self, path: Path, keep: bool) -> None:
        self.path = path
        self.keep = keep
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE event_keys (token_address TEXT, transaction_hash TEXT, "
            "log_index INTEGER, fingerprint TEXT, PRIMARY KEY(token_address, transaction_hash, log_index))"
        )
        self.connection.execute("PRAGMA synchronous=OFF")
        self.pending = 0

    def add(self, row: dict[str, Any]) -> bool:
        key = event_key(row)
        fingerprint = json.dumps(row, sort_keys=True, separators=(",", ":"))
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO event_keys VALUES (?, ?, ?, ?)",
            (*key, fingerprint),
        )
        self.pending += 1
        if self.pending >= 10000:
            self.connection.commit()
            self.pending = 0
        if cursor.rowcount:
            return True
        previous = self.connection.execute(
            "SELECT fingerprint FROM event_keys WHERE token_address=? "
            "AND transaction_hash=? AND log_index=?", key
        ).fetchone()
        if previous and previous[0] != fingerprint:
            raise ValueError(f"conflicting duplicate event key: {key}")
        return False

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()
        if not self.keep:
            self.path.unlink(missing_ok=True)


def arrow_type(pa: Any, kind: str) -> Any:
    return {"str": pa.string(), "int": pa.int64(), "bool": pa.bool_(),
            "list_str": pa.list_(pa.string())}[kind]


class ParquetSink:
    def __init__(self, path: Path, table_name: str, pa: Any, pq: Any) -> None:
        self.path = path
        self.pa = pa
        self.pq = pq
        self.schema = pa.schema(
            [pa.field(name, arrow_type(pa, kind)) for name, kind in TABLE_FIELDS[table_name]]
        )
        self.writer = None
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        table = self.pa.Table.from_pylist(rows, schema=self.schema)
        if self.writer is None:
            self.writer = self.pq.ParquetWriter(self.path, self.schema, compression="zstd")
        self.writer.write_table(table)

    def close(self) -> None:
        if self.writer is None:
            self.pq.write_table(
                self.pa.Table.from_pylist([], schema=self.schema),
                self.path,
                compression="zstd",
            )
        else:
            self.writer.close()


def load_arrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "Parquet output requires pyarrow; install the data dependency group with uv sync"
        ) from exc
    return pa, pq


def feature_accumulator() -> dict[str, Any]:
    return {"raw_event_count": 0, "event_count": 0, "swap_count": 0, "mint_count": 0, "burn_count": 0,
            "volume_usd": Decimal("0"), "missing_swap_usd": 0, "active_days": set(),
            "protocols": set(), "first_event": None, "last_event": None,
            "post_cutoff": 0, "pre_t0": 0, "missing_timestamp": 0}


def update_features(accumulator: dict[str, Any], row: dict[str, Any], *,
                    t0: datetime | None, cutoff: datetime | None) -> None:
    accumulator["raw_event_count"] += 1
    timestamp = parse_time(row.get("block_timestamp"))
    if timestamp is None:
        accumulator["missing_timestamp"] += 1
        return
    if t0 is None or cutoff is None:
        return
    if timestamp < t0:
        accumulator["pre_t0"] += 1
        return
    if timestamp > cutoff:
        accumulator["post_cutoff"] += 1
        return
    accumulator["event_count"] += 1
    event_type = row.get("event_type")
    if event_type == "swap":
        accumulator["swap_count"] += 1
        try:
            amount = Decimal(str(row.get("amount_usd"))) if row.get("amount_usd") is not None else None
        except (InvalidOperation, ValueError):
            amount = None
        if amount is None or not amount.is_finite() or amount <= 0:
            accumulator["missing_swap_usd"] += 1
        else:
            accumulator["volume_usd"] += amount
    elif event_type == "mint":
        accumulator["mint_count"] += 1
    elif event_type == "burn":
        accumulator["burn_count"] += 1
    accumulator["active_days"].add(timestamp.date().isoformat())
    if row.get("protocol"):
        accumulator["protocols"].add(row["protocol"])
    accumulator["first_event"] = min(filter(None, (accumulator["first_event"], timestamp)),
                                     default=timestamp)
    accumulator["last_event"] = max(filter(None, (accumulator["last_event"], timestamp)),
                                    default=timestamp)


def feature_row(token: str, source_name: str, outcome: dict[str, Any],
                entity: dict[str, Any], accumulator: dict[str, Any]) -> dict[str, Any]:
    t0 = parse_time(outcome.get("t0"))
    cutoff = parse_time(outcome.get("cutoff"))
    complete = t0 is not None and cutoff is not None and accumulator["missing_timestamp"] == 0
    return {
        "token_address": token, "source_dataset": source_name, "t0": iso_time(t0),
        "cutoff": iso_time(cutoff), "observation_days": integer(outcome.get("observation_days")),
        "event_count": accumulator["event_count"], "swap_count": accumulator["swap_count"],
        "mint_count": accumulator["mint_count"], "burn_count": accumulator["burn_count"],
        "pre_cutoff_volume_usd": format(accumulator["volume_usd"], "f"),
        "pre_cutoff_missing_swap_usd_count": accumulator["missing_swap_usd"],
        "active_day_count": len(accumulator["active_days"]), "pool_count": len(entity.get("pools") or []),
        "protocol_count": len(accumulator["protocols"]), "first_event_timestamp": iso_time(accumulator["first_event"]),
        "last_event_timestamp": iso_time(accumulator["last_event"]),
        "feature_complete": complete, "feature_status": "complete" if complete else "missing_timestamps_or_cutoff",
    }


def feature_audit_row(token: str, source_name: str, outcome: dict[str, Any],
                      accumulator: dict[str, Any]) -> dict[str, Any]:
    t0 = parse_time(outcome.get("t0"))
    cutoff = parse_time(outcome.get("cutoff"))
    complete = t0 is not None and cutoff is not None and accumulator["missing_timestamp"] == 0
    return {
        "token_address": token, "source_dataset": source_name, "t0": iso_time(t0),
        "cutoff": iso_time(cutoff), "raw_event_count": accumulator["raw_event_count"],
        "pre_t0_event_count": accumulator["pre_t0"],
        "post_cutoff_event_count": accumulator["post_cutoff"],
        "missing_timestamp_count": accumulator["missing_timestamp"],
        "feature_complete": complete,
        "feature_status": "complete" if complete else "missing_timestamps_or_cutoff",
    }


def pool_rows(entity: dict[str, Any], source_name: str) -> list[dict[str, Any]]:
    return [{
        "token_address": token_of(entity), "source_dataset": source_name,
        "pool_address": text(pool.get("pool_address")), "protocol": text(pool.get("protocol")),
        "token0": text(pool.get("token0")), "token1": text(pool.get("token1")),
        "token0_symbol": text(pool.get("token0_symbol")), "token1_symbol": text(pool.get("token1_symbol")),
        "creation_block": integer(pool.get("creation_block")), "creation_timestamp": text(pool.get("creation_timestamp")),
        "creation_transaction_hash": text(pool.get("creation_transaction_hash")), "source": text(pool.get("source")),
        "pool_scope_complete": boolean(entity.get("pool_scope_complete")),
        "pool_scope_reason": text(entity.get("pool_scope_reason")),
    } for pool in entity.get("pools") or []]


def outcome_row(outcome: dict[str, Any], source_name: str, retrieved_at: str | None) -> dict[str, Any]:
    row = {name: outcome.get(name) for name, _ in TABLE_FIELDS["outcomes"]}
    row["token_address"] = token_of(outcome)
    row["source_dataset"] = source_name
    row["retrieved_at"] = retrieved_at
    # Frozen target manifests encode follow-up completeness as censoring_status.
    volume_complete = boolean(row["volume_complete"])
    if volume_complete is None:
        censoring_status = boolean(outcome.get("censoring_status"))
        if censoring_status is not None:
            volume_complete = not censoring_status
    row["volume_complete"] = volume_complete
    return row


def sensitivity_row(outcome: dict[str, Any], source_name: str) -> dict[str, Any]:
    return {name: token_of(outcome) if name == "token_address" else
            source_name if name == "source_dataset" else outcome.get(name)
            for name, _ in TABLE_FIELDS["sensitivity_outcomes"]}


def token_row(entity: dict[str, Any], outcome: dict[str, Any], source_name: str) -> dict[str, Any]:
    return {
        "token_address": token_of(entity), "source_dataset": source_name,
        "launch_period": text(entity.get("launch_period") or outcome.get("launch_period")),
        "sampling_rank": integer(entity.get("sampling_rank")), "first_observed_block": integer(entity.get("first_observed_block")),
        "first_observed_timestamp": text(entity.get("first_observed_timestamp")), "t0": text(outcome.get("t0")),
        "cutoff": text(outcome.get("cutoff")), "followup_end": text(outcome.get("followup_end")),
        "pool_count": integer(outcome.get("pool_count")) or len(entity.get("pools") or []),
        "pool_scope_complete": boolean(entity.get("pool_scope_complete")), "pool_scope_reason": text(entity.get("pool_scope_reason")),
        "activity_collected": boolean(entity.get("activity_collected")), "activity_collection_reason": text(entity.get("activity_collection_reason")),
        "primary_label": text(outcome.get("label")),
    }


def candidate_row(candidate: dict[str, Any], source_name: str | None) -> dict[str, Any]:
    return {
        "token_address": token_of(candidate), "source_dataset": source_name,
        "candidate_source_file": text(candidate.get("_candidate_source_file")),
        "launch_period": text(candidate.get("launch_period")), "launch_band": text(candidate.get("launch_band")),
        "sampling_rank": integer(candidate.get("sampling_rank")), "selection_rank": integer(candidate.get("selection_rank")),
        "selection_stratum": text(candidate.get("selection_stratum")), "pool_count_stratum": text(candidate.get("pool_count_stratum")),
        "early_volume_stratum": text(candidate.get("early_volume_stratum")), "inclusion_probability": text(candidate.get("inclusion_probability")),
        "sampling_weight": text(candidate.get("sampling_weight")), "eligible_in_stratum": integer(candidate.get("eligible_in_stratum")),
        "selected_in_stratum": integer(candidate.get("selected_in_stratum")), "screen_eligible": boolean(candidate.get("screen_eligible")),
        "screen_activity_complete": boolean(candidate.get("screen_activity_complete")), "pool_scope_complete": boolean(candidate.get("pool_scope_complete")),
        "first_observed_block": integer(candidate.get("first_observed_block")), "first_observed_timestamp": text(candidate.get("first_observed_timestamp")),
        "sampling_label_inspected": boolean(candidate.get("sampling_label_inspected")),
    }


def partition_for_outcome(outcome: dict[str, Any] | None, *, train_end: datetime | None,
                          validation_end: datetime | None, test_end: datetime | None) -> tuple[str, str | None]:
    if outcome is None:
        return "not_collected", "not_in_source_run"
    if outcome.get("label") not in PRIMARY_LABELS:
        return "excluded", outcome.get("censoring_reason") or outcome.get("exclusion_reason")
    t0 = parse_time(outcome.get("t0"))
    if t0 is None:
        return "excluded", "missing_t0"
    if train_end and t0 < train_end:
        return "train", None
    if validation_end and t0 < validation_end:
        return "validation", None
    if test_end and t0 <= test_end:
        return "test", None
    return "excluded", "launch_after_test_cutoff"


def sampling_row(token: str, candidate: dict[str, Any] | None, entity: dict[str, Any] | None,
                 outcome: dict[str, Any] | None, source_name: str | None) -> dict[str, Any]:
    candidate, entity, outcome = candidate or {}, entity or {}, outcome or {}
    return {
        "token_address": token, "source_dataset": source_name, "primary_label": text(outcome.get("label")),
        "censoring_status": True if outcome.get("label") == "censored" else (False if outcome else None),
        "censoring_reason": text(outcome.get("censoring_reason")),
        "selection_probability": text(candidate.get("inclusion_probability") or candidate.get("selection_probability")),
        "selection_stratum": text(candidate.get("selection_stratum") or candidate.get("early_volume_stratum") or candidate.get("pool_count_stratum")),
        "launch_period": text(candidate.get("launch_period") or entity.get("launch_period") or outcome.get("launch_period")),
        "cohort_role": text(candidate.get("cohort_role")) or "unassigned",
        "quota_selection_reason": text(candidate.get("quota_selection_reason")),
        "inclusion_weight": text(candidate.get("sampling_weight")), "case_control_weight": text(candidate.get("case_control_weight")),
        "overlap_group": text(candidate.get("overlap_group")) or token,
    }


def split_row(token: str, entity: dict[str, Any] | None, outcome: dict[str, Any] | None,
              source_name: str | None, partition: str, exclusion_reason: str | None) -> dict[str, Any]:
    entity, outcome = entity or {}, outcome or {}
    return {
        "token_address": token, "source_dataset": source_name, "t0": text(outcome.get("t0")),
        "cutoff": text(outcome.get("cutoff")), "followup_end": text(outcome.get("followup_end")),
        "label": text(outcome.get("label")), "censoring_status": True if outcome.get("label") == "censored" else (False if outcome else None),
        "censoring_reason": text(outcome.get("censoring_reason")), "overlap_group": text(entity.get("overlap_group")) or token,
        "partition": partition, "exclusion_reason": exclusion_reason, "split_frozen_before_test_labels": None,
        "split_freeze_evidence": "not_recorded_in_source_run",
    }


def request_row(row: dict[str, Any], source_name: str) -> dict[str, Any]:
    params = row.get("params")
    return {
        "source_dataset": source_name, "request_id": text(row.get("request_id")), "response_id": text(row.get("response_id")),
        "retrieved_at": text(row.get("retrieved_at")), "method": text(row.get("method")), "url": text(row.get("url")),
        "status": integer(row.get("status")), "attempt": integer(row.get("attempt")), "incomplete": boolean(row.get("incomplete")),
        "error": text(row.get("error")), "raw_path": text(row.get("raw_path")), "raw_line": integer(row.get("raw_line")),
        "params_json": json.dumps(params, sort_keys=True, ensure_ascii=True) if params is not None else None,
    }


def run_duckdb(output: Path, project_root: Path) -> dict[str, Any]:
    try:
        import duckdb
    except ImportError:
        return {"status": "not_run_missing_dependency", "message": "duckdb is not installed"}
    sql_path = project_root / "sql" / "model_tables.sql"
    if not sql_path.exists():
        return {"status": "not_run_missing_sql", "message": str(sql_path)}
    database = output / "analytical.duckdb"
    sql = sql_path.read_text(encoding="utf-8").replace("__OUTPUT_DIR__", str(output).replace("'", "''"))
    connection = duckdb.connect(str(database))
    try:
        connection.execute(sql)
    finally:
        connection.close()
    return {"status": "complete", "database": str(database)}


def build(args: argparse.Namespace) -> dict[str, Any]:
    pa, pq = load_arrow()
    project_root = Path(args.project_root).resolve()
    output = (project_root / args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    sources = [load_source((project_root / value).resolve()) for value in args.source]
    candidates = load_candidates([(project_root / value).resolve() for value in args.candidate])
    frozen_splits = load_frozen_splits((project_root / args.frozen_split).resolve() if args.frozen_split else None)
    entities, outcomes, sensitivity = {}, {}, {}
    for source in sources:
        for token, entity in source["entities"].items():
            if token in entities:
                raise ValueError(f"duplicate token across source runs: {token}")
            entities[token] = entity, source
        for token, outcome in source["outcomes"].items():
            outcomes[token] = outcome, source
        for row in iter_jsonl(source["path"] / "sensitivity_zero_activity_outcomes.jsonl"):
            token = token_of(row)
            if token:
                if token in sensitivity:
                    raise ValueError(f"duplicate sensitivity outcome: {token}")
                sensitivity[token] = row, source

    train_end, validation_end, test_end = map(parse_time, (args.train_end, args.validation_end, args.test_end))
    if args.config:
        config = json.loads((project_root / args.config).read_text(encoding="utf-8"))
        split = config.get("split") or {}
        train_end = train_end or parse_time(split.get("train_end"))
        validation_end = validation_end or parse_time(split.get("validation_end"))
        test_end = test_end or parse_time(split.get("test_end"))

    sinks = {name: ParquetSink(output / f"{name}.parquet", name, pa, pq) for name in TABLE_FIELDS}
    event_count = duplicate_event_count = 0
    try:
        token_rows, pool_rows_all, outcome_rows, sensitivity_rows, censor_rows = [], [], [], [], []
        for token in sorted(entities):
            entity, source = entities[token]
            outcome = outcomes[token][0]
            source_name, retrieved_at = source["name"], text(source["report"].get("retrieved_at"))
            token_rows.append(token_row(entity, outcome, source_name))
            pool_rows_all.extend(pool_rows(entity, source_name))
            outcome_rows.append(outcome_row(outcome, source_name, retrieved_at))
            if token in sensitivity:
                sensitivity_rows.append(sensitivity_row(sensitivity[token][0], source_name))
            if outcome.get("label") == "censored":
                censor_rows.append({"token_address": token, "source_dataset": source_name, "label_definition": text(outcome.get("label_definition")), "reason": text(outcome.get("censoring_reason")), "retrieved_at": retrieved_at})
        for name, rows in (("tokens", token_rows), ("pools", pool_rows_all), ("outcomes", outcome_rows), ("sensitivity_outcomes", sensitivity_rows), ("censoring", censor_rows)):
            sinks[name].append(rows)

        candidate_rows, sampling_rows, split_rows = [], [], []
        for token in sorted(set(entities) | set(candidates)):
            entity_info, outcome_info, candidate = entities.get(token), outcomes.get(token), candidates.get(token)
            entity = entity_info[0] if entity_info else None
            outcome = outcome_info[0] if outcome_info else None
            source_name = entity_info[1]["name"] if entity_info else None
            if candidate:
                candidate_rows.append(candidate_row(candidate, source_name))
            sampling_rows.append(sampling_row(token, candidate, entity, outcome, source_name))
            if frozen_splits:
                key = (token, source_name or "")
                if key not in frozen_splits:
                    raise ValueError(f"missing frozen split assignment for {key}")
                partition, reason = frozen_splits[key]
            else:
                partition, reason = partition_for_outcome(outcome, train_end=train_end, validation_end=validation_end, test_end=test_end)
            split_rows.append(split_row(token, entity, outcome, source_name, partition, reason))
        for name, rows in (("candidates", candidate_rows), ("sampling", sampling_rows), ("splits", split_rows)):
            sinks[name].append(rows)

        accumulators = {token: feature_accumulator() for token in entities}
        key_index = EventKeyIndex(output / ".event_keys.sqlite", args.keep_event_key_index)
        event_batch, request_batch = [], []
        try:
            for source in sources:
                source_name = source["name"]
                for raw_event in iter_jsonl(source["path"] / "events.jsonl"):
                    event = normalize_event(raw_event, source_name)
                    if not key_index.add(event):
                        duplicate_event_count += 1
                        continue
                    event_batch.append(event)
                    event_count += 1
                    entity_info = entities.get(event["token_address"])
                    if entity_info:
                        outcome = outcomes[event["token_address"]][0]
                        update_features(accumulators[event["token_address"]], event, t0=parse_time(outcome.get("t0")), cutoff=parse_time(outcome.get("cutoff")))
                    if len(event_batch) >= args.batch_size:
                        sinks["events"].append(event_batch)
                        event_batch = []
                for raw_request in iter_jsonl(source["path"] / "manifests" / "request_log.jsonl"):
                    request_batch.append(request_row(raw_request, source_name))
                    if len(request_batch) >= args.batch_size:
                        sinks["request_log"].append(request_batch)
                        request_batch = []
            sinks["events"].append(event_batch)
            sinks["request_log"].append(request_batch)
        finally:
            key_index.close()
        sinks["features"].append([
            feature_row(token, source["name"], outcomes[token][0], entity, accumulators[token])
            for token, (entity, source) in sorted(entities.items())
        ])
        sinks["feature_audit"].append([
            feature_audit_row(token, source["name"], outcomes[token][0], accumulators[token])
            for token, (entity, source) in sorted(entities.items())
        ])
    finally:
        for sink in sinks.values():
            sink.close()

    duckdb_status = {"status": "skipped_by_flag"} if args.skip_duckdb else run_duckdb(output, project_root)
    manifest = {
        "manifest_version": "data-product-0.2",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "sources": [{"path": str(source["path"]), "dataset": source["name"], "token_rows": len(source["entities"]), "outcome_rows": len(source["outcomes"]), "retrieved_at": source["report"].get("retrieved_at")} for source in sources],
        "candidate_files": [str((Path(args.project_root) / value).resolve()) for value in args.candidate],
        "counts": {
            "tokens": len(entities), "candidates": len(candidates), "candidate_only_tokens": len(set(candidates) - set(entities)),
            "events": event_count, "duplicate_events_skipped": duplicate_event_count, "outcomes": len(outcomes),
            "censored": sum(row[0].get("label") == "censored" for row in outcomes.values()),
            "supervised_labels": sum(row[0].get("label") in PRIMARY_LABELS for row in outcomes.values()),
        },
        "contract": {"observation_days": 7, "followup_days": 90, "volume_threshold_usd": "1000", "volume_event_type": "swap", "censored_excluded_from_supervised_labels": True, "post_cutoff_events_excluded_from_features": True, "normalized_event_schema": "week1-events-0.2"},
        "validation": {"event_key": ["token_address", "transaction_hash", "log_index"], "split_boundaries": {"train_end": iso_time(train_end), "validation_end": iso_time(validation_end), "test_end": iso_time(test_end)}, "split_frozen_before_test_labels": str((project_root / args.frozen_split).resolve()) if args.frozen_split else "not_verified", "natural_prevalence_test_policy": not bool(args.frozen_split), "split_policy": "frozen_target_manifest" if args.frozen_split else "chronological_boundaries"},
        "parquet": {"engine": "pyarrow", "tables": sorted(TABLE_FIELDS)},
        "duckdb": duckdb_status,
    }
    write_json(output / "run_manifest.json", manifest)
    return manifest


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--candidate", action="append", default=[])
    parser.add_argument("--frozen-split")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/week1_config.json")
    parser.add_argument("--train-end")
    parser.add_argument("--validation-end")
    parser.add_argument("--test-end")
    parser.add_argument("--batch-size", type=int, default=50000)
    parser.add_argument("--keep-event-key-index", action="store_true")
    parser.add_argument("--skip-duckdb", action="store_true")
    return parser


if __name__ == "__main__":
    result = build(make_parser().parse_args())
    print(json.dumps({"counts": result["counts"]}, indent=2, sort_keys=True))
