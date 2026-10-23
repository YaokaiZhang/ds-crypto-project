"""Explicit, replayable token metadata verification and Honeypot evidence capture."""
from __future__ import annotations

import hashlib
import json
import os
import time
import threading
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qsl
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import Any, Iterable

from .collection import CollectionError, EtherscanClient, _now, _safe_error
from .io import atomic_bytes, save_json, write_records
from .provider_access import ethereum_rpc_url
from .token import TOKEN_TASKS, UNISWAP_V2_FACTORY, token_scope
from .transactions import address, integer


class SnapshotClient:
    """Public request identities; successful immutable captures can be replayed."""
    def __init__(self, out: str | Path, settings: dict[str, Any] | None = None):
        self.out, self.settings = Path(out), dict(settings or {})
        self.transport = self.settings.get("transport")
        self.requests = 0
        self._last_request = 0.0
        self._request_lock = threading.Lock()
        self._cache_locks = {}

    def request(self, source: str, params: dict[str, Any]) -> dict[str, Any]:
        key = json.dumps([source, params], sort_keys=True)
        with self._request_lock:
            lock = self._cache_locks.setdefault(key, threading.Lock())
        with lock:
            return self._request(source, params)

    def _request(self, source, params):
        digest = hashlib.sha256(json.dumps({"source": source, "params": params}, sort_keys=True).encode()).hexdigest()
        if self.settings.get("cancel_event") is not None and self.settings["cancel_event"].is_set():
            raise InterruptedError("snapshot_request_cancelled")
        cache_root = self.out
        if (source == "ethereum_rpc" and self.settings.get("rpc_cache_dir")
                and not self.transport and not self.settings.get("fixtures")):
            cache_root = Path(self.settings["rpc_cache_dir"])
        path = cache_root / "raw_requests" / f"{digest}.json"
        if path.exists():
            bundle = json.loads(path.read_text())
            if (bundle.get("source") != source or bundle.get("request") != params
                    or bundle.get("response_sha256") != self.checksum(bundle.get("response"))):
                raise CollectionError("invalid_snapshot_cache")
            return {**bundle, "evidence_ref": str(path.resolve())}
        fixtures = self.settings.get("fixtures", {})
        if not self.transport and not fixtures and not self.settings.get("allow_network", False):
            raise CollectionError("network_disabled_use_allow_network_or_fixtures")
        if self.requests >= int(self.settings.get("max_requests", 10000)):
            raise CollectionError("request_budget_exhausted")
        secret = self.settings.get("rpc_url") or ethereum_rpc_url()
        api_key = os.environ.get("HONEYPOT_API_KEY", "")
        parts = urlsplit(secret)
        private = [secret, api_key, *[v for _, v in parse_qsl(parts.query)], parts.path.rsplit("/", 1)[-1]]
        private = [v for v in private if len(v) > 8]
        payload = None
        for attempt in range(int(self.settings.get("retries", 3)) + 1):
            try:
                # One shared start-rate/request budget across concurrent samples.
                with self._request_lock:
                    if self.requests >= int(self.settings.get("max_requests", 10000)):
                        raise CollectionError("request_budget_exhausted")
                    self.requests += 1
                    if not self.transport and not fixtures:
                        rate = min(3.0, max(.01, float(self.settings.get("rate_limit_rps", 1))))
                        remaining = 1 / rate - (time.monotonic() - self._last_request)
                        if remaining > 0:
                            time.sleep(remaining)
                        self._last_request = time.monotonic()
                if self.transport:
                    payload = self.transport(source, dict(params))
                elif fixtures:
                    key = digest if digest in fixtures else params.get("method", source)
                    if key not in fixtures:
                        raise CollectionError("missing_snapshot_fixture")
                    payload = fixtures[key]
                elif source == "ethereum_rpc":
                    endpoint = self.settings.get("rpc_url") or secret
                    if not endpoint:
                        raise CollectionError("missing_ethereum_rpc_url")
                    request = Request(endpoint, data=json.dumps({"jsonrpc": "2.0", "id": 1, **params}).encode(),
                                      headers={"Content-Type": "application/json"})
                    with urlopen(request, timeout=float(self.settings.get("timeout_seconds", 30))) as response:
                        payload = json.load(response)
                else:
                    headers = {"Accept": "application/json", "User-Agent": "chainrisk-research/0.1"}
                    if api_key:
                        headers["X-API-KEY"] = api_key
                    query = {key: value for key, value in params.items() if key != "sample_id"}
                    request = Request("https://api.honeypot.is/v2/IsHoneypot?" + urlencode(query), headers=headers)
                    with urlopen(request, timeout=float(self.settings.get("timeout_seconds", 30))) as response:
                        payload = json.load(response)
                if not isinstance(payload, dict):
                    raise CollectionError("invalid_or_failed_snapshot_response")
                if payload.get("error"):
                    raise CollectionError("invalid_or_failed_snapshot_response:" +
                                          _safe_error(payload["error"], private))
                if source == "ethereum_rpc" and payload.get("result") is None:
                    raise CollectionError("missing_rpc_result")
                break
            except HTTPError as exc:
                if exc.code in (401, 403, 429):
                    detail = _safe_error(exc.read(2048).decode("utf-8", errors="replace"), private)
                    save_json(self.out / "provider_error.json", {"source": source, "http_status": exc.code,
                              "checked_at": _now(), "content_type": exc.headers.get("Content-Type"),
                              "body_excerpt": detail})
                    raise CollectionError(f"HTTP Error {exc.code}: provider access/quota failure; see provider_error.json") from None
                if attempt == int(self.settings.get("retries", 3)):
                    raise CollectionError(_safe_error(exc, private)) from None
                if not self.transport and not fixtures:
                    time.sleep(min(4, .5 * 2 ** attempt))
            except (URLError, TimeoutError, OSError) as exc:
                if attempt == int(self.settings.get("retries", 3)):
                    raise CollectionError(_safe_error(exc, private)) from None
                if not self.transport and not fixtures:
                    time.sleep(min(4, .5 * 2 ** attempt))
        bundle = {"source": source, "request": params, "retrieved_at": _now(),
                  "checked_at": int(time.time()), "response": payload,
                  "response_sha256": self.checksum(payload)}
        atomic_bytes(path, (json.dumps(bundle, ensure_ascii=False, indent=2) + "\n").encode())
        return {**bundle, "evidence_ref": str(path.resolve())}

    @staticmethod
    def checksum(payload: Any) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def verify_token_targets(targets: Iterable[dict[str, Any]], out: str | Path,
                         settings: dict[str, Any] | None = None, dry_run: bool = False, *,
                         client: SnapshotClient | None = None) -> dict[str, Any]:
    """Verify supplied pools at cutoff using pair getters AND factory getPair.

    Requires historical eth_call support. Cutoff block can be supplied or resolved
    through Etherscan. No current-state fallback or all-chain discovery occurs.
    """
    targets = [dict(item) for item in targets]
    if not targets or len({item.get("sample_id") for item in targets}) != len(targets):
        raise ValueError("verification_requires_unique_samples")
    for item in targets:
        if (item.get("task_id") not in TOKEN_TASKS or item.get("chain_id", 1) != 1
                or not item.get("sample_id") or not address(item.get("target")) or integer(item.get("cutoff")) is None
                or not item.get("pools") or any(not address(pool) for pool in item["pools"])):
            raise ValueError("verification_requires_token_cutoff_and_selected_pools")
    if dry_run:
        return {"status": "planned", "target_count": len(targets), "network_performed": False}
    client = client or (settings or {}).get("_client") or SnapshotClient(out, settings)
    def rpc(method, params):
        observer = (settings or {}).get("on_progress")
        if observer:
            observer({"phase": "query", "query": {"action": method}})
        result = client.request("ethereum_rpc", {"method": method, "params": params})
        if observer:
            observer({"phase": "received", "query": {"action": method}})
        return result
    if integer(rpc("eth_chainId", [])["response"]["result"]) != 1:
        raise CollectionError("ethereum_mainnet_only")
    verified = []
    for item in targets:
        block = integer(item.get("cutoff_block", item.get("end_block")))
        if block is None:
            block = EtherscanClient(out, settings).block_by_time(int(item["cutoff"]), "before")
        header = rpc("eth_getBlockByNumber", [hex(block), False])
        state = header["response"]["result"]
        if (integer(state.get("number")) != block or integer(state.get("timestamp")) is None
                or integer(state["timestamp"]) > int(item["cutoff"]) or not state.get("hash")):
            raise CollectionError("cutoff_block_header_mismatch")
        tag = {"blockHash": state["hash"], "requireCanonical": True}
        root = address(item["target"])
        def call(entity, data):
            return rpc("eth_call", [{"to": entity, "data": data}, tag])
        decimals = call(root, "0x313ce567")
        raw_decimals = decimals["response"]["result"]
        if not isinstance(raw_decimals, str) or len(raw_decimals) != 66:
            raise CollectionError("invalid_decimals_abi")
        item.update(target=root, cutoff_block=block, end_block=block, cutoff_block_hash=state["hash"],
                    token_metadata={"decimals": integer(raw_decimals), "verified_at_block": block,
                                    "evidence_ref": decimals["evidence_ref"]}, pool_metadata=[])
        for original_pool in item["pools"]:
            pool = address(original_pool)
            facts = {}
            references = []
            for key, selector in (("token0", "0x0dfe1681"), ("token1", "0xd21220a7"), ("factory", "0xc45a0155")):
                bundle = call(pool, selector)
                raw = bundle["response"]["result"]
                if not isinstance(raw, str) or len(raw) != 66 or int(raw[2:26], 16) != 0:
                    raise CollectionError("invalid_pair_address_abi")
                facts[key] = address("0x" + raw[-40:])
                references.append(bundle["evidence_ref"])
            if facts["factory"] != UNISWAP_V2_FACTORY:
                raise CollectionError("unsupported_v2_factory")
            pair = call(facts["factory"], "0xe6a43905" + facts["token0"][2:].rjust(64, "0") + facts["token1"][2:].rjust(64, "0"))
            raw_pair = pair["response"]["result"]
            if not isinstance(raw_pair, str) or len(raw_pair) != 66 or integer(raw_pair) != int(pool, 16):
                raise CollectionError("factory_pair_membership_mismatch")
            item["pool_metadata"].append({**facts, "pool": pool, "verified_at_block": block,
                                           "evidence_ref": pair["evidence_ref"], "getter_refs": references})
        item["pools"] = sorted(address(pool) for pool in item["pools"])
        token_scope(item)
        verified.append(item)
    write_records(Path(out) / "verified_targets.jsonl", verified)
    return {"status": "verified", "targets": len(verified), "requests": client.requests,
            "output": str((Path(out) / "verified_targets.jsonl").resolve())}


def collect_honeypot_evidence(targets: Iterable[dict[str, Any]], out: str | Path,
                             settings: dict[str, Any] | None = None, dry_run: bool = False) -> dict[str, Any]:
    targets = list(targets)
    if not targets or len({item.get("sample_id") for item in targets}) != len(targets):
        raise ValueError("capture_requires_unique_samples")
    queries = []
    for item in targets:
        if item.get("task_id") != "honeypot" or item.get("chain_id", 1) != 1 or not address(item.get("target")):
            raise ValueError("honeypot_capture_requires_ethereum_token")
        for pool in item.get("pools", []):
            if not address(pool) or not item.get("sample_id"):
                raise ValueError("honeypot_capture_requires_sample_and_pool")
            queries.append({"sample_id": item["sample_id"], "address": address(item["target"]),
                            "chainID": 1, "pair": address(pool)})
        if not item.get("pools"):
            raise ValueError("honeypot_capture_requires_selected_pool")
    if dry_run:
        return {"status": "planned", "requests": len(queries), "network_performed": False}
    client = SnapshotClient(out, settings)
    records = [client.request("honeypot_is", query) for query in queries]
    write_records(Path(out) / "honeypot_snapshots.jsonl", records)
    detection_targets = [{"sample_id": record["request"]["sample_id"] + ":" + record["request"]["pair"][2:],
                          "task_id": "honeypot", "chain_id": 1, "target": record["request"]["address"],
                          "pools": [record["request"]["pair"]], "cutoff": record["checked_at"],
                          "source_snapshot": record["evidence_ref"]} for record in records]
    write_records(Path(out) / "detection_targets.jsonl", detection_targets)
    # Capture time is a candidate label cutoff, never the input target's arbitrary
    # historical cutoff. The API does not provide historical-block simulation.
    return {"status": "captured", "snapshots": len(records), "requires_admission_review": True,
            "output": str((Path(out) / "honeypot_snapshots.jsonl").resolve()),
            "targets_output": str((Path(out) / "detection_targets.jsonl").resolve())}
