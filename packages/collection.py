"""Resumable Etherscan V2 collection, including an entirely offline fixture mode."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .data import SOURCE_KINDS, normalize_records
from .transactions import address, decode_v2_log, integer
from .token import TOKEN_TASKS, TOKEN_SCOPE_VERSION, token_scope
from .progress import progress_bar
from .io import atomic_bytes
from .provider_access import etherscan_key, SerialRequestBudget, REQUESTS_PER_SECOND, REQUESTS_PER_24H


class CollectionError(RuntimeError):
    pass


def transient_network_error(error):
    """Transport outages are retryable provider failures, never bad samples."""
    text = str(error).lower()
    return any(marker in text for marker in (
        "nodename nor servname", "name resolution", "name or service not known", "getaddrinfo failed",
        "network is unreachable", "network is down", "no route to host", "connection reset",
        "connection aborted", "connection refused", "remote end closed connection", "broken pipe",
        "timed out", "timeout", "temporary failure in name", "temporarily unavailable",
        "http error 502", "http error 503", "http error 504", "provider_request_cancelled",
        "sample_request_cancelled", "snapshot_request_cancelled", "honeypot_stage_cancelled"))


def _save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


def _jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temp.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _safe_error(exc: Any, secrets: Iterable[str]) -> str:
    value = str(exc)
    for secret in secrets:
        if secret:
            value = value.replace(secret, "REDACTED")
    return value[:500]


class EtherscanClient:
    """Raw request cache keyed by public parameters, never by credentials.

    Only successful responses enter the reusable cache. Request-level success
    is distinct from complete address/range coverage.
    """

    def __init__(self, out: str | Path, settings: dict[str, Any] | None = None,
                 transport: Callable[[dict[str, Any]], Any] | None = None):
        self.out = Path(out)
        self.settings = dict(settings or {})
        self.endpoint = _safe_endpoint(self.settings.get("endpoint", "https://api.etherscan.io/v2/api"))
        self.key = self.settings.get("api_key") or etherscan_key(self.settings.get("api_key_env", "ETHERSCAN_API_KEY"))
        self.transport = transport or self.settings.get("transport")
        shared = self.settings.get("shared_cache_dir")
        fixture_mode = self.settings.get("fixtures") or self.settings.get("fixture_dir") or self.transport
        # Fixture/synthetic responses must never populate a real shared cache.
        self.shared_cache = Path(shared) / hashlib.sha256(self.endpoint.encode()).hexdigest() if shared and not fixture_mode else None
        self.page_size = min(1000, max(1, int(self.settings.get("page_size", 1000))))
        self.max_pages = max(1, int(self.settings.get("max_pages", 10)))
        self.rate = min(REQUESTS_PER_SECOND, max(0.01, float(self.settings.get("rate_limit_rps", REQUESTS_PER_SECOND))))
        self.budget = self.settings.get("request_budget") or SerialRequestBudget(rate=self.rate)
        self.retries = max(0, int(self.settings.get("retries", 3)))
        self.timeout = float(self.settings.get("timeout_seconds", 30))
        self.max_requests = max(1, int(self.settings.get("max_requests", 10000)))
        self.max_history_rows = max(1, int(self.settings.get("max_history_rows", 100000)))
        self.request_count = 0
        self.cached_count = 0
        self.http_attempts = 0
        self.http_seconds = 0.0
        self.on_progress = None
        self.active_query = {}

    def report_progress(self, phase):
        if self.on_progress:
            self.on_progress({"phase": phase, "query": self.active_query,
                              "requests": self.request_count, "cache_hits": self.cached_count,
                              "http_attempts": self.http_attempts, "http_seconds": self.http_seconds,
                              "throttle_wait_seconds": self.budget.wait_seconds})

    def _fixture(self, query: dict[str, Any]) -> Any:
        fixtures = self.settings.get("fixtures", {})
        key = self.request_id(query)
        action = query["action"]
        if isinstance(fixtures, dict) and (key in fixtures or action in fixtures):
            value = fixtures.get(key, fixtures.get(action))
            if isinstance(value, list):
                size = integer(query.get("offset"), default=self.page_size)
                page = integer(query.get("page"), default=1)
                value = {"status": "1", "message": "OK", "result": value[(page - 1) * size:page * size]}
            return value
        directory = self.settings.get("fixture_dir")
        if directory:
            path = Path(directory)
            names = [f"{key}.json", f"{action}_{query.get('address', '')}_{query.get('startblock', query.get('fromBlock', ''))}_{query.get('endblock', query.get('toBlock', ''))}_{query.get('page', 1)}.json",
                     f"{action}_{query.get('page', 1)}.json", f"{action}.json"]
            for name in names:
                candidate = path / name
                if candidate.is_file():
                    payload = json.loads(candidate.read_text())
                    return payload.get("response", payload)
            raise CollectionError(f"missing_fixture:{action}")
        raise CollectionError("missing_fixture")

    @staticmethod
    def request_id(query: dict[str, Any]) -> str:
        public = {key: value for key, value in query.items() if key != "apikey"}
        return hashlib.sha256(json.dumps(public, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def request(self, module: str, action: str, **params: Any) -> dict[str, Any]:
        query = {"chainid": 1, "module": module, "action": action, **params}
        self.active_query = {name: value for name, value in query.items() if name != "apikey"}
        if integer(query["chainid"]) != 1:
            raise CollectionError("ethereum_mainnet_only")
        key = self.request_id(query)
        if self.settings.get("logical_query_progress"):
            self.report_progress("query")
        path = (self.shared_cache or self.out) / "raw_requests" / f"{key}.json"
        if path.exists():
            bundle = json.loads(path.read_text())
            if bundle.get("request") != query or bundle.get("complete") is not True:
                raise CollectionError("invalid_cached_request")
            if self.shared_cache and bundle.get("endpoint") != self.endpoint:
                raise CollectionError("cached_provider_mismatch")
            self._validate_response(bundle.get("response"), action)
            digest = hashlib.sha256(json.dumps(bundle["response"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if bundle.get("response_sha256") != digest:
                raise CollectionError("cached_response_checksum_mismatch")
            bundle["raw_path"] = str(path.resolve())
            self.cached_count += 1
            self.report_progress("cache")
            return bundle
        if self.request_count >= self.max_requests:
            raise CollectionError("request_budget_exhausted")
        has_fixtures = bool(self.settings.get("fixtures") or self.settings.get("fixture_dir") or self.transport)
        if not has_fixtures and not self.settings.get("allow_network", False):
            raise CollectionError("network_disabled_use_allow_network_or_fixtures")
        if not has_fixtures and not self.key:
            raise CollectionError("missing_etherscan_api_key")
        last_error = "request_failed"
        for attempt in range(self.retries + 1):
            try:
                if self.request_count >= self.max_requests:
                    raise CollectionError("request_budget_exhausted")
                self.request_count += 1
                self.report_progress("request")
                if self.transport:
                    payload = self.transport(dict(query))
                elif has_fixtures:
                    payload = self._fixture(query)
                else:
                    url = self.endpoint + "?" + urlencode({**query, "apikey": self.key})
                    request = Request(url, headers={"Accept": "application/json", "User-Agent": "chainrisk-scam/0.1"})
                    with self.budget.request_slot():
                        cancelled = self.settings.get("cancel_event")
                        if cancelled is not None and cancelled.is_set():
                            raise CollectionError("sample_request_cancelled")
                        self.http_attempts += 1
                        started = time.perf_counter()
                        try:
                            with urlopen(request, timeout=self.timeout) as response:
                                byte_limit = self.settings.get("max_response_bytes")
                                if byte_limit:
                                    body = response.read(int(byte_limit) + 1)
                                    if len(body) > int(byte_limit):
                                        raise CollectionError("response_byte_budget_exhausted")
                                    payload = json.loads(body)
                                else:
                                    payload = json.load(response)
                        finally:
                            self.http_seconds += time.perf_counter() - started
                self._validate_response(payload, action)
                bundle = {"request_id": key, "request": query, "endpoint": self.endpoint,
                          "source_kind": SOURCE_KINDS.get(action, action), "retrieved_at": _now(),
                          "response": payload, "complete": True}
                bundle["response_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                if self.shared_cache:
                    published = atomic_bytes(path, json.dumps(bundle, sort_keys=True).encode(), immutable=True)
                    # Validate and use the winner if another process published
                    # the same historical request while this one was in flight.
                    winner = self.request(module, action, **params)
                    if published:
                        self.cached_count -= 1
                    return winner
                _save(path, bundle)
                bundle["raw_path"] = str(path.resolve())
                self.report_progress("received")
                return bundle
            except (CollectionError, HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                last_error = _safe_error(exc, [self.key])
                self.report_progress("error")
                retryable = transient_network_error(last_error) or any(marker in last_error.lower() for marker in (
                    "rate limit", "timeout", "timed out", "temporarily", "429", "502", "503", "504", "max rate"))
                if not retryable or attempt == self.retries:
                    break
                if not has_fixtures:
                    time.sleep(min(8, 0.5 * 2 ** attempt))
        raise CollectionError(last_error)

    @staticmethod
    def _validate_response(payload: Any, action: str) -> None:
        if not isinstance(payload, dict):
            raise CollectionError("unexpected_api_payload")
        if payload.get("error"):
            raise CollectionError(str(payload["error"]))
        result = payload.get("result")
        if str(payload.get("status")) == "0":
            message = (str(payload.get("message", "")) + " " + str(result)).lower()
            empty = "no transactions found" in message or "no records found" in message or "no logs found" in message
            if not empty or result not in ([], "", "No transactions found", "No records found", "No logs found"):
                raise CollectionError(str(result or payload.get("message") or "etherscan_error"))
        if action in ("txlist", "txlistinternal", "tokentx", "getLogs") and not isinstance(result, list):
            if str(payload.get("status")) != "0":
                raise CollectionError("history_result_not_array")
        elif action in ("txlist", "txlistinternal", "tokentx", "getLogs") and any(not isinstance(row, dict) for row in result):
            raise CollectionError("history_row_not_object")
        elif action in ("eth_getTransactionReceipt", "eth_getBlockByNumber") and not isinstance(result, dict):
            raise CollectionError("missing_receipt_or_block")
        elif action == "getblocknobytime" and integer(result) is None:
            raise CollectionError("missing_block_for_timestamp")

    def block_by_time(self, timestamp: int, closest: str = "before") -> int:
        bundle = self.request("block", "getblocknobytime", timestamp=int(timestamp), closest=closest)
        return int(bundle["response"]["result"])

    def receipt(self, tx_hash: str) -> dict[str, Any]:
        return self.request("proxy", "eth_getTransactionReceipt", txhash=tx_hash)

    def block(self, block_number: int) -> dict[str, Any]:
        return self.request("proxy", "eth_getBlockByNumber", tag=hex(block_number), boolean="false")

    def history(self, action: str, entity: str, start_block: int, end_block: int,
                **extra: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Paginate bounded intervals; split exhausted windows, never skip blocks."""
        if action not in ("txlist", "txlistinternal", "tokentx", "getLogs"):
            raise ValueError("unsupported_history_action")
        ids: list[str] = []
        rows: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        segments = []

        def fetch(low: int, high: int, depth: int = 0) -> None:
            if len(rows) >= self.max_history_rows:
                gaps.append({"start_block": low, "end_block": high, "reason": "history_row_budget_exhausted"})
                return
            local = []
            page_digests = set()
            reason = None
            for page in range(1, self.max_pages + 1):
                params = {"address": entity, "page": page, "offset": self.page_size, **extra}
                params.update({"fromBlock": low, "toBlock": high} if action == "getLogs" else
                              {"startblock": low, "endblock": high, "sort": "asc"})
                try:
                    bundle = self.request("logs" if action == "getLogs" else "account", action, **params)
                    ids.append(bundle["request_id"])
                    page_rows = bundle["response"].get("result") or []
                    if not isinstance(page_rows, list):
                        page_rows = []  # validated, recognized empty response only
                    if len(page_rows) > self.page_size:
                        raise CollectionError("api_page_size_exceeded")
                    if len(rows) + len(local) + len(page_rows) > self.max_history_rows:
                        raise CollectionError("history_row_budget_exhausted")
                    if any((block := integer(raw.get("blockNumber", raw.get("block_number")))) is None
                           or not low <= block <= high for raw in page_rows):
                        raise CollectionError("history_row_outside_requested_block_range")
                    digest = hashlib.sha256(json.dumps(page_rows, sort_keys=True).encode()).hexdigest()
                    if page_rows and digest in page_digests:
                        reason = "pagination_did_not_advance"
                        break
                    page_digests.add(digest)
                    local.extend({**raw, "source_kind": SOURCE_KINDS[action], "source_row": source_row,
                                  "request_id": bundle["request_id"], "raw_path": bundle["raw_path"],
                                  "retrieved_at": bundle["retrieved_at"]} for source_row, raw in enumerate(page_rows))
                    if len(page_rows) < self.page_size:
                        rows.extend(local)
                        segments.append({"start_block": low, "end_block": high, "pages": page, "complete": True})
                        return
                except CollectionError as exc:
                    reason = str(exc)
                    break
            reason = reason or "page_limit_reached"
            # Ascending account histories have a proven complete prefix before
            # the final block of a full page window. Keep that prefix, then
            # reread the boundary block (which may span pages). Binary splitting
            # the original interval discards and downloads that prefix repeatedly.
            if reason == "page_limit_reached" and action != "getLogs" and local:
                blocks = [integer(row.get("blockNumber", row.get("block_number"))) for row in local]
                boundary = blocks[-1]
                if boundary > low and all(a <= b for a, b in zip(blocks, blocks[1:])):
                    rows.extend(row for row, block in zip(local, blocks) if block < boundary)
                    segments.append({"start_block": low, "end_block": boundary - 1,
                                     "pages": self.max_pages, "complete": True})
                    pending.append((boundary, high, depth))
                    return
            can_split = low < high and depth < 32 and (reason in ("page_limit_reached", "pagination_did_not_advance") or "timeout" in reason.lower())
            if can_split:
                middle = (low + high) // 2
                pending.append((middle + 1, high, depth + 1))
                pending.append((low, middle, depth + 1))
            else:
                rows.extend(local)
                gaps.append({"start_block": low, "end_block": high, "reason": reason})

        if start_block > end_block:
            raise ValueError("inverted_block_range")
        pending = [(start_block, end_block, 0)]
        while pending:
            fetch(*pending.pop())
        return rows, {"action": action, "address": entity, "start_block": start_block, "end_block": end_block,
                      "request_ids": list(dict.fromkeys(ids)), "segments": segments, "gaps": gaps,
                      "complete": not gaps, "row_count": len(rows)}


def collect_dataset(targets: Iterable[dict[str, Any]], out: str | Path,
                    settings: dict[str, Any] | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Collect frozen targets and write audited events plus target coverage.

    Explicit target.cutoff is mandatory. Optional start_block/end_block bypass
    timestamp-to-block lookup, but event timestamps are still cutoff filtered.
    """
    settings = dict(settings or {})
    settings = {**settings, **settings.get("etherscan", {})}
    max_raw_rows = int(settings.get("max_raw_rows", 500000))
    if max_raw_rows < 1:
        raise ValueError("raw_row_budget_must_be_positive")
    graph_settings = settings.get("graph", {})
    hops = int(graph_settings.get("hops", settings.get("hops", 2)))
    fanouts = tuple(graph_settings.get("fanouts", settings.get("fanouts", (32, 16))))
    max_nodes = int(graph_settings.get("max_nodes", settings.get("max_nodes", 512)))
    seed = int(graph_settings.get("seed", settings.get("seed", 20261008)))
    window_days = int(graph_settings.get("window_days", settings.get("window_days", settings.get("observation_days", 30))))
    if window_days < 1:
        raise ValueError("observation_window_must_be_positive")
    if hops < 1 or len(fanouts) < hops or min(fanouts) < 1 or max_nodes < 1:
        raise ValueError("invalid_collection_neighborhood_budget")
    targets = [dict(item) for item in targets]
    samples = set()
    for target in targets:
        sample = target.get("sample_id")
        if not sample or sample in samples:
            raise ValueError("missing_or_duplicate_sample_id")
        samples.add(sample)
        if address(target.get("target")) is None or integer(target.get("cutoff")) is None:
            raise ValueError("target_requires_address_and_explicit_unix_cutoff")
        if integer(target.get("chain_id"), default=1) != 1:
            raise ValueError("ethereum_mainnet_only")
        if int(target["cutoff"]) < 0:
            raise ValueError("cutoff_must_be_nonnegative")
    public_settings = {key: value for key, value in settings.items()
                       if key not in ("api_key", "transport", "fixtures", "etherscan")}
    if "endpoint" in public_settings:
        public_settings["endpoint"] = _safe_endpoint(public_settings["endpoint"])
    manifest = {"version": "scam-collection-0.1", "chain_id": 1, "created_at": _now(),
                "target_count": len(targets), "settings": public_settings, "complete": False, "dry_run": dry_run}
    if dry_run:
        manifest["planned_targets"] = targets
        return manifest
    client = EtherscanClient(out, settings)
    raw_rows: list[dict[str, Any]] = []
    retained_source_rows = set()
    coverages = []
    eligible_targets = []
    roots = progress_bar(targets, mode=settings.get("progress", "auto"),
                         desc="Etherscan root graphs", unit="root")
    collection_started = time.perf_counter()
    last_progress = 0.0
    active_root = None

    def report_progress(state):
        nonlocal last_progress
        now = time.perf_counter()
        if now - last_progress < 1 and state["phase"] not in {"histories_complete", "complete", "incomplete"}:
            return
        last_progress = now
        query = state["query"]
        elapsed = now - collection_started
        report = {**state, "updated_at": _now(), "roots_completed": len(coverages), "roots_total": len(targets),
                  "active_root": active_root, "raw_rows_retained": len(raw_rows), "elapsed_seconds": elapsed,
                  "mean_http_seconds": state["http_seconds"] / max(1, state["http_attempts"]),
                  "effective_http_rps": state["http_attempts"] / max(0.001, elapsed)}
        _save(Path(out) / "progress.json", report)
        roots.set_postfix(req=state["http_attempts"], cache=state["cache_hits"],
                          api_s=round(report["mean_http_seconds"], 2), wait_s=round(state["throttle_wait_seconds"], 1),
                          addr=str(query.get("address", ""))[:10], action=query.get("action", ""),
                          page=query.get("page", "-"), refresh=True)

    client.on_progress = report_progress
    for target in roots:
        active_root = target["target"]
        cutoff = int(target["cutoff"])
        start_time = int(target.get("observation_start", cutoff - window_days * 86400))
        if start_time >= cutoff:
            raise ValueError("observation_start_must_precede_cutoff")
        details = []
        failure = None
        sampling_truncated = False
        frontier_scopes = []
        sampled_nodes = {target["target"].lower()}
        neighborhood_complete = False
        scope = None
        start_block = None
        try:
            if target.get("task_id") in TOKEN_TASKS:
                scope = token_scope(target)
            start_block = integer(target.get("start_block"))
            end_block = integer(target.get("end_block"))
            if start_block is None:
                start_block = client.block_by_time(start_time, "after")
            if end_block is None:
                end_block = client.block_by_time(cutoff, "before")
            if scope and end_block != scope["cutoff_block"]:
                raise ValueError("collection_cutoff_block_differs_from_verified_scope")
            entities = [target["target"].lower()]
            actions = list(settings.get("actions", ["txlist", "txlistinternal"]))
            token_task = target.get("task_id") in ("honeypot", "rug_pull")
            if token_task:
                actions = list(settings.get("token_actions", ["getLogs", "txlist", "txlistinternal"]))
                if not {"getLogs", "txlist", "txlistinternal"}.issubset(actions):
                    raise ValueError("token_collection_requires_logs_external_internal")
                entities += [address(value) for value in target.get("pools", []) if address(value)]
                entities += [address(value) for value in target.get("factories", []) if address(value)]
            from .graph import select_neighbor_addresses
            frontier = sorted(set(entities))
            history_depths = 1 if token_task else hops
            for depth in range(history_depths):
                next_frontier = set()
                for entity in frontier:
                    entity_rows = []
                    for action in actions:
                        rows, source_coverage = client.history(action, entity, start_block, end_block)
                        new_rows = [row for row in rows if (row["request_id"], row["source_row"]) not in retained_source_rows]
                        if len(raw_rows) + len(new_rows) > max_raw_rows:
                            raise CollectionError("raw_row_budget_exhausted")
                        entity_rows.extend(rows)
                        raw_rows.extend(new_rows)
                        retained_source_rows.update((row["request_id"], row["source_row"]) for row in new_rows)
                        details.append({**source_coverage, "hop": depth, "frontier_address": entity})
                        if action != "tokentx":
                            continue
                        # Indexed token history sometimes omits logIndex; use receipts.
                        missing_rows = [row for row in rows if integer(row.get("logIndex")) is None]
                        missing = {row.get("hash"): row for row in missing_rows}
                        # Keep token history metadata: normalization joins it to
                        # receipt logs for decimals and provenance, then suppresses
                        # its missing-index event copy.
                        for tx_hash, token_row in missing.items():
                            bundle = client.receipt(tx_hash)
                            receipt = bundle["response"]["result"]
                            raw_rows.append({"source_kind": "receipt", "request_id": bundle["request_id"],
                                             "raw_path": bundle["raw_path"], "retrieved_at": bundle["retrieved_at"],
                                             "timestamp": integer(token_row.get("timeStamp")), "response": {"result": receipt}})
                    if token_task:
                        frontier_scopes.append({"hop": depth, "address": entity, "history_requested": True,
                                                "scope": "token_or_selected_pool_emitter_logs"})
                        continue
                    neighbors = set()
                    for raw in entity_rows:
                        stamp = integer(raw.get("timeStamp", raw.get("timestamp")))
                        if stamp is None or not start_time < stamp <= cutoff:
                            continue
                        src, dst = address(raw.get("from")), address(raw.get("to")) or address(raw.get("contractAddress"))
                        if "topics" in raw:
                            try:
                                decoded = decode_v2_log(raw)
                                if decoded:
                                    src, dst = decoded.get("src"), decoded.get("dst")
                            except ValueError:
                                continue
                        if entity == src and dst and dst != entity:
                            neighbors.add(dst)
                        if entity == dst and src and src != entity:
                            neighbors.add(src)
                    selected = select_neighbor_addresses(target["target"].lower(), entity, neighbors, int(fanouts[depth]), seed)
                    sampling_truncated |= len(neighbors) > len(selected)
                    admitted_neighbors = []
                    for neighbor in selected:
                        if neighbor not in sampled_nodes:
                            if len(sampled_nodes) >= max_nodes:
                                sampling_truncated = True
                                continue
                            sampled_nodes.add(neighbor)
                            next_frontier.add(neighbor)
                        admitted_neighbors.append(neighbor)
                    frontier_scopes.append({"hop": depth, "address": entity, "history_requested": True,
                                            "neighbor_count": len(neighbors), "selected_neighbors": admitted_neighbors,
                                            "truncated": len(admitted_neighbors) < len(neighbors),
                                            "scope": "sampled_frontier_address_history"})
                frontier = sorted(next_frontier)
                if not frontier:
                    break
            neighborhood_complete = not token_task and bool(details) and all(item["complete"] for item in details)
            if not details:
                failure = "no_event_sources_requested"
        except (CollectionError, ValueError, TypeError) as exc:
            failure = _safe_error(exc, [client.key])
        coverage = {"sample_id": target["sample_id"], "target": target["target"].lower(),
                    "cutoff": cutoff, "observation_start": start_time, "sources": details,
                    "start_timestamp": start_time, "end_timestamp": cutoff,
                    "complete": failure is None and bool(details) and all(item["complete"] for item in details),
                    "failure": failure, "neighborhood_history_complete": neighborhood_complete and failure is None,
                    "neighborhood_scope": "token_and_selected_pool_logs" if target.get("task_id") in ("honeypot", "rug_pull") else "sampled_frontier",
                    "sampling_truncated": sampling_truncated, "frontier_scopes": frontier_scopes,
                    "hops": hops, "fanouts": list(fanouts[:hops]), "seed": seed,
                    "max_nodes": max_nodes, "sampled_node_count": len(sampled_nodes),
                    "boundary_node_statistic_scope": "sampled_observed_subgraph"}
        if target.get("task_id") in TOKEN_TASKS:
            coverage.update(scope_version=TOKEN_SCOPE_VERSION, scope_sha256=scope["sha256"] if scope else None,
                            required_emitters=sorted({target["target"].lower(),
                                *(pool for value in target.get("pools", []) if (pool := address(value)))}),
                            start_block=start_block, end_block=target.get("cutoff_block", target.get("end_block")),
                            boundary_node_statistic_scope="selected_token_pool_emitters")
        coverages.append(coverage)
        eligible_targets.append({**target, "coverage": coverage})
        client.report_progress("root_complete")
    client.report_progress("histories_complete")
    # Etherscan logs supply timestamp; hydrate any receipt/RPC-style logs through block headers.
    for row in raw_rows:
        if integer(row.get("timeStamp", row.get("timestamp"))) is None and row.get("blockNumber"):
            try:
                bundle = client.block(int(integer(row["blockNumber"])))
                row["timestamp"] = integer(bundle["response"]["result"]["timestamp"])
                row.setdefault("blockHash", bundle["response"]["result"].get("hash"))
            except (CollectionError, ValueError, TypeError):
                pass  # strict normalizer records the missing timestamp
    known_pools = {pool: "pool" for target in targets for value in target.get("pools", [])
                   if (pool := address(value)) is not None}
    events, audit = normalize_records(raw_rows, known_entities=known_pools)
    bounded_events = [event for event in events if any(item["observation_start"] < event["timestamp"] <= item["cutoff"] for item in coverages)]
    if not audit["complete"]:
        for item in coverages:
            item["complete"] = False
            item["normalization_failure"] = True
    out = Path(out)
    _jsonl(out / "events.jsonl", bounded_events)
    _jsonl(out / "coverage.jsonl", coverages)
    _jsonl(out / "targets_with_coverage.jsonl", eligible_targets)
    _save(out / "normalization_audit.json", audit)
    manifest.update(complete=all(item["complete"] for item in coverages) and audit["complete"],
                    provider_policy={"rate_limit_rps": client.rate, "rolling_24h_limit": REQUESTS_PER_24H,
                                     "quota_scope": "one_serial_collector_on_this_project", "quota_wait": "automatic"},
                    request_count=client.request_count, cached_request_count=client.cached_count,
                    event_count=len(bounded_events), coverage=coverages,
                    paths={"events": str((out / "events.jsonl").resolve()),
                           "coverage": str((out / "coverage.jsonl").resolve()),
                           "targets": str((out / "targets_with_coverage.jsonl").resolve()),
                           "raw": str(((client.shared_cache or out) / "raw_requests").resolve())})
    _save(out / "manifest.json", manifest)
    client.report_progress("complete" if manifest["complete"] else "incomplete")
    roots.close()
    return manifest
