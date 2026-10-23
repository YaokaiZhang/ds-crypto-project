"""TokenScout labels and explicit collection stages; never fit models."""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packages.collection import CollectionError, EtherscanClient, _now, _safe_error
from packages.io import atomic_bytes, load_json, read_records, save_json, sha256_file, write_records
from packages.provider_access import ethereum_rpc_url
from packages.token import UNISWAP_V2_FACTORY, token_scope
from packages.token_sources import SnapshotClient, verify_token_targets
from packages.transactions import address, decode_v2_log, integer
from packages.sources.phishing import _download

SOURCE_FILES = {
    "labels": ("token_labels_processed.csv", "1NVKGqZfCVTHNWgMDRAuppauBeYxMKIc9"),
    "mapping": ("token-dict.json", "1mVfUa9TwidBN3mEgQ-H31CGiY-52aM8H"),
}
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
PAIR_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
QUOTE_PRIORITY = [WETH, "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                  "0xdac17f958d2ee523a2206206994597c13d831ec7", "0x6b175474e89094c44da98b954eedeac495271d0f"]
ZERO = "0x" + "0" * 40
DEFAULT_CUTOFF = 1677628799  # 2023-02-28T23:59:59Z, source coverage anchor only.
STAGES = ("sources", "audit", "discover", "verify", "prepare")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _freeze(path, value):
    if path.exists():
        if load_json(path) != value:
            raise ValueError("rug_pull_snapshot_inputs_changed_use_a_new_snapshot")
    else:
        save_json(path, value)


def _manifest(path, files, **metadata):
    result = {**metadata, "artifacts": {os.path.relpath(p, path.parent): sha256_file(p) for p in files}}
    _freeze(path, result)
    return result


def _verified(path):
    result = load_json(path)
    for relative, checksum in result["artifacts"].items():
        if sha256_file(path.parent / relative) != checksum:
            raise ValueError("rug_pull_artifact_checksum_mismatch")
    return result


def _csv(path, rows):
    stream = io.StringIO(newline="")
    fields = ["sample_id", "token_address", "pool_address", "label", "source", "source_label",
              "source_entity_ids", "cutoff", "label_policy"]
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "source_entity_ids": json.dumps(row.get("source_entity_ids", []))})
    atomic_bytes(path, stream.getvalue().encode())


def freeze_sources(out, settings, allow_network):
    directory = out / "sources"
    manifest = directory / "manifest.json"
    local = settings.get("source_files", {})
    if local and set(local) != set(SOURCE_FILES):
        raise ValueError("tokenscout_source_files_require_labels_and_mapping")
    if manifest.exists():
        result = _verified(manifest)
        for key, filename in local.items():
            if sha256_file(filename) != result["artifacts"][SOURCE_FILES[key][0]]:
                raise ValueError("rug_pull_source_file_changed")
        return result
    if not local and not allow_network:
        raise ValueError("tokenscout_download_requires_allow_network_or_source_files")
    files, sources = [], []
    for key, (filename, file_id) in SOURCE_FILES.items():
        url = "https://drive.google.com/uc?export=download&id=" + file_id
        destination = directory / filename
        # Retain an interrupted successful download instead of downloading again.
        data = Path(local[key]).read_bytes() if local else (
            destination.read_bytes() if destination.exists() else _download(url, limit=32 * 1024 * 1024))
        if key == "labels":
            header = csv.DictReader(io.StringIO(data.decode("utf-8-sig"))).fieldnames
            if not {"tokens", "t2-labels"}.issubset(header or []):
                raise ValueError("invalid_tokenscout_label_schema")
        elif not isinstance(json.loads(data), dict):
            raise ValueError("invalid_tokenscout_mapping_schema")
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError("rug_pull_partial_source_changed")
        atomic_bytes(destination, data)
        files.append(destination)
        sources.append({"name": key, "url": url, "file": filename, "file_id": file_id,
                        "bytes": len(data), "transport": "local" if local else "https"})
    return _manifest(manifest, files, version="tokenscout-sources-1", retrieved_at=_now(), sources=sources)


def _mapping(path):
    # Preserve repeated JSON keys so ambiguous mappings cannot silently overwrite.
    pairs = json.loads(path.read_text(), object_pairs_hook=lambda values: values)
    by_id, invalid = defaultdict(set), 0
    for key, value in pairs:
        if address(key):
            entity, token_id = address(key), integer(value)
        else:
            entity, token_id = address(value), integer(key)
        if entity in (None, ZERO) or token_id is None or token_id < 0:
            invalid += 1
            continue
        by_id[str(token_id)].add(entity)
    ambiguous = {key for key, values in by_id.items() if len(values) != 1}
    return {key: next(iter(values)) for key, values in by_id.items() if key not in ambiguous}, {
        "entries": len(pairs), "invalid_entries": invalid, "ambiguous_ids": len(ambiguous),
        "usable_ids": len(by_id) - len(ambiguous)}, ambiguous


def audit_labels(out, settings):
    _verified(out / "sources/manifest.json")
    directory = out / "labels"
    options = settings.get("selection", {})
    previous = load_json(directory / "recipe.json") if (directory / "recipe.json").exists() else {}
    recipe = {"version": "tokenscout-source-labels-1", "positive_count": options.get("positive_count", previous.get("positive_count", 1500)),
              "negative_count": options.get("negative_count", previous.get("negative_count")),
              "seed": options.get("seed", previous.get("seed", 20261022)),
              "source_manifest_sha256": sha256_file(out / "sources/manifest.json"),
              "label_mapping": {"rugpull": 1, "truthworthy": 0}}
    selection_stage = options.get("selection_stage", previous.get("selection_stage", "before_pool" if previous else "after_pool_verification"))
    if selection_stage not in {"before_pool", "after_pool_verification"}:
        raise ValueError("invalid_rug_pull_selection_stage")
    if selection_stage == "after_pool_verification":
        recipe.update(version="tokenscout-source-labels-2", selection_stage=selection_stage)
    for name in ("positive_count", "negative_count"):
        if recipe[name] is not None and (type(recipe[name]) is not int or recipe[name] < 1):
            raise ValueError("invalid_rug_pull_" + name)
    if type(recipe["seed"]) is not int:
        raise ValueError("invalid_rug_pull_seed")
    _freeze(directory / "recipe.json", recipe)
    if (directory / "manifest.json").exists():
        return _verified(directory / "manifest.json")
    mapping, mapping_quality, ambiguous = _mapping(out / "sources/token-dict.json")
    with (out / "sources/token_labels_processed.csv").open(encoding="utf-8-sig") as source:
        raw = list(csv.DictReader(source))
    groups, rejected, raw_counts = defaultdict(list), [], Counter()
    mapped_rows = 0
    for line, row in enumerate(raw, 2):
        subtype = row["t2-labels"].strip().lower()
        raw_counts[subtype] += 1
        token_id = integer(row["tokens"])
        token_id = str(token_id) if token_id is not None else None
        entity = mapping.get(token_id)
        item = {"source_row": line, "source_entity_id": row["tokens"], "source_label": subtype,
                "token_address": entity}
        if entity is None:
            rejected.append({**item, "reason": "ambiguous_mapping" if token_id in ambiguous else "missing_or_invalid_mapping"})
        else:
            mapped_rows += 1
            groups[entity].append(item)
    cleaned, duplicates, conflicting, conflict_rows, excluded_other = [], 0, 0, 0, 0
    for entity, items in sorted(groups.items()):
        subtypes = {item["source_label"] for item in items}
        if len(subtypes) > 1:
            conflicting += 1
            conflict_rows += len(items)
            rejected.extend({**item, "reason": "conflicting_token_labels"} for item in items)
            continue
        subtype = next(iter(subtypes))
        duplicates += len(items) - 1
        if subtype not in recipe["label_mapping"]:
            excluded_other += len(items)
            continue
        label = recipe["label_mapping"][subtype]
        cleaned.append({"sample_id": "ts-" + _digest(entity)[:24], "task_id": "rug_pull", "chain_id": 1,
                        "entity_id": entity, "token_address": entity, "label": label, "mapped_label": label,
                        "source": "tokenscout", "source_label": subtype,
                        "source_entity_ids": sorted({item["source_entity_id"] for item in items}),
                        "source_rows": [item["source_row"] for item in items],
                        "label_policy": "tokenscout-source-defined-retrospective-1",
                        "label_status": "source_defined_positive" if label else "source_defined_negative",
                        "valid_from": None, "valid_to": None, "label_available_at": None,
                        "incident_onset": None, "incident_tx": None, "controller_evidence_ref": None,
                        "training_eligible": False,
                        "evidence_ref": str((out / "sources/token_labels_processed.csv").resolve())})
    selected = []
    for label, name in ((1, "positive_count"), (0, "negative_count")):
        candidates = sorted((r for r in cleaned if r["label"] == label),
                            key=lambda r: _digest([recipe["seed"], r["token_address"]]))
        selected.extend(candidates if recipe[name] is None or selection_stage == "after_pool_verification" else candidates[:recipe[name]])
    write_records(directory / "cleaned_labels.jsonl", cleaned)
    write_records(directory / "selected_labels.jsonl", selected)
    write_records(directory / "rejected.jsonl", rejected)
    _csv(directory / "cleaned_labels.csv", cleaned)
    _csv(directory / "selected_labels.csv", selected)
    counts = {"raw_rows": len(raw), "raw_label_counts": dict(raw_counts), "mapping": mapping_quality,
              "mapped_rows": mapped_rows, "unmapped_rows": len(raw) - mapped_rows,
              "unique_mapped_addresses": len(groups), "duplicate_rows": duplicates,
              "conflicting_addresses": conflicting, "conflicting_rows": conflict_rows,
              "other_label_rows_excluded": excluded_other, "cleaned_tokens": len(cleaned),
              "cleaned_label_counts": dict(Counter(str(r["label"]) for r in cleaned)),
              "selected_tokens": len(selected), "selected_label_counts": dict(Counter(str(r["label"]) for r in selected)),
              "selection_before_pool_queries": selection_stage == "before_pool",
              "replacement_after_pool_failure": selection_stage == "after_pool_verification"}
    save_json(directory / "quality_audit.json", counts)
    return _manifest(directory / "manifest.json", [directory / name for name in
        ("recipe.json", "cleaned_labels.jsonl", "selected_labels.jsonl", "rejected.jsonl", "cleaned_labels.csv",
         "selected_labels.csv", "quality_audit.json")], version="tokenscout-label-audit-1", counts=counts)


class BatchSnapshotClient(SnapshotClient):
    """Small paced RPC batches, published into the standard single-call replay cache."""
    def __init__(self, out, settings=None):
        super().__init__(out, settings)
        self.errors = {}
        self.batch_requests = 0
        self.last_batch = 0.0

    def _path(self, params):
        return self.out / "raw_requests" / (_digest({"source": "ethereum_rpc", "params": params}) + ".json")

    def prefetch(self, queries, progress="off"):
        queries = list({_digest(q): q for q in queries}.values())
        size = int(self.settings.get("batch_size", 20))
        rate = float(self.settings.get("batch_rate_rps", .5))
        if not 1 <= size <= 20 or not 0 < rate <= 1:
            raise ValueError("invalid_rug_pull_rpc_batch_limits")
        pending = []
        for query in queries:
            if self._path(query).exists():
                self.request("ethereum_rpc", query)  # Validate existing response hash.
            else:
                pending.append(query)
        for start in range(0, len(pending), size):
            chunk = pending[start:start + size]
            body = [{"jsonrpc": "2.0", "id": i + 1, **query} for i, query in enumerate(chunk)]
            path = self.out / "batches" / (_digest(body) + ".json")
            if path.exists():
                bundle = load_json(path)
                if bundle["requests"] != body or bundle["response_sha256"] != self.checksum(bundle["responses"]):
                    raise CollectionError("rug_pull_batch_cache_checksum_mismatch")
            else:
                if not self.settings.get("allow_network") and not self.transport:
                    raise CollectionError("network_disabled_use_allow_network_or_fixtures")
                responses = None
                for attempt in range(int(self.settings.get("retries", 3)) + 1):
                    delay = 1 / rate - (time.monotonic() - self.last_batch)
                    if delay > 0 and not self.transport:
                        time.sleep(delay)
                    self.last_batch = time.monotonic()
                    try:
                        self.batch_requests += 1
                        if self.transport:
                            responses = [dict(self.transport("ethereum_rpc", query), id=i + 1)
                                         for i, query in enumerate(chunk)]
                        else:
                            endpoint = ethereum_rpc_url()
                            if not endpoint:
                                raise CollectionError("missing_ethereum_rpc_url")
                            request = Request(endpoint, data=json.dumps(body).encode(),
                                              headers={"Content-Type": "application/json"})
                            with urlopen(request, timeout=float(self.settings.get("timeout_seconds", 60))) as response:
                                responses = json.load(response)
                        if (isinstance(responses, list) and attempt < int(self.settings.get("retries", 3))
                                and any(isinstance(row, dict) and isinstance(row.get("error"), dict)
                                        and row["error"].get("code") == -32000
                                        and not self._contract_error(row["error"]) for row in responses)):
                            continue
                        break
                    except HTTPError as exc:
                        if exc.code in (401, 403, 429):
                            raise CollectionError(f"rug_pull_rpc_provider_access_or_quota_http_{exc.code}") from None
                        if attempt == int(self.settings.get("retries", 3)):
                            raise CollectionError(f"rug_pull_rpc_transport_http_{exc.code}") from None
                    except (URLError, TimeoutError, OSError):
                        if attempt == int(self.settings.get("retries", 3)):
                            raise CollectionError("rug_pull_rpc_transport_connection_failed") from None
                if (not isinstance(responses, list) or len(responses) != len(chunk)
                        or any(not isinstance(row, dict) for row in responses)):
                    raise CollectionError("rug_pull_rpc_batch_response_incomplete")
                if {row.get("id") for row in responses} != set(range(1, len(chunk) + 1)):
                    raise CollectionError("rug_pull_rpc_batch_ids_mismatch")
                bundle = {"requests": body, "responses": responses, "retrieved_at": _now(),
                          "response_sha256": self.checksum(responses)}
                # Provider failures must never become permanent per-token exclusions.
                for response in responses:
                    error = response.get("error")
                    if error and not self._contract_error(error):
                        from urllib.parse import urlsplit, parse_qsl
                        endpoint = ethereum_rpc_url()
                        parts = urlsplit(endpoint)
                        secrets = [endpoint, parts.path.rsplit("/", 1)[-1], *[v for _, v in parse_qsl(parts.query)]]
                        save_json(self.out / "provider_error.json", {"code": error.get("code"),
                            "message": _safe_error(error, [s for s in secrets if len(s) > 8]),
                            "query": chunk[int(response["id"]) - 1], "checked_at": _now()})
                        raise CollectionError("rug_pull_rpc_provider_error_code_" + str(error.get("code")))
                save_json(path, bundle)
            by_id = {row.get("id"): row for row in bundle["responses"]}
            if set(by_id) != set(range(1, len(chunk) + 1)):
                raise CollectionError("rug_pull_rpc_batch_ids_mismatch")
            for i, query in enumerate(chunk, 1):
                response = by_id[i]
                if response.get("error"):
                    if not self._contract_error(response["error"]):
                        raise CollectionError("rug_pull_rpc_cached_provider_error")
                    self.errors[_digest(query)] = "contract_execution_reverted"
                    continue
                if response.get("result") is None:
                    raise CollectionError("rug_pull_rpc_missing_result")
                normalized = {"jsonrpc": "2.0", "id": 1, "result": response["result"]}
                item = {"source": "ethereum_rpc", "request": query, "retrieved_at": bundle["retrieved_at"],
                        "checked_at": int(time.time()), "response": normalized,
                        "response_sha256": self.checksum(normalized)}
                atomic_bytes(self._path(query), (json.dumps(item, indent=2) + "\n").encode())
            if progress != "off":
                print(f"[rug_pull rpc] {min(start + size, len(pending))}/{len(pending)} calls; "
                      f"HTTP batches={self.batch_requests}", file=sys.stderr, flush=True)

    @staticmethod
    def _contract_error(error):
        message = str(error.get("message", "")).lower()
        return error.get("code") == 3 or "execution reverted" in message or "revert opcode" in message


def _call(entity, data, tag):
    return {"method": "eth_call", "params": [{"to": entity, "data": data}, tag]}


def _rpc_settings(settings, allow_network):
    return {**settings.get("rpc", {}), "allow_network": allow_network, "max_requests": 30000}


def _context(out, settings, allow_network):
    directory = out / "pools"
    previous = load_json(directory / "recipe.json") if (directory / "recipe.json").exists() else {}
    options = settings.get("pools", {})
    scope = options.get("scope", "weth" if previous.get("quote_token") == WETH else "all_v2")
    if scope not in {"weth", "all_v2"}:
        raise ValueError("unsupported_rug_pull_pool_scope")
    recipe = {"version": "tokenscout-uniswap-v2-weth-1" if scope == "weth" else "tokenscout-uniswap-v2-all-quotes-1",
              "factory": UNISWAP_V2_FACTORY, "quote_token": WETH if scope == "weth" else None,
              "cutoff": options.get("cutoff", previous.get("cutoff", DEFAULT_CUTOFF)),
              "cutoff_meaning": "retrospective_source_coverage_anchor_not_incident_or_label_time",
              "labels_manifest_sha256": sha256_file(out / "labels/manifest.json")}
    mode = settings.get("rpc", {}).get("verification_mode", previous.get("metadata_verification_mode",
        "factory_event_and_rpc" if not previous and scope == "all_v2" else None))
    if mode:
        if mode not in {"pair_getters", "factory_event_and_rpc"}:
            raise ValueError("unsupported_rug_pull_metadata_verification_mode")
        recipe["metadata_verification_mode"] = mode
    if type(recipe["cutoff"]) is not int or recipe["cutoff"] < 1:
        raise ValueError("invalid_rug_pull_cutoff")
    _freeze(directory / "recipe.json", recipe)
    rpc_settings = _rpc_settings(settings, allow_network)
    client = BatchSnapshotClient(directory / "rpc", rpc_settings)
    bounds_path = directory / "block.json"
    if bounds_path.exists():
        state = load_json(bounds_path)
    else:
        chain = EtherscanClient(directory / "blocks", {**settings.get("collection", {}), "allow_network": allow_network})
        block = chain.block_by_time(recipe["cutoff"], "before")
        chain_id = client.request("ethereum_rpc", {"method": "eth_chainId", "params": []})["response"]["result"]
        if integer(chain_id) != 1:
            raise CollectionError("ethereum_mainnet_only")
        header = client.request("ethereum_rpc", {"method": "eth_getBlockByNumber", "params": [hex(block), False]})
        state = header["response"]["result"]
        if integer(state.get("number")) != block or integer(state.get("timestamp")) is None or integer(state["timestamp"]) > recipe["cutoff"] or not state.get("hash"):
            raise CollectionError("cutoff_block_header_mismatch")
        _freeze(bounds_path, state)
    # Bind the saved header to its cached RPC evidence on every resume.
    if integer(client.request("ethereum_rpc", {"method": "eth_chainId", "params": []})["response"]["result"]) != 1:
        raise CollectionError("ethereum_mainnet_only")
    header = client.request("ethereum_rpc", {"method": "eth_getBlockByNumber", "params": [state["number"], False]})
    if header["response"]["result"] != state:
        raise CollectionError("rug_pull_frozen_block_mismatch")
    return recipe, state, client


def factory_pool_index(out, settings, state, allow_network, progress):
    """Only Factory PairCreated metadata, never pool trading or transfer histories."""
    directory = out / "pools/factory_index"
    if (directory / "manifest.json").exists():
        return _verified(directory / "manifest.json")
    options = {**settings.get("collection", {}), "allow_network": allow_network,
               "page_size": 1000, "max_pages": 10, "max_history_rows": 500000,
               "max_requests": 2000}
    last = [0.0]
    lock = threading.Lock()
    end = integer(state["number"])
    windows = [(low, min(low + 999999, end)) for low in range(0, end + 1, 1000000)]
    def fetch(bounds):
        client = EtherscanClient(directory, options)
        if progress != "off":
            def report(value):
                with lock:
                    if time.monotonic() - last[0] >= 15:
                        print(f"[rug_pull pool index] blocks={bounds[0]}..{bounds[1]} "
                              f"page={value.get('query', {}).get('page', '?')}", file=sys.stderr, flush=True)
                        last[0] = time.monotonic()
            client.on_progress = report
        return client.history("getLogs", UNISWAP_V2_FACTORY, *bounds, topic0=PAIR_TOPIC)
    # Independent metadata ranges share the existing persistent Etherscan quota.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, windows))
    logs = [row for rows, _ in results for row in rows]
    coverage = {"action": "getLogs", "topic0": PAIR_TOPIC, "address": UNISWAP_V2_FACTORY,
                "start_block": 0, "end_block": end, "row_count": len(logs),
                "segments": [segment for _, c in results for segment in c["segments"]],
                "request_ids": list(dict.fromkeys(i for _, c in results for i in c["request_ids"])),
                "gaps": [gap for _, c in results for gap in c["gaps"]],
                "complete": all(c["complete"] for _, c in results)}
    save_json(directory / "coverage.json", coverage)
    if not coverage.get("complete") or coverage.get("gaps"):
        reasons = "; ".join(str(gap.get("reason", "unknown")) for gap in coverage.get("gaps", []))
        raise CollectionError("rug_pull_factory_index_coverage_incomplete: " + reasons)
    pools = {}
    for raw in logs:
        if address(raw.get("address")) != UNISWAP_V2_FACTORY:
            raise CollectionError("rug_pull_factory_index_wrong_emitter")
        event = decode_v2_log(raw)
        if not event or event["relation"] != "pair_created":
            raise CollectionError("rug_pull_factory_index_wrong_event")
        row = {"pool": event["pool"], "token0": event["token0"], "token1": event["token1"],
               "factory": UNISWAP_V2_FACTORY, "pair_count": int(event["pair_count"]),
               "created_block": integer(raw.get("blockNumber")), "created_at": integer(raw.get("timeStamp")),
               "creation_tx": raw.get("transactionHash"), "evidence_ref": raw.get("raw_path")}
        if row["pool"] in pools and pools[row["pool"]] != row:
            raise CollectionError("rug_pull_conflicting_factory_pool")
        pools[row["pool"]] = row
    rows = sorted(pools.values(), key=lambda r: r["pair_count"])
    if rows and [r["pair_count"] for r in rows] != list(range(1, len(rows) + 1)):
        raise CollectionError("rug_pull_factory_pair_sequence_incomplete")
    write_records(directory / "pools.jsonl", rows)
    return _manifest(directory / "manifest.json", [directory / "pools.jsonl", directory / "coverage.json"],
                     factory=UNISWAP_V2_FACTORY, cutoff_block=integer(state["number"]), pool_count=len(rows))


def discover_all_quote_pools(out, settings, recipe, state, allow_network, progress):
    directory = out / "pools"
    factory_pool_index(out, settings, state, allow_network, progress)
    index = read_records(directory / "factory_index/pools.jsonl")
    cleaned = read_records(out / "labels/cleaned_labels.jsonl")
    source_addresses = {r["token_address"] for r in cleaned}
    matches = defaultdict(list)
    for pool in index:
        for key, other in (("token0", "token1"), ("token1", "token0")):
            if pool[key] in source_addresses:
                matches[pool[key]].append({**pool, "quote_token": pool[other]})
    selected = read_records(out / "labels/selected_labels.jsonl")
    targets, excluded, selected_matches = [], [], []
    for label in selected:
        candidates = matches.get(label["token_address"], [])
        if not candidates:
            excluded.append({**label, "reason": "no_canonical_v2_pair_at_cutoff"})
            continue
        def rank(pool):
            quote = pool["quote_token"]
            return (QUOTE_PRIORITY.index(quote) if quote in QUOTE_PRIORITY else len(QUOTE_PRIORITY),
                    pool["created_block"], pool["pool"])
        candidates = sorted(candidates, key=rank)
        pool = candidates[0]
        selected_matches.append({"sample_id": label["sample_id"], "token_address": label["token_address"],
                                 "selected_pool": pool["pool"], "pool_count": len(candidates),
                                 "pools": candidates})
        targets.append({"sample_id": label["sample_id"], "task_id": "rug_pull", "chain_id": 1,
                        "target": label["token_address"], "pools": [pool["pool"]], "quote_token": pool["quote_token"],
                        "cutoff": recipe["cutoff"], "cutoff_block": integer(state["number"]),
                        "end_block": integer(state["number"]), "pool_discovery_evidence_ref": pool["evidence_ref"]})
    write_records(directory / "candidate_targets.jsonl", targets)
    write_records(directory / "unmatched_labels.jsonl", excluded)
    write_records(directory / "token_pool_matches.jsonl", selected_matches)
    all_counts = Counter(str(r["label"]) for r in cleaned if r["token_address"] in matches)
    return _manifest(directory / "discovery_manifest.json", [directory / name for name in
        ("recipe.json", "block.json", "candidate_targets.jsonl", "unmatched_labels.jsonl", "token_pool_matches.jsonl",
         "factory_index/manifest.json")], selected_tokens=len(selected), matched_tokens=len(targets),
        unmatched_tokens=len(excluded), unmatched_reasons=dict(Counter(r["reason"] for r in excluded)),
        all_source_tokens_with_v2_pools=sum(all_counts.values()), all_source_matched_label_counts=dict(all_counts),
        selected_pool_policy="WETH, USDC, USDT, DAI priority then earliest canonical v2 pool; one pool per token",
        selected_quote_counts=dict(Counter(t["quote_token"] for t in targets)))


def discover_pools(out, settings, allow_network, progress):
    _verified(out / "labels/manifest.json")
    recipe, state, client = _context(out, settings, allow_network)
    directory = out / "pools"
    if (directory / "discovery_manifest.json").exists():
        return _verified(directory / "discovery_manifest.json")
    if recipe["quote_token"] is None:
        return discover_all_quote_pools(out, settings, recipe, state, allow_network, progress)
    labels = read_records(out / "labels/selected_labels.jsonl")
    tag = {"blockHash": state["hash"], "requireCanonical": True}
    queries = {r["token_address"]: _call(UNISWAP_V2_FACTORY,
               "0xe6a43905" + r["token_address"][2:].rjust(64, "0") + WETH[2:].rjust(64, "0"), tag)
               for r in labels if r["token_address"] != WETH}
    client.prefetch(queries.values(), progress)
    targets, excluded = [], []
    for label in labels:
        entity = label["token_address"]
        reason, pool = None, None
        if entity == WETH:
            reason = "quote_token_itself"
        else:
            query = queries[entity]
            if _digest(query) in client.errors:
                raise CollectionError("canonical_factory_getPair_reverted")
            bundle = client.request("ethereum_rpc", query)
            raw = bundle["response"]["result"]
            if not isinstance(raw, str) or len(raw) != 66 or int(raw[2:26], 16) != 0:
                raise CollectionError("invalid_factory_pair_address_abi")
            pool = address("0x" + raw[-40:])
            if pool == ZERO:
                reason = "no_canonical_weth_pair_at_cutoff"
        if reason:
            excluded.append({**label, "reason": reason})
        else:
            targets.append({"sample_id": label["sample_id"], "task_id": "rug_pull", "chain_id": 1,
                            "target": entity, "pools": [pool], "cutoff": recipe["cutoff"],
                            "cutoff_block": integer(state["number"]), "end_block": integer(state["number"]),
                            "pool_discovery_evidence_ref": bundle["evidence_ref"]})
    write_records(directory / "candidate_targets.jsonl", targets)
    write_records(directory / "unmatched_labels.jsonl", excluded)
    return _manifest(directory / "discovery_manifest.json", [directory / p for p in
        ("recipe.json", "block.json", "candidate_targets.jsonl", "unmatched_labels.jsonl")],
        selected_tokens=len(labels), matched_tokens=len(targets), unmatched_tokens=len(excluded),
        unmatched_reasons=dict(Counter(r["reason"] for r in excluded)))


def _verify_target_round(out, targets, client, state, allow_network, progress, mode="pair_getters"):
    directory = out / "pools"
    client.settings["allow_network"] = allow_network
    tag = {"blockHash": state["hash"], "requireCanonical": True}
    factory_facts = {}
    if mode == "factory_event_and_rpc":
        _verified(directory / "factory_index/manifest.json")
        factory_facts = {r["pool"]: r for r in read_records(directory / "factory_index/pools.jsonl")}
    queries = []
    for target in targets:
        queries.append(_call(target["target"], "0x313ce567", tag))
        if mode == "pair_getters":
            for selector in ("0x0dfe1681", "0xd21220a7", "0xc45a0155"):
                queries.append(_call(target["pools"][0], selector, tag))
        token0, token1 = sorted([target["target"], target.get("quote_token", WETH)])
        queries.append(_call(UNISWAP_V2_FACTORY,
            "0xe6a43905" + token0[2:].rjust(64, "0") + token1[2:].rjust(64, "0"), tag))
    client.prefetch(queries, progress)
    # Existing token verifier may only replay the prefetched single-call evidence.
    client.settings["allow_network"] = False
    verified, rejected = [], []
    for target in targets:
        token_query = _call(target["target"], "0x313ce567", tag)
        try:
            if _digest(token_query) in client.errors:
                raise ValueError("token_decimals_execution_reverted")
            if mode == "factory_event_and_rpc":
                pool = target["pools"][0]
                fact = factory_facts.get(pool, {})
                if (fact.get("factory") != UNISWAP_V2_FACTORY or target["target"] not in (fact.get("token0"), fact.get("token1"))
                        or not isinstance(fact.get("created_block"), int) or fact["created_block"] > target["cutoff_block"]):
                    raise CollectionError("canonical_factory_creation_identity_mismatch")
                query = _call(UNISWAP_V2_FACTORY, "0xe6a43905" + fact["token0"][2:].rjust(64, "0") + fact["token1"][2:].rjust(64, "0"), tag)
                if _digest(query) in client.errors:
                    raise CollectionError("canonical_factory_getPair_reverted")
                membership = client.request("ethereum_rpc", query)
                raw = membership["response"]["result"]
                if not isinstance(raw, str) or len(raw) != 66 or integer(raw) != int(pool, 16):
                    raise CollectionError("factory_pair_membership_mismatch")
                decimals = client.request("ethereum_rpc", token_query)
                raw_decimals = decimals["response"]["result"]
                if not isinstance(raw_decimals, str) or len(raw_decimals) != 66:
                    raise ValueError("invalid_decimals_abi")
                item = {**target, "cutoff_block_hash": state["hash"],
                    "token_metadata": {"decimals": integer(raw_decimals), "verified_at_block": target["cutoff_block"],
                                       "evidence_ref": decimals["evidence_ref"]},
                    "pool_metadata": [{"pool": pool, "token0": fact["token0"], "token1": fact["token1"],
                        "factory": UNISWAP_V2_FACTORY, "verified_at_block": target["cutoff_block"],
                        "evidence_ref": membership["evidence_ref"], "creation_evidence_ref": fact["evidence_ref"],
                        "verification_method": "canonical_factory_creation_and_cutoff_getPair"}]}
                token_scope(item)
                write_records(directory / "samples" / target["sample_id"] / "verified_targets.jsonl", [item])
                verified.append(item)
                continue
            facts = []
            for selector in ("0x0dfe1681", "0xd21220a7", "0xc45a0155"):
                query = _call(target["pools"][0], selector, tag)
                if _digest(query) in client.errors:
                    raise CollectionError("canonical_pool_getter_reverted")
                raw = client.request("ethereum_rpc", query)["response"]["result"]
                if not isinstance(raw, str) or len(raw) != 66 or int(raw[2:26], 16):
                    raise CollectionError("invalid_pair_address_abi")
                facts.append("0x" + raw[-40:])
            if (target["target"] not in facts[:2] or target.get("quote_token", WETH) not in facts[:2]
                    or facts[2] != UNISWAP_V2_FACTORY):
                raise CollectionError("canonical_pool_metadata_mismatch")
            sorted_query = _call(UNISWAP_V2_FACTORY, "0xe6a43905" + facts[0][2:].rjust(64, "0") + facts[1][2:].rjust(64, "0"), tag)
            if _digest(sorted_query) in client.errors or not client._path(sorted_query).exists():
                raise CollectionError("canonical_pool_token_order_or_factory_query_mismatch")
            sample_dir = directory / "samples" / target["sample_id"]
            result = verify_token_targets([target], sample_dir, client=client)
            verified.extend(read_records(result["output"]))
        except (ValueError, CollectionError) as error:
            # Only malformed/missing token decimals are a supported sample exclusion.
            if str(error) not in {"invalid_decimals_abi", "token_decimals_execution_reverted", "token_scope_requires_historical_decimals"}:
                raise
            rejected.append({"sample_id": target["sample_id"], "token_address": target["target"], "reason": str(error)})
    return verified, rejected


def verify_pools(out, settings, allow_network, progress):
    _verified(out / "pools/discovery_manifest.json")
    directory = out / "pools"
    recipe, state, client = _context(out, settings, allow_network)
    if (directory / "verification_manifest.json").exists():
        return _verified(directory / "verification_manifest.json")
    by_id = {r["sample_id"]: r for r in read_records(out / "labels/selected_labels.jsonl")}
    targets = read_records(directory / "candidate_targets.jsonl")
    label_recipe = load_json(out / "labels/recipe.json")
    mode = recipe.get("metadata_verification_mode", "pair_getters")
    verified, rejected = [], []
    if label_recipe.get("selection_stage") == "after_pool_verification":
        rank = lambda t: _digest([label_recipe["seed"], t["target"]])
        positives = sorted((t for t in targets if by_id[t["sample_id"]]["label"] == 1), key=rank)
        negatives = sorted((t for t in targets if by_id[t["sample_id"]]["label"] == 0), key=rank)
        quota = label_recipe["positive_count"] or len(positives)
        if label_recipe["negative_count"] is not None:
            negatives = negatives[:label_recipe["negative_count"]]
        _freeze(directory / "verification_plan.json", {"version": "eligible-source-cohort-1",
            "metadata_verification_mode": mode,
            "positive_count": quota, "negative_count": len(negatives),
            "ordered_positives": [t["sample_id"] for t in positives],
            "ordered_negatives": [t["sample_id"] for t in negatives],
            "discovery_manifest_sha256": sha256_file(directory / "discovery_manifest.json")})
        cursor, round_number = 0, 0
        while True:
            have = sum(by_id[t["sample_id"]]["label"] == 1 for t in verified)
            needed = quota - have
            if needed <= 0:
                break
            chosen = positives[cursor:cursor + needed]
            cursor += len(chosen)
            if round_number == 0:
                chosen += negatives
            if not chosen:
                raise ValueError("insufficient_metadata_verified_rug_pull_positives")
            round_number += 1
            round_dir = directory / "verification_rounds" / f"round-{round_number:04d}"
            _freeze(round_dir / "plan.json", {"sample_ids": [t["sample_id"] for t in chosen]})
            if (round_dir / "manifest.json").exists():
                _verified(round_dir / "manifest.json")
                good, bad = read_records(round_dir / "verified.jsonl"), read_records(round_dir / "rejected.jsonl")
            else:
                good, bad = _verify_target_round(out, chosen, client, state, allow_network, progress, mode)
                write_records(round_dir / "verified.jsonl", good)
                write_records(round_dir / "rejected.jsonl", bad)
                _manifest(round_dir / "manifest.json", [round_dir / "plan.json", round_dir / "verified.jsonl", round_dir / "rejected.jsonl"])
            verified.extend(good)
            rejected.extend(bad)
        if sum(by_id[t["sample_id"]]["label"] == 1 for t in verified) != quota:
            raise ValueError("rug_pull_eligible_positive_quota_not_met")
    else:
        verified, rejected = _verify_target_round(out, targets, client, state, allow_network, progress, mode)
    final_labels = [{**by_id[t["sample_id"]], "pool_address": t["pools"][0], "pool_addresses": t["pools"],
                     "cutoff": recipe["cutoff"], "pool_verified": True} for t in verified]
    write_records(directory / "verified_targets.jsonl", verified)
    write_records(directory / "verification_rejections.jsonl", rejected)
    write_records(out / "labels/verified_labels.jsonl", final_labels)
    _csv(out / "labels/verified_labels.csv", final_labels)
    return _manifest(directory / "verification_manifest.json", [directory / "verified_targets.jsonl",
        directory / "verification_rejections.jsonl", out / "labels/verified_labels.jsonl",
        out / "labels/verified_labels.csv"], verified_tokens=len(verified), rejected_tokens=len(rejected),
        verified_label_counts=dict(Counter(str(r["label"]) for r in final_labels)),
        eligible_selection_stage=label_recipe.get("selection_stage", "before_pool"),
        attempted_tokens=len(verified) + len(rejected), pool_candidate_tokens=len(targets))


def export_pool_matched_source(out):
    """All source labels with a canonical pool identity, independent of the pilot cap."""
    directory = out / "labels"
    manifest = directory / "pool_candidates_manifest.json"
    if manifest.exists():
        return _verified(manifest)
    _verified(out / "pools/factory_index/manifest.json")
    labels = read_records(directory / "cleaned_labels.jsonl")
    by_token = {r["token_address"]: r for r in labels}
    best, counts = {}, Counter()
    for pool in read_records(out / "pools/factory_index/pools.jsonl"):
        for key, other in (("token0", "token1"), ("token1", "token0")):
            token, quote = pool[key], pool[other]
            if token not in by_token:
                continue
            counts[token] += 1
            rank = (QUOTE_PRIORITY.index(quote) if quote in QUOTE_PRIORITY else len(QUOTE_PRIORITY),
                    pool["created_block"], pool["pool"])
            if token not in best or rank < best[token][0]:
                best[token] = (rank, {**pool, "quote_token": quote})
    cutoff = load_json(out / "pools/recipe.json")["cutoff"]
    rows = [{**by_token[token], "pool_address": pool["pool"], "pool_addresses": [pool["pool"]],
             "quote_token": pool["quote_token"], "factory": UNISWAP_V2_FACTORY, "dex": "uniswap_v2",
             "cutoff": cutoff, "discovered_pool_count": counts[token],
             "pool_identity_evidence_ref": pool["evidence_ref"], "pool_discovered": True,
             "token_metadata_verified": False} for token, (_, pool) in sorted(best.items())]
    write_records(directory / "pool_matched_candidates.jsonl", rows)
    _csv(directory / "pool_matched_candidates.csv", rows)
    return _manifest(manifest, [directory / "pool_matched_candidates.jsonl", directory / "pool_matched_candidates.csv"],
        counts=dict(Counter(str(r["label"]) for r in rows)), token_count=len(rows),
        source_labels_manifest_sha256=sha256_file(directory / "manifest.json"),
        factory_index_manifest_sha256=sha256_file(out / "pools/factory_index/manifest.json"),
        meaning="Canonical Factory pool identities for all matching source labels; token metadata not yet verified outside the selected cohort")


def quality_report(out):
    _verified(out / "sources/manifest.json")
    labels = _verified(out / "labels/manifest.json")
    discovery = _verified(out / "pools/discovery_manifest.json")
    verification = _verified(out / "pools/verification_manifest.json")
    by_id = {r["sample_id"]: r for r in read_records(out / "labels/selected_labels.jsonl")}
    matched_counts = Counter(str(by_id[r["sample_id"]]["label"])
                             for r in read_records(out / "pools/candidate_targets.jsonl"))
    unmatched_counts = Counter(str(r["label"]) for r in read_records(out / "pools/unmatched_labels.jsonl"))
    report = {"status": "labels_ready", "task_id": "rug_pull", "source": "tokenscout",
              "label_meaning": "source-defined rugpull versus truthworthy; not independently confirmed withdrawal incidents",
              "labels": labels["counts"], "pools": {k: v for k, v in discovery.items() if k != "artifacts"},
              "verification": {k: v for k, v in verification.items() if k != "artifacts"},
              "pool_scope": "Ethereum canonical Uniswap v2 all quote assets at the source coverage anchor"
                  if load_json(out / "pools/recipe.json")["quote_token"] is None else
                  "Ethereum canonical Uniswap v2 TOKEN/WETH at the source coverage anchor",
              "pool_recipe": load_json(out / "pools/recipe.json"),
              "unknown_source_times_preserved": True, "transaction_history_collected": False,
              "graphs_built": False, "training_started": False}
    report["pools"].update(matched_label_counts=dict(matched_counts), unmatched_label_counts=dict(unmatched_counts))
    report["cohort_policy"] = load_json(out / "labels/recipe.json")
    if (out / "pools/factory_index/manifest.json").exists():
        report["all_source_pool_candidates"] = export_pool_matched_source(out)
    final_targets = read_records(out / "pools/verified_targets.jsonl")
    rejected = read_records(out / "pools/verification_rejections.jsonl")
    quote_names = dict(zip(QUOTE_PRIORITY, ["WETH", "USDC", "USDT", "DAI"]))
    quote_counts = Counter(quote_names.get(t.get("quote_token", WETH), "其他资产") for t in final_targets)
    report["cohort"] = {"tokens": len(final_targets),
        "unique_tokens": len({t["target"] for t in final_targets}),
        "unique_pools": len({p for t in final_targets for p in t["pools"]}),
        "label_counts": verification["verified_label_counts"], "quote_asset_counts": dict(quote_counts)}
    report["metadata_rejections"] = {"reason_counts": dict(Counter(r["reason"] for r in rejected)),
        "label_counts": dict(Counter(str(by_id[r["sample_id"]]["label"]) for r in rejected))}
    save_json(out / "label_quality_summary.json", report)
    c, v = report["labels"], report["verification"]
    anchor = datetime.fromtimestamp(report["pool_recipe"]["cutoff"], timezone.utc).isoformat()
    selection = load_json(out / "labels/recipe.json")
    available = discovery.get("all_source_matched_label_counts", dict(matched_counts))
    text = ("# Rug Pull TokenScout 标签质量摘要\n\n"
            f"最终名单：**{v['verified_label_counts'].get('1', 0):,} 个正例、{v['verified_label_counts'].get('0', 0):,} 个负例，共 {v['verified_tokens']:,} 个 Token**。\n\n"
            "| 阶段 | 正例（rugpull） | 负例（truthworthy） |\n|---|---:|---:|\n"
            f"| 地址清理后 | {c['cleaned_label_counts'].get('1', 0):,} | {c['cleaned_label_counts'].get('0', 0):,} |\n"
            f"| 找到官方 v2 池归属 | {available.get('1', 0):,} | {available.get('0', 0):,} |\n"
            f"| 最终元数据验证通过并选定 | {v['verified_label_counts'].get('1', 0):,} | {v['verified_label_counts'].get('0', 0):,} |\n\n"
            f"原始标签 {c['raw_rows']:,} 条，成功映射 {c['mapped_rows']:,} 条，失败 {c['unmapped_rows']:,} 条；"
            f"同标签重复 {c['duplicate_rows']:,} 条，冲突地址 {c['conflicting_addresses']:,} 个。"
            f"Ponzi/Honeypot 等非本任务标签排除 {c['other_label_rows_excluded']:,} 条。\n\n"
            f"元数据验证排除 {v['rejected_tokens']:,} 个：{json.dumps(report['metadata_rejections']['reason_counts'], ensure_ascii=False)}。"
            f"最终对应 {report['cohort']['unique_pools']:,} 个不同池；另一侧资产：{json.dumps(dict(quote_counts), ensure_ascii=False)}。\n\n"
            "标签直接继承 TokenScout（rugpull=1、truthworthy=0），未逐笔独立确认恶意撤资。"
            f"池范围为官方 Uniswap v2 全部报价资产；历史验证锚点 {anchor}，不作为事件或标签时间。\n\n"
            "最终标签：labels/verified_labels.csv/jsonl；后续采集输入：pools/verified_targets.jsonl；"
            "排除明细：pools/verification_rejections.jsonl。\n\n"
            "**未采集交易历史，未构图，未训练。**\n")
    if selection.get("selection_stage") == "after_pool_verification":
        text += f"\n本次先匹配池并验证元数据，再保留 {selection['positive_count']} 个合格正例和全部合格负例；正例元数据失败时按固定顺序补足，排除记录保留。\n"
    if "all_source_matched_label_counts" in discovery:
        text += ("\n完整池归属：pools/token_pool_matches.jsonl；全量有池来源候选：labels/pool_matched_candidates.csv/jsonl。"
                 "名单之外的候选尚未进行 Token 精度等 RPC 元数据验证。\n"
                 "没有官方 v2 匹配不表示其他 DEX 没有池，尚未跨 DEX 确认。\n")
    atomic_bytes(out / "label_quality_summary.md", text.encode())
    return report


def prepare_rug_pull(out, *, stage="all", settings=None, allow_network=False, dry_run=False,
                     progress="auto", positive_count=None, negative_count=None, historical_cutoff=None,
                     graph_run="recent-v1", graph_limit=None, strict_collection=False):
    if stage == "prepare-training":
        if any(v is not None for v in (positive_count, negative_count, historical_cutoff, graph_limit)):
            raise ValueError("rug_pull_training_preparation_uses_frozen_graph_run")
        from .honeypot_graphs import graph_root
        from .rug_pull_training import prepare_training
        return prepare_training(graph_root(out, graph_run), dry_run=dry_run)
    if stage in {"plan", "collect", "build-graphs", "graphs"}:
        if positive_count is not None or negative_count is not None or historical_cutoff is not None:
            raise ValueError("rug_pull_collection_uses_frozen_verified_cohort_and_cutoff")
        from .rug_pull_graphs import run_graphs
        return run_graphs(out, stage=stage, settings=settings, graph_run=graph_run, limit=graph_limit,
            allow_network=allow_network, dry_run=dry_run, drop_failed=not strict_collection, progress=progress)
    settings = dict(settings or {})
    settings["selection"] = dict(settings.get("selection", {}))
    settings["pools"] = dict(settings.get("pools", {}))
    for key, value in (("positive_count", positive_count), ("negative_count", negative_count)):
        if value is not None:
            settings["selection"][key] = value
    if historical_cutoff is not None:
        from packages.labeling import _time
        settings["pools"]["cutoff"] = _time(historical_cutoff)
    aliases = {"addresses": "audit", "cohort": "audit", "label": "audit"}
    stage = aliases.get(stage, stage)
    stages = list(STAGES) if stage in {"all", "evidence"} else [stage]
    if any(s not in STAGES for s in stages):
        raise ValueError("unsupported_rug_pull_stage_training_requires_separate_workflow")
    if dry_run:
        return {"status": "planned", "stages": stages, "network_performed": False,
                "transaction_history_collected": False, "training_started": False,
                "output": str(Path(out).resolve())}
    out = Path(out)
    result = None
    for current in stages:
        if current == "sources":
            result = freeze_sources(out, settings, allow_network)
        elif current == "audit":
            result = audit_labels(out, settings)
        elif current == "discover":
            result = discover_pools(out, settings, allow_network, progress)
        elif current == "verify":
            result = verify_pools(out, settings, allow_network, progress)
        else:
            result = quality_report(out)
    return {"status": "labels_ready" if stages[-1] == "prepare" else "complete", "stage": stage,
            "result": result, "output": str(out.resolve()), "transaction_history_collected": False,
            "training_started": False}
