"""Discover unlabeled Ethereum addresses from reproducible historical block samples.

This collects a small address-discovery sample, not Etherscan training histories.
Transaction participation never establishes a benign label.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from ..io import load_json, read_records, save_json, sha256_file, write_records
from ..progress import progress_bar
from ..transactions import address

DEFAULT_RPC = "https://eth-mainnet.g.alchemy.com/public"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class HistoricalBlockClient:
    def __init__(self, out, *, allow_network=False, rpc_env="ETHEREUM_RPC_URL", transport=None):
        self.out = Path(out)
        self.allow_network = allow_network
        self.transport = transport
        self.endpoint = os.environ.get(rpc_env) or os.environ.get("PHISHING_RPC_URL") or DEFAULT_RPC
        parts = urlsplit(self.endpoint)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("background_rpc_requires_https_without_embedded_credentials_or_query")
        self.provider = parts.hostname
        self.rpc_env = rpc_env
        self.last_call = 0.0
        self.network_requests = 0
        self.providers = set()

    def call(self, method, params):
        query = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        path = self.out / "raw_requests" / f"{_digest(query)}.json"
        if path.exists():
            cached = load_json(path)
            if cached.get("request") != query or cached.get("response_sha256") != _digest(cached.get("result")):
                raise ValueError("historical_rpc_cache_checksum_mismatch")
            self.providers.add(cached["provider"])
            return cached["result"]
        if not self.transport and not self.allow_network:
            raise ValueError("background_discovery_requires_allow_network_or_cached_requests")
        failure = "unknown"
        for attempt in range(3):
            try:
                if self.transport:
                    result = self.transport(method, params)
                else:
                    delay = 2 / 3 - (time.monotonic() - self.last_call)
                    if delay > 0:
                        time.sleep(delay)
                    self.last_call = time.monotonic()
                    self.network_requests += 1
                    request = Request(self.endpoint, data=json.dumps(query).encode(),
                                      headers={"Content-Type": "application/json", "User-Agent": "scam-background/1"})
                    with urlopen(request, timeout=30) as response:
                        payload = response.read(10 * 1024 * 1024 + 1)
                    if len(payload) > 10 * 1024 * 1024:
                        raise ValueError("historical_rpc_response_size_limit")
                    payload = json.loads(payload)
                    if not isinstance(payload, dict) or payload.get("id") != 1 or payload.get("jsonrpc") != "2.0":
                        raise ValueError("invalid_json_rpc_envelope")
                    if payload.get("error"):
                        error = payload["error"]
                        failure = f"provider_error_{error.get('code', 'unknown')}" if isinstance(error, dict) else "provider_error"
                        raise ValueError(failure)
                    if payload.get("result") is None:
                        raise ValueError("missing_result")
                    result = payload["result"]
                if result is None:
                    raise ValueError("historical_rpc_missing_result")
                save_json(path, {"request": query, "result": result, "response_sha256": _digest(result),
                                 "provider": self.provider, "retrieved_at": datetime.now(timezone.utc).isoformat()})
                self.providers.add(self.provider)
                return result
            except (OSError, ValueError, TimeoutError) as error:
                failure = (str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError)
                           else type(error).__name__)
                if attempt == 2:
                    # Do not expose a private endpoint/token in exception text.
                    raise ValueError(f"historical_rpc_request_failed:{method}:{failure}; check network/RPC provider") from None
                time.sleep(0.5 * 2 ** attempt)

    def block(self, number, full=False):
        result = self.call("eth_getBlockByNumber", [hex(number), full])
        if (not isinstance(result, dict) or int(result.get("number", "-0x1"), 16) != number
                or not isinstance(result.get("hash"), str) or len(result["hash"]) != 66):
            raise ValueError("historical_rpc_invalid_block")
        int(result["timestamp"], 16)
        return result

    def cutoff_block(self, cutoff):
        high = int(self.call("eth_blockNumber", []), 16)
        low = 0
        if int(self.block(high)["timestamp"], 16) < cutoff:
            raise ValueError("background_cutoff_after_available_chain")
        while low < high:
            middle = (low + high + 1) // 2
            if int(self.block(middle)["timestamp"], 16) <= cutoff:
                low = middle
            else:
                high = middle - 1
        block = self.block(low)
        if int(block["timestamp"], 16) > cutoff:
            raise ValueError("background_cutoff_before_genesis")
        return low, block["hash"]


def discover_background(out, *, cutoff, seed=20261008, block_count=384,
                        allow_network=False, rpc_env="ETHEREUM_RPC_URL", progress="auto", transport=None):
    out = Path(out)
    if not isinstance(block_count, int) or isinstance(block_count, bool) or not 10 <= block_count <= 4096:
        raise ValueError("background_blocks_must_be_between_10_and_4096")
    recipe = {"version": "historical-address-discovery-1", "chain_id": 1, "cutoff": cutoff,
              "seed": seed, "block_count": block_count, "participants": ["from", "to"],
              "sampling": "one deterministic random block per equal block-height stratum"}
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        if manifest["recipe"] != recipe:
            raise ValueError("background_recipe_changed_use_a_new_snapshot")
        load_background_records(out, cutoff)
        return manifest
    client = HistoricalBlockClient(out, allow_network=allow_network, rpc_env=rpc_env, transport=transport)
    if int(client.call("eth_chainId", []), 16) != 1:
        raise ValueError("background_discovery_requires_ethereum_mainnet")
    end_block, end_hash = client.cutoff_block(cutoff)
    if end_block + 1 < block_count:
        raise ValueError("too_many_background_strata_for_block_range")
    randomizer = random.Random(seed)
    numbers = [randomizer.randrange(i * (end_block + 1) // block_count,
                                   (i + 1) * (end_block + 1) // block_count) for i in range(block_count)]
    rows, blocks, transaction_count = {}, [], 0
    for number in progress_bar(numbers, mode=progress, desc="Historical background blocks", unit="block"):
        block = client.block(number, full=True)
        timestamp = int(block["timestamp"], 16)
        if timestamp > cutoff or not isinstance(block.get("transactions"), list):
            raise ValueError("background_block_outside_cutoff_or_missing_transactions")
        blocks.append({"number": number, "hash": block["hash"], "timestamp": timestamp})
        for tx in block["transactions"]:
            if (not isinstance(tx, dict) or tx.get("blockHash") != block["hash"]
                    or int(tx.get("blockNumber", "-0x1"), 16) != number
                    or not isinstance(tx.get("hash"), str) or len(tx["hash"]) != 66):
                raise ValueError("background_transaction_missing_block_provenance")
            transaction_count += 1
            for role in ("from", "to"):
                entity = address(tx.get(role))
                if entity and entity != "0x" + "0" * 40 and entity not in rows:
                    rows[entity] = {"address": entity, "block_number": number, "block_hash": block["hash"],
                                    "timestamp": timestamp, "transaction_hash": tx["hash"], "role": role}
    candidates = sorted(rows.values(), key=lambda row: row["address"])
    if not candidates:
        raise ValueError("no_historical_background_addresses")
    write_records(out / "candidates.jsonl", candidates)
    save_json(out / "sampled_blocks.json", blocks)
    manifest = {"recipe": recipe, "end_block": end_block, "end_block_hash": end_hash,
                "candidate_addresses": len(candidates), "sampled_transactions": transaction_count,
                "candidates_sha256": sha256_file(out / "candidates.jsonl"),
                "sampled_blocks_sha256": sha256_file(out / "sampled_blocks.json"),
                "providers": sorted(client.providers), "rpc_env": rpc_env,
                "meaning": "unlabeled historical transaction participants; never verified benign",
                "bias": "active addresses have a higher inclusion probability; this is not uniform address sampling"}
    save_json(manifest_path, manifest)
    return manifest


def load_background_records(directory, cutoff, *, task_id=None):
    directory = Path(directory)
    manifest = load_json(directory / "manifest.json")
    if (manifest["recipe"]["cutoff"] != cutoff or manifest["recipe"]["chain_id"] != 1
            or sha256_file(directory / "candidates.jsonl") != manifest["candidates_sha256"]
            or sha256_file(directory / "sampled_blocks.json") != manifest["sampled_blocks_sha256"]):
        raise ValueError("historical_background_snapshot_mismatch")
    rows, seen = [], set()
    blocks = {row["number"]: row for row in load_json(directory / "sampled_blocks.json")}
    for number, row in enumerate(read_records(directory / "candidates.jsonl"), 1):
        entity = address(row.get("address"))
        block = blocks.get(row.get("block_number"))
        if (not entity or entity in seen or row["timestamp"] > cutoff or not block
                or row["block_hash"] != block["hash"] or row["timestamp"] != block["timestamp"]
                or row["role"] not in {"from", "to"}
                or not isinstance(row.get("transaction_hash"), str) or len(row["transaction_hash"]) != 66):
            raise ValueError("invalid_historical_background_candidate")
        seen.add(entity)
        rows.append({**({"task_id": task_id} if task_id else {}), "entity_id": entity, "mapped_label": None,
                     "label_status": "unlabeled", "role": "unknown", "audit_decision": "accepted",
                     "admission_basis": "historical_transaction_presence", "training_positive": False,
                     "source_id": "historical_rpc", "source_file": "historical_rpc",
                     "source_row": number, "source_sha256": manifest["candidates_sha256"],
                     "label_version": manifest["candidates_sha256"], "label_available_at": None,
                     "valid_from": None, "valid_to": None, "raw_record": row,
                     "evidence_ref": f"ethereum:1:transaction:{row['transaction_hash']}"})
    if len(rows) != manifest["candidate_addresses"]:
        raise ValueError("historical_background_count_mismatch")
    return rows, manifest
