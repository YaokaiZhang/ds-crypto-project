"""Normalize archived Etherscan facts with units, direction, and raw lineage."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .transactions import address, decode_v2_log, integer

SOURCE_KINDS = {"txlist": "normal", "txlistinternal": "internal", "tokentx": "erc20",
                "getLogs": "logs", "eth_getTransactionReceipt": "receipt",
                "eth_getBlockByNumber": "block"}


def _success(row: dict[str, Any]) -> bool | None:
    if "isError" in row:
        if str(row["isError"]) not in ("0", "1"):
            raise ValueError("invalid_transaction_error_flag")
        success = str(row["isError"]) == "0"
        receipt_status = integer(row.get("txreceipt_status"))
        if receipt_status is not None and success != (receipt_status == 1):
            raise ValueError("conflicting_transaction_success_flags")
        return success
    value = row.get("txreceipt_status", row.get("status"))
    number = integer(value)
    return None if number is None else number == 1


def _kind(row: dict[str, Any]) -> str:
    explicit = row.get("source_kind") or row.get("action")
    if explicit:
        return SOURCE_KINDS.get(str(explicit), str(explicit))
    if "topics" in row:
        return "logs"
    if "traceId" in row or "trace_path" in row:
        return "internal"
    if "tokenDecimal" in row:
        return "erc20"
    return "normal"


def _flatten(payload: Any, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    context = dict(context or {})
    if isinstance(payload, list):
        return [item for index, row in enumerate(payload) for item in _flatten(row, {**context, "source_row": index})]
    if not isinstance(payload, dict):
        raise ValueError("raw_payload_must_be_object_or_array")
    if "response" in payload or "rows" in payload:
        request = payload.get("request", {})
        request_chain = request.get("chainid", request.get("chain_id"))
        if request_chain is not None and integer(request_chain) != 1:
            raise ValueError("unsupported_chain")
        context.update(source_kind=payload.get("source_kind") or request.get("action"),
                       request_id=payload.get("request_id"), raw_path=payload.get("raw_path"),
                       retrieved_at=payload.get("retrieved_at"))
        if request_chain is not None:
            context["chain_id"] = 1
        for key in ("timestamp", "timeStamp", "block_number", "blockNumber"):
            if payload.get(key) is not None:
                context[key] = payload[key]
        return _flatten(payload.get("response", payload.get("rows")), context)
    if "result" in payload:
        result = payload["result"]
        if payload.get("error"):
            raise ValueError("raw_api_error_or_unexpected_result")
        if str(payload.get("status")) == "0":
            message = (str(payload.get("message", "")) + " " + str(result)).lower()
            empty = any(value in message for value in ("no transactions found", "no records found", "no logs found"))
            if empty and result in ([], "", "No transactions found", "No records found", "No logs found"):
                return []
            raise ValueError("raw_api_error_or_unexpected_result")
        if isinstance(result, (list, dict)):
            return _flatten(result, context)
        if result is None and _kind(context) in ("receipt", "block"):
            raise ValueError("missing_receipt_or_block")
        raise ValueError("raw_api_error_or_unexpected_result")
    if "logs" in payload and _kind(context) == "receipt":
        result = []
        if _success(payload) is False and payload.get("logs"):
            raise ValueError("failed_receipt_has_persistent_logs")
        for log in payload.get("logs", []):
            result.append({**context, "source_kind": "logs", "success": _success(payload), **log})
        return result
    if _kind(context) == "block":
        return []
    return [{**context, **payload}]


def normalize_records(raw_rows: Iterable[dict[str, Any]],
                      known_entities: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Strictly normalize facts; rejected rows remain in the audit.

    Receipt logs need their historical block timestamp in the wrapper or row.
    Missing logIndex is rejected instead of inventing a transfer identity.
    """
    rows: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows):
        try:
            rows.extend(_flatten(raw, {"source_row": index}))
        except (ValueError, TypeError) as exc:
            invalid.append({"row": index, "reason": str(exc)})
    receipt_transfers = set()
    token_metadata: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if _kind(row) == "logs":
            try:
                decoded = decode_v2_log(row)
                if decoded and decoded["relation"] == "erc20_transfer":
                    receipt_transfers.add((str(row.get("transactionHash") or row.get("tx_hash") or "").lower(),
                                           decoded["src"], decoded["dst"], decoded["asset"], decoded["raw_amount"]))
            except ValueError:
                pass
    hydrated_history = 0
    retained = []
    for row in rows:
        key = (str(row.get("hash") or "").lower(), address(row.get("from")), address(row.get("to")),
               address(row.get("contractAddress")), str(integer(row.get("value"))))
        decimals = integer(row.get("tokenDecimal"))
        if _kind(row) == "erc20" and key in receipt_transfers and (decimals is None or 0 <= decimals <= 255):
            token_metadata.setdefault(key, []).append(row)
            if integer(row.get("logIndex", row.get("log_index"))) is None:
                hydrated_history += 1
            else:
                retained.append(row)
        else:
            retained.append(row)
    rows = retained
    pools = {str(k).lower() for k, v in (known_entities or {}).items()
             if v == "pool" or isinstance(v, dict) and v.get("role") == "pool"}
    for row in rows:
        if _kind(row) == "logs":
            try:
                decoded = decode_v2_log(row)
                if decoded and decoded["relation"] == "pair_created":
                    pools.add(decoded["pool"])
            except ValueError:
                pass
    events: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    raw_count = len(rows)
    for index, row in enumerate(rows):
        try:
            kind = _kind(row)
            chain = integer(row.get("chain_id", row.get("chainId")), default=1)
            if chain != 1:
                raise ValueError("unsupported_chain")
            tx_hash = str(row.get("hash") or row.get("transactionHash") or row.get("tx_hash") or "").lower()
            if len(tx_hash) != 66 or not tx_hash.startswith("0x"):
                raise ValueError("missing_or_invalid_tx_hash")
            int(tx_hash[2:], 16)
            timestamp = integer(row.get("timeStamp", row.get("timestamp")))
            block = integer(row.get("blockNumber", row.get("block_number")))
            if timestamp is None or timestamp < 0 or block is None or block < 0:
                raise ValueError("missing_historical_time_or_block")
            common = {"chain_id": chain, "timestamp": timestamp, "block_number": block,
                      "block_hash": str(row.get("blockHash") or row.get("block_hash") or "").lower() or None,
                      "tx_hash": tx_hash, "address": address(row.get("address") or row.get("contractAddress")),
                      "asset": None, "raw_amount": None, "decimals": None,
                      "success": row.get("success") if isinstance(row.get("success"), bool) else _success(row),
                      "lineage": {key: row.get(key) for key in ("request_id", "raw_path", "retrieved_at", "source_row")},
                      "source_kind": kind}
            if "synthetic" in row:
                common["synthetic"] = bool(row["synthetic"])
            output = []
            if kind == "logs":
                if row.get("removed") is True:
                    raise ValueError("removed_noncanonical_log")
                log_index = integer(row.get("logIndex", row.get("log_index")))
                if log_index is None or log_index < 0:
                    raise ValueError("missing_log_index")
                decoded = decode_v2_log(row)
                if decoded is None:
                    continue
                if common["success"] is False:
                    raise ValueError("persistent_failed_log")
                if decoded["relation"] == "erc20_transfer":
                    metadata_key = (tx_hash, decoded["src"], decoded["dst"], decoded["asset"], decoded["raw_amount"])
                    metadata = token_metadata.get(metadata_key, [])
                    decimals = {integer(item.get("tokenDecimal")) for item in metadata
                                if integer(item.get("tokenDecimal")) is not None}
                    if len(decimals) > 1:
                        raise ValueError("conflicting_token_decimals_metadata")
                    common["decimals"] = next(iter(decimals)) if decimals else None
                    if metadata:
                        common["lineage"]["token_metadata_sources"] = [
                            {key: item.get(key) for key in ("request_id", "raw_path", "retrieved_at", "source_row")}
                            for item in metadata]
                if decoded["relation"] == "erc20_transfer" and common["address"] in pools:
                    decoded["relation"] = "lp_transfer"
                common["success"] = True
                output = [{**common, **decoded, "log_index": log_index,
                           "event_id": f"1:{tx_hash}:log:{log_index}"}]
            elif kind == "erc20":
                log_index = integer(row.get("logIndex", row.get("log_index")))
                if log_index is None:
                    raise ValueError("erc20_history_requires_receipt_log_index")
                amount = integer(row.get("value"))
                decimals = integer(row.get("tokenDecimal"))
                if amount is None or amount < 0 or decimals is not None and not 0 <= decimals <= 255:
                    raise ValueError("invalid_token_amount_or_decimals")
                if common["success"] is False:
                    raise ValueError("failed_transaction_token_transfer")
                common["success"] = True
                output = [{**common, "event_id": f"1:{tx_hash}:log:{log_index}", "log_index": log_index,
                           "src": address(row.get("from")), "dst": address(row.get("to")),
                           "relation": "lp_transfer" if common["address"] in pools else "erc20_transfer",
                           "asset": address(row.get("contractAddress")),
                           "raw_amount": str(amount), "decimals": decimals}]
            elif kind in ("normal", "internal"):
                src = address(row.get("from"))
                dst = address(row.get("to")) or address(row.get("contractAddress"))
                amount = integer(row.get("value"))
                if amount is None or amount < 0:
                    raise ValueError("missing_or_invalid_raw_amount")
                common.update(src=src, dst=dst, asset="ETH", raw_amount=str(amount), decimals=18)
                trace = str(row.get("traceId", row.get("trace_path", "")))
                if kind == "internal" and not trace:
                    raise ValueError("missing_trace_path")
                prefix = f"1:{tx_hash}:trace:{trace}" if kind == "internal" else f"1:{tx_hash}:normal"
                common.update(trace_path=trace if kind == "internal" else None,
                              input=row.get("input"), method_id=row.get("methodId"),
                              gas_used=integer(row.get("gasUsed")), gas_price=integer(row.get("gasPrice")))
                if common["success"] is False:
                    output.append({**common, "event_id": prefix + ":failed_call", "relation": "failed_call",
                                   "raw_amount": None, "attempted_raw_amount": str(amount)})
                else:
                    if amount > 0 and common["success"] is True:
                        output.append({**common, "event_id": prefix + ":eth", "relation": f"{kind if kind == 'internal' else 'external'}_eth"})
                    if amount == 0 or row.get("input") not in (None, "", "0x") or kind == "internal" or common["success"] is None:
                        output.append({**common, "event_id": prefix + ":call", "relation": "call", "raw_amount": None,
                                       "attempted_raw_amount": str(amount) if common["success"] is None else None})
                    if row.get("type") == "create" or not address(row.get("to")) and dst:
                        output.append({**common, "event_id": prefix + ":deployed", "relation": "deployed", "raw_amount": None})
            else:
                raise ValueError("unsupported_source_kind")
            for event in output:
                if not event.get("src") or not event.get("dst"):
                    raise ValueError("missing_event_participant")
                if event["event_id"] in events:
                    duplicates.append(event["event_id"])
                    previous = events[event["event_id"]]
                    core = ("src", "dst", "relation", "asset", "raw_amount", "timestamp", "block_number", "success",
                            "pool", "token0", "token1", "amount0_in", "amount1_in", "amount0_out", "amount1_out",
                            "amount0", "amount1", "reserve0", "reserve1")
                    if any(previous.get(key) != event.get(key) for key in core):
                        raise ValueError("conflicting_duplicate_event")
                    for key in ("decimals", "block_hash"):
                        if previous.get(key) is not None and event.get(key) is not None and previous[key] != event[key]:
                            raise ValueError(f"conflicting_duplicate_{key}")
                        if previous.get(key) is None and event.get(key) is not None:
                            previous[key] = event[key]
                    previous["lineage"].setdefault("duplicate_sources", []).append(event["lineage"])
                else:
                    events[event["event_id"]] = event
        except (ValueError, TypeError, KeyError) as exc:
            invalid.append({"row": index, "reason": str(exc), "request_id": row.get("request_id")})
    root_money = {(e["tx_hash"], e["src"], e["dst"], e["raw_amount"]) for e in events.values()
                  if e["relation"] == "external_eth"}
    suppressed = []
    for key, event in list(events.items()):
        if event["relation"] == "internal_eth" and event.get("trace_path") == "0" and (
                event["tx_hash"], event["src"], event["dst"], event["raw_amount"]) in root_money:
            suppressed.append(key)
            del events[key]
    ordered = sorted(events.values(), key=lambda e: (e["block_number"], e["timestamp"], e["event_id"]))
    return ordered, {"raw_rows": raw_count, "normalized_events": len(ordered),
                     "invalid_records": invalid, "duplicate_records": duplicates,
                     "suppressed_root_internal": suppressed, "hydrated_erc20_history": hydrated_history,
                     "missing_success_events": [event["event_id"] for event in ordered if event["success"] is None],
                     "complete": not invalid}


def normalize_bundle(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(path)
    files = sorted((path / "raw_requests").glob("*.json")) if path.is_dir() else [path]
    if path.is_dir() and not files:
        files = sorted(path.glob("*.jsonl"))
    if not files:
        raise ValueError("no_raw_files")
    rows = []
    block_times: dict[int, int] = {}
    payloads = []
    for file in files:
        if file.suffix == ".jsonl":
            payload = [json.loads(line) for line in file.read_text().splitlines() if line.strip()]
        else:
            payload = json.loads(file.read_text())
        if isinstance(payload, dict):
            payload["raw_path"] = str(file.resolve())
            action = payload.get("request", {}).get("action")
            if action == "eth_getBlockByNumber":
                block = payload.get("response", {}).get("result", {})
                number, stamp = integer(block.get("number")), integer(block.get("timestamp"))
                if number is not None and stamp is not None:
                    block_times[number] = stamp
                continue
            if action and action not in SOURCE_KINDS:
                continue
        payloads.append(payload)
    bundle_errors = []
    for payload in payloads:
        try:
            rows.extend(_flatten(payload))
        except (ValueError, TypeError) as exc:
            bundle_errors.append({"raw_path": payload.get("raw_path") if isinstance(payload, dict) else None,
                                  "reason": str(exc)})
    for row in rows:
        number = integer(row.get("blockNumber", row.get("block_number")))
        stamp = integer(row.get("timeStamp", row.get("timestamp")))
        if number is not None and stamp is not None:
            block_times[number] = stamp
    for row in rows:
        number = integer(row.get("blockNumber", row.get("block_number")))
        if integer(row.get("timeStamp", row.get("timestamp"))) is None and number in block_times:
            row["timestamp"] = block_times[number]
    known_pools = {}
    target_path = path / "targets_with_coverage.jsonl" if path.is_dir() else None
    if target_path and target_path.is_file():
        for line in target_path.read_text().splitlines():
            if line.strip():
                target = json.loads(line)
                for value in target.get("pools", []):
                    if pool := address(value):
                        known_pools[pool] = "pool"
    events, audit = normalize_records(rows, known_entities=known_pools)
    if bundle_errors:
        audit["invalid_records"].extend(bundle_errors)
        audit["complete"] = False
    manifest_path = path / "manifest.json" if path.is_dir() else None
    if manifest_path and manifest_path.is_file() and json.loads(manifest_path.read_text()).get("complete") is not True:
        audit.update(complete=False, collection_incomplete=True)
    return events, audit
