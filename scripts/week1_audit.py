#!/usr/bin/env python3
"""Collect and audit the legacy Week 1 Ethereum token feasibility pilot.

The implementation intentionally uses only the Python standard library.  It
archives every HTTP response and request description before normalizing data,
so a failed source or incomplete cursor is visible in the audit output.

This collector preserves the earlier first-10-swaps/no-activity outcome for
historical transport evidence. It is not the primary 7-day volume-label
pipeline; use ``scripts/graph_free_pilot.py`` for the current label contract.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


UTC = timezone.utc
MAX_RESPONSE_ITEMS = 1000
EVENT_NAMES = ("swap", "mint", "burn")
RAW_BUNDLE_MAX_RECORDS = 10000
RAW_BUNDLE_PREFIX = "responses-"


class RequestFailure(RuntimeError):
    """A source request failed after the bounded retry policy."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


SENSITIVE_QUERY_KEYS = frozenset(
    {"api_key", "apikey", "auth", "key", "password", "secret", "token", "access_token"}
)


@dataclass(frozen=True)
class ResolvedRpcUrl:
    """Keep the authenticated URL in memory and expose only its safe display form."""

    authenticated_url: str
    redacted_url: str
    source: str


def load_env_file(path: Path) -> dict[str, str]:
    """Read the small KEY=VALUE subset needed by the collector without a dependency."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def redact_url(url: str, *, secrets: Iterable[str] = (), redact_path: bool = False) -> str:
    """Remove URL credentials before a URL is persisted or included in a report."""
    if not url:
        return url
    redacted = url
    for secret in sorted({secret for secret in secrets if secret}, key=len, reverse=True):
        redacted = redacted.replace(secret, "REDACTED")
    try:
        parsed = urlsplit(redacted)
    except ValueError:
        return redacted
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in SENSITIVE_QUERY_KEYS],
        doseq=True,
    )
    path = "/REDACTED" if redact_path and parsed.path not in {"", "/"} else parsed.path
    return urlunsplit((parsed.scheme, netloc, path, query, ""))


def _environment_value(name: str, dotenv: Mapping[str, str], environ: Mapping[str, str]) -> str | None:
    if name in environ and environ[name].strip():
        return environ[name].strip()
    value = dotenv.get(name)
    return value.strip() if value and value.strip() else None


def _endpoint_with_key(endpoint: str, api_key: str | None) -> str:
    if not api_key or api_key in endpoint:
        return endpoint
    for placeholder in ("${API_KEY}", "{API_KEY}", "<API_KEY>"):
        if placeholder in endpoint:
            return endpoint.replace(placeholder, api_key)
    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("ENDPOINT must be an absolute HTTP(S) URL")
    path = f"{parsed.path.rstrip('/')}/{quote(api_key, safe='')}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def resolve_archive_rpc(
    dotenv_path: Path | None = None,
    *,
    fallback_url: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ResolvedRpcUrl:
    """Resolve an archive RPC from env, `.env`, or the public config fallback.

    `ETHEREUM_ARCHIVE_RPC_URL` is the preferred complete URL override. Otherwise
    `ENDPOINT` may already contain `API_KEY`, contain an API_KEY placeholder, or
    be a base URL to which `API_KEY` is appended as one path segment.
    """
    process_env = os.environ if environ is None else environ
    dotenv = load_env_file(dotenv_path) if dotenv_path else {}
    override = _environment_value("ETHEREUM_ARCHIVE_RPC_URL", dotenv, process_env)
    api_key = _environment_value("API_KEY", dotenv, process_env)
    if override:
        authenticated_url = override
        source = "ETHEREUM_ARCHIVE_RPC_URL"
    else:
        endpoint = _environment_value("ENDPOINT", dotenv, process_env)
        if endpoint:
            authenticated_url = _endpoint_with_key(endpoint, api_key)
            source = "ENDPOINT/API_KEY"
        elif fallback_url:
            authenticated_url = fallback_url
            source = "config fallback"
        else:
            raise ValueError("no archive RPC configured; set ETHEREUM_ARCHIVE_RPC_URL or ENDPOINT")
    parsed = urlsplit(authenticated_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("archive RPC must be an absolute HTTP(S) URL")
    redacted_url = redact_url(
        authenticated_url,
        secrets=(api_key,) if api_key else (),
        redact_path=source == "ETHEREUM_ARCHIVE_RPC_URL" and not api_key,
    )
    return ResolvedRpcUrl(
        authenticated_url=authenticated_url,
        redacted_url=redacted_url,
        source=source,
    )


def reporting_config(
    config: dict[str, Any], *, rpc_url: str | None = None, rpc_source: str | None = None
) -> dict[str, Any]:
    """Copy config while ensuring persisted URL fields contain no credentials."""
    copied = json.loads(json_dump(config))
    source = copied.get("source", {})
    for key, value in list(source.items()):
        if not isinstance(value, str) or not key.endswith("_url"):
            continue
        source[key] = rpc_url if rpc_url and key in {"rpc_url", "activity_rpc_url"} else redact_url(value)
    if rpc_source:
        source["archive_rpc_source"] = rpc_source
    return copied


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_address(value: str | None) -> str | None:
    if not value:
        return None
    value = value.lower()
    return value if value.startswith("0x") else f"0x{value}"


def address_topic(value: str) -> str:
    return "0x" + ("0" * 24) + normalize_address(value)[2:]


def word_values(data: str | None) -> list[str]:
    if not data:
        return []
    data = data[2:] if data.startswith("0x") else data
    return [data[i : i + 64] for i in range(0, len(data), 64) if len(data[i : i + 64]) == 64]


def address_from_topic(value: str | None) -> str | None:
    if not value:
        return None
    value = value[2:] if value.startswith("0x") else value
    if len(value) < 40:
        return None
    return "0x" + value[-40:].lower()


def as_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    raise ValueError(f"cannot convert to int: {value!r}")


def is_rpc_range_error(error: Any) -> bool:
    if not isinstance(error, dict):
        return False
    error_text = json_dump(error).lower()
    return error.get("code") in {-32600, -32602} and (
        "more than 20000" in error_text
        or "block range" in error_text
        or "free tier" in error_text
        or "up to 10 block" in error_text
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json_dump(row) + "\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json_dump(row) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class RawArchive:
    """Store raw responses in gzip JSONL bundles and a durable manifest.

    ``raw_path`` plus ``raw_line`` identifies a record in a bundle. Older
    manifests that point to one JSON file per request remain readable.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.raw_dir = root / "raw"
        self.manifest_path = root / "manifests" / "request_log.jsonl"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        existing_rows = read_jsonl(self.manifest_path)
        self.sequence = len(existing_rows)
        self.bundle_index = 1
        self.bundle_line = 0
        for row in existing_rows:
            raw_path = str(row.get("raw_path") or "")
            if not raw_path.endswith(".jsonl.gz"):
                continue
            name = Path(raw_path).name
            match = re.fullmatch(rf"{re.escape(RAW_BUNDLE_PREFIX)}(\d+)\.jsonl\.gz", name)
            if match:
                index = int(match.group(1))
                if index > self.bundle_index:
                    self.bundle_index = index
                    self.bundle_line = int(row.get("raw_line") or 0)
                elif index == self.bundle_index:
                    self.bundle_line = max(self.bundle_line, int(row.get("raw_line") or 0))

    def _next_bundle_record(self) -> tuple[Path, int]:
        if self.bundle_line >= RAW_BUNDLE_MAX_RECORDS:
            self.bundle_index += 1
            self.bundle_line = 0
        self.bundle_line += 1
        path = self.raw_dir / f"{RAW_BUNDLE_PREFIX}{self.bundle_index:06d}.jsonl.gz"
        return path, self.bundle_line

    def record(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        request_body: Any,
        status: int | None,
        headers: dict[str, str],
        response_body: Any,
        error: str | None,
        attempt: int,
    ) -> str:
        url = redact_url(url)
        request_material = json_dump(
            {"method": method, "url": url, "params": params or {}, "request_body": request_body}
        ).encode("utf-8")
        request_id = sha256_bytes(request_material)
        self.sequence += 1
        response_id = sha256_bytes(
            request_material + f"|attempt={attempt}|sequence={self.sequence}".encode("utf-8")
        )
        raw_path, raw_line = self._next_bundle_record()
        raw_payload = {
            "request_id": request_id,
            "response_id": response_id,
            "request": {
                "method": method,
                "url": url,
                "params": params or {},
                "body": request_body,
            },
            "response": {
                "retrieved_at": utc_now(),
                "status": status,
                "headers": headers,
                "body": response_body,
                "body_sha256": sha256_bytes(json_dump(response_body).encode("utf-8")),
                "error": error,
            },
        }
        with gzip.open(raw_path, "at", encoding="utf-8") as handle:
            handle.write(json_dump(raw_payload) + "\n")
        append_jsonl(
            self.manifest_path,
            {
                "request_id": request_id,
                "response_id": response_id,
                "retrieved_at": utc_now(),
                "method": method,
                "url": url,
                "params": params or {},
                "status": status,
                "attempt": attempt,
                "raw_path": str(raw_path.relative_to(self.root)),
                "raw_line": raw_line,
                "raw_format": "jsonl.gz",
                "error": error,
                "incomplete": error is not None or status != 200,
            },
        )
        return request_id


class HttpClient:
    def __init__(
        self,
        archive: RawArchive,
        *,
        user_agent: str,
        interval: float,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self.archive = archive
        self.user_agent = user_agent
        self.interval = interval
        self.timeout = timeout
        self.max_retries = max_retries
        self.last_request = 0.0

    def _wait_interval(self) -> None:
        delay = self.interval - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()

    @staticmethod
    def _decode(raw: bytes) -> Any:
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        archive_url: str | None = None,
    ) -> tuple[Any, str]:
        query = urlencode(params or {}, doseq=True)
        full_url = f"{url}?{query}" if query else url
        persisted_url = redact_url(archive_url or url)
        body_bytes = None if body is None else json_dump(body).encode("utf-8")
        headers = {"accept": "application/json", "user-agent": self.user_agent}
        if body_bytes is not None:
            headers["content-type"] = "application/json"

        for attempt in range(1, self.max_retries + 2):
            self._wait_interval()
            request = Request(full_url, data=body_bytes, headers=headers, method=method)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    parsed = self._decode(raw)
                    request_id = self.archive.record(
                        method=method,
                        url=persisted_url,
                        params=params,
                        request_body=body,
                        status=response.status,
                        headers=dict(response.headers.items()),
                        response_body=parsed,
                        error=None,
                        attempt=attempt,
                    )
                    return parsed, request_id
            except HTTPError as exc:
                raw = exc.read()
                parsed = self._decode(raw)
                headers_out = dict(exc.headers.items()) if exc.headers else {}
                error = f"HTTP {exc.code}"
                self.archive.record(
                    method=method,
                    url=persisted_url,
                    params=params,
                    request_body=body,
                    status=exc.code,
                    headers=headers_out,
                    response_body=parsed,
                    error=error,
                    attempt=attempt,
                )
                if exc.code == 429:
                    retry_after = headers_out.get("Retry-After") or headers_out.get("retry-after")
                    try:
                        retry_seconds = float(retry_after) if retry_after else 0.0
                    except ValueError:
                        retry_seconds = 0.0
                    if retry_seconds > 15 or attempt > self.max_retries:
                        raise RequestFailure(f"{error}; retry_after={retry_after or 'unknown'}") from exc
                    time.sleep(max(retry_seconds, min(2**attempt, 8)))
                    continue
                if exc.code >= 500 and attempt <= self.max_retries:
                    time.sleep(min(2**attempt, 8))
                    continue
                raise RequestFailure(error) from exc
            except (URLError, TimeoutError, OSError) as exc:
                error = f"{type(exc).__name__}: {exc}"
                error = error.replace(full_url, persisted_url).replace(url, persisted_url)
                self.archive.record(
                    method=method,
                    url=persisted_url,
                    params=params,
                    request_body=body,
                    status=None,
                    headers={},
                    response_body=None,
                    error=error,
                    attempt=attempt,
                )
                if attempt <= self.max_retries:
                    time.sleep(min(2**attempt, 8))
                    continue
                raise RequestFailure(error) from exc
        raise RequestFailure("unreachable request state")


class RestClient:
    def __init__(self, http: HttpClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    def get(self, path: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        payload, request_id = self.http.request("GET", f"{self.base_url}/{path.lstrip('/')}", params=params)
        if not isinstance(payload, dict):
            raise RequestFailure(f"expected JSON object from REST endpoint, got {type(payload).__name__}")
        if payload.get("errors") or payload.get("message") == "Invalid parameter(s)":
            raise RequestFailure(f"REST source rejected request: {json_dump(payload)[:500]}")
        return payload, request_id


class RpcClient:
    def __init__(self, http: HttpClient, url: str, *, archive_url: str | None = None) -> None:
        self.http = http
        self.url = url
        self.archive_url = redact_url(archive_url or url)

    def batch(self, calls: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        payload, request_id = self.http.request("POST", self.url, body=calls, archive_url=self.archive_url)
        if not isinstance(payload, list):
            raise RequestFailure(f"expected JSON-RPC batch response, got {type(payload).__name__}")
        return payload, request_id

    def call(self, method: str, params: list[Any]) -> tuple[dict[str, Any], str]:
        responses, request_id = self.batch(
            [{"jsonrpc": "2.0", "id": 1, "method": method, "params": params}]
        )
        if not responses:
            raise RequestFailure("empty JSON-RPC response")
        return responses[0], request_id


def protocol_by_name(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {protocol["name"]: protocol for protocol in config["protocols"]}


def parse_factory_item(protocol: dict[str, Any], item: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    topics = item.get("topics") or []
    if not topics or topics[0].lower() != protocol["creation_topic"].lower():
        return None
    token0 = address_from_topic(topics[1] if len(topics) > 1 else None)
    token1 = address_from_topic(topics[2] if len(topics) > 2 else None)
    words = word_values(item.get("data"))
    pool_index = protocol["pool_address_data_word"]
    if not token0 or not token1 or len(words) <= pool_index:
        return None
    pool = address_from_topic(words[pool_index])
    if not pool:
        return None
    return {
        "protocol": protocol["name"],
        "factory": normalize_address(protocol["factory"]),
        "pool_address": pool,
        "token0": token0,
        "token1": token1,
        "block_number": as_int(item["block_number"]),
        "block_hash": item.get("block_hash"),
        "block_timestamp": item.get("block_timestamp"),
        "transaction_hash": item.get("transaction_hash"),
        "log_index": as_int(item.get("index", 0)),
        "topics": topics,
        "data": item.get("data"),
        "creation_topic": topics[0],
        "source_request_id": request_id,
        "source": "blockscout_rest",
    }


def parse_factory_rpc(protocol: dict[str, Any], item: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    topics = item.get("topics") or []
    if not topics or topics[0].lower() != protocol["creation_topic"].lower():
        return None
    token0 = address_from_topic(topics[1] if len(topics) > 1 else None)
    token1 = address_from_topic(topics[2] if len(topics) > 2 else None)
    words = word_values(item.get("data"))
    pool_index = protocol["pool_address_data_word"]
    if not token0 or not token1 or len(words) <= pool_index:
        return None
    pool = address_from_topic(words[pool_index])
    if not pool:
        return None
    return {
        "protocol": protocol["name"],
        "factory": normalize_address(protocol["factory"]),
        "pool_address": pool,
        "token0": token0,
        "token1": token1,
        "block_number": as_int(item["blockNumber"]),
        "block_hash": item.get("blockHash"),
        "block_timestamp": None,
        "transaction_hash": item.get("transactionHash"),
        "log_index": as_int(item.get("logIndex", 0)),
        "topics": topics,
        "data": item.get("data"),
        "creation_topic": topics[0],
        "source_request_id": request_id,
        "source": "blockscout_rpc",
    }


def event_key(row: dict[str, Any]) -> str:
    return f"{row.get('transaction_hash')}:{row.get('log_index')}"


def collect_factory_windows(
    config: dict[str, Any],
    rpc: RpcClient,
    output: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []
    for protocol in config["protocols"]:
        for window in config["sample_windows"]:
            window_events: dict[str, dict[str, Any]] = {}
            ranges: list[dict[str, Any]] = []

            def collect_range(from_block: int, to_block: int, depth: int = 0) -> None:
                request_body = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_getLogs",
                    "params": [
                        {
                            "address": normalize_address(protocol["factory"]),
                            "fromBlock": hex(from_block),
                            "toBlock": hex(to_block),
                            "topics": [protocol["creation_topic"]],
                        }
                    ],
                }
                try:
                    responses, request_id = rpc.batch([request_body])
                except RequestFailure as exc:
                    ranges.append(
                        {
                            "from_block": from_block,
                            "to_block": to_block,
                            "depth": depth,
                            "request_id": None,
                            "count": None,
                            "complete": False,
                            "failure": str(exc),
                        }
                    )
                    return
                response = responses[0] if responses else {}
                if response.get("error"):
                    ranges.append(
                        {
                            "from_block": from_block,
                            "to_block": to_block,
                            "depth": depth,
                            "request_id": request_id,
                            "count": None,
                            "complete": False,
                            "failure": json_dump(response["error"]),
                        }
                    )
                    return
                logs = response.get("result") or []
                capped = len(logs) >= MAX_RESPONSE_ITEMS
                ranges.append(
                    {
                        "from_block": from_block,
                        "to_block": to_block,
                        "depth": depth,
                        "request_id": request_id,
                        "count": len(logs),
                        "complete": not capped,
                        "failure": None if not capped else "response_cap_requires_bisection",
                    }
                )
                if capped and from_block < to_block and depth < 24:
                    midpoint = (from_block + to_block) // 2
                    collect_range(from_block, midpoint, depth + 1)
                    collect_range(midpoint + 1, to_block, depth + 1)
                    return
                if capped:
                    ranges[-1]["failure"] = "response_cap_at_minimum_range"
                for item in logs:
                    parsed = parse_factory_rpc(protocol, item, request_id)
                    if parsed:
                        window_events[event_key(parsed)] = parsed | {"sampling_period": window["period"]}

            collect_range(window["start_block"], window["end_block"])
            events.update(window_events)
            coverage.append(
                {
                    "protocol": protocol["name"],
                    "period": window["period"],
                    "start_block": window["start_block"],
                    "end_block": window["end_block"],
                    "ranges": ranges,
                    "request_ids": [row["request_id"] for row in ranges if row["request_id"]],
                    "complete": all(row["complete"] for row in ranges) and bool(ranges),
                    "failure": next((row["failure"] for row in ranges if row["failure"]), None),
                }
            )
    result = sorted(events.values(), key=lambda row: (row["block_number"], row["log_index"], row["protocol"]))
    write_jsonl(output / "factory_events.jsonl", result)
    write_jsonl(output / "manifests" / "factory_coverage.jsonl", coverage)
    return result, coverage


def collect_factory_windows_rest(
    config: dict[str, Any],
    rest: RestClient,
    output: Path,
    *,
    max_pages: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect factory events through REST keyset pagination.

    This fallback is intentionally conservative: a page limit or source error
    leaves the window incomplete, so affected downstream entities remain
    censored rather than being treated as a complete factory history.
    """
    events: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []
    for protocol in config["protocols"]:
        for window in config["sample_windows"]:
            params: dict[str, Any] = {
                "block_number": window["end_block"],
                "index": 0,
                "items_count": 5,
            }
            page_count = 0
            request_ids: list[str] = []
            complete = False
            failure: str | None = None
            observed_min: int | None = None
            observed_max: int | None = None
            while page_count < max_pages:
                try:
                    payload, request_id = rest.get(
                        f"addresses/{normalize_address(protocol['factory'])}/logs", params
                    )
                except RequestFailure as exc:
                    failure = str(exc)
                    break
                request_ids.append(request_id)
                page_count += 1
                items = payload.get("items") or []
                blocks = [as_int(item["block_number"]) for item in items if item.get("block_number") is not None]
                if blocks:
                    observed_min = min(blocks) if observed_min is None else min(observed_min, min(blocks))
                    observed_max = max(blocks) if observed_max is None else max(observed_max, max(blocks))
                for item in items:
                    try:
                        block_number = as_int(item["block_number"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not (window["start_block"] <= block_number <= window["end_block"]):
                        continue
                    parsed = parse_factory_item(protocol, item, request_id)
                    if parsed:
                        events[event_key(parsed)] = parsed | {"sampling_period": window["period"]}
                if not items:
                    complete = True
                    break
                if observed_min is not None and observed_min < window["start_block"]:
                    complete = True
                    break
                next_params = payload.get("next_page_params")
                if not next_params:
                    complete = True
                    break
                params = next_params
            if not complete and failure is None:
                failure = f"page_limit_reached:{max_pages}"
            coverage.append(
                {
                    "protocol": protocol["name"],
                    "period": window["period"],
                    "start_block": window["start_block"],
                    "end_block": window["end_block"],
                    "pages": page_count,
                    "request_ids": request_ids,
                    "observed_min_block": observed_min,
                    "observed_max_block": observed_max,
                    "complete": complete,
                    "failure": failure,
                    "source": "blockscout_rest",
                }
            )
    result = sorted(events.values(), key=lambda row: (row["block_number"], row["log_index"], row["protocol"]))
    write_jsonl(output / "factory_events.jsonl", result)
    write_jsonl(output / "manifests" / "factory_coverage.jsonl", coverage)
    return result, coverage


def candidate_rows(factory_events: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    excluded = {normalize_address(value) for value in config["sampling"]["exclude_addresses"]}
    periods = {window["period"] for window in config["sample_windows"]}
    candidates: dict[str, dict[str, Any]] = {}
    for event in factory_events:
        for token_field, other_field in (("token0", "token1"), ("token1", "token0")):
            token = normalize_address(event[token_field])
            if token in excluded:
                continue
            current = candidates.setdefault(
                token,
                {
                    "token_address": token,
                    "observed_pools": {},
                    "protocols": set(),
                    "periods": set(),
                    "first_block": event["block_number"],
                    "first_timestamp": event.get("block_timestamp"),
                    "counterparty_addresses": set(),
                },
            )
            current["observed_pools"][event["pool_address"]] = {
                "pool_address": event["pool_address"],
                "protocol": event["protocol"],
                "token0": event["token0"],
                "token1": event["token1"],
                "creation_block": event["block_number"],
                "creation_timestamp": event.get("block_timestamp"),
                "creation_transaction_hash": event.get("transaction_hash"),
            }
            current["protocols"].add(event["protocol"])
            current["periods"].add(event.get("sampling_period"))
            current["counterparty_addresses"].add(normalize_address(event[other_field]))
            if event["block_number"] < current["first_block"]:
                current["first_block"] = event["block_number"]
                current["first_timestamp"] = event.get("block_timestamp")
    rows: list[dict[str, Any]] = []
    for current in candidates.values():
        pool_count = len(current["observed_pools"])
        if pool_count == 1:
            stratum = "1"
        elif pool_count <= 4:
            stratum = "2-4"
        else:
            stratum = "5+"
        period = min((value for value in current["periods"] if value in periods), default=None)
        rows.append(
            {
                "token_address": current["token_address"],
                "launch_period": period,
                "first_observed_block": current["first_block"],
                "first_observed_timestamp": current["first_timestamp"],
                "observed_pool_count": pool_count,
                "pool_count_stratum": stratum,
                "observed_protocols": sorted(current["protocols"]),
                "observed_pools": sorted(current["observed_pools"].values(), key=lambda row: row["pool_address"]),
                "counterparty_count": len(current["counterparty_addresses"]),
                "sampling_label_inspected": False,
            }
        )
    return sorted(rows, key=lambda row: (row["launch_period"] or "", row["token_address"]))


def select_candidates(frame: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    """Select deterministically by launch period and observed pool stratum."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in frame:
        key = (row["launch_period"] or "unknown", row["pool_count_stratum"])
        buckets[key].append(row)
    for rows in buckets.values():
        rows.sort(key=lambda row: hashlib.sha256(row["token_address"].encode()).hexdigest())
    periods = sorted({key[0] for key in buckets})
    selected: list[dict[str, Any]] = []
    period_quota = {period: target // len(periods) for period in periods}
    for period in periods[: target % len(periods)]:
        period_quota[period] += 1
    for period in periods:
        period_rows: list[dict[str, Any]] = []
        for stratum in ("1", "2-4", "5+"):
            period_rows.extend(buckets.get((period, stratum), []))
        period_rows.sort(key=lambda row: hashlib.sha256((period + row["token_address"]).encode()).hexdigest())
        selected.extend(period_rows[: period_quota[period]])
    if len(selected) < target:
        selected_addresses = {row["token_address"] for row in selected}
        remaining = [row for row in frame if row["token_address"] not in selected_addresses]
        remaining.sort(key=lambda row: hashlib.sha256(row["token_address"].encode()).hexdigest())
        selected.extend(remaining[: target - len(selected)])
    for rank, row in enumerate(selected[:target], start=1):
        row["sampling_rank"] = rank
        row["sampling_label_inspected"] = False
    return selected[:target]


def collect_exact_pool_scope(
    config: dict[str, Any],
    selected: list[dict[str, Any]],
    rpc: RpcClient,
    output: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    token_addresses = sorted({row["token_address"] for row in selected})
    calls: list[dict[str, Any]] = []
    metadata: list[tuple[dict[str, Any], int]] = []
    for protocol in config["protocols"]:
        token_topics = [address_topic(address) for address in token_addresses]
        for indexed_position in (1, 2):
            topics: list[Any] = [protocol["creation_topic"]]
            topics.extend([token_topics] if indexed_position == 1 else [None, token_topics])
            calls.append(
                {
                    "jsonrpc": "2.0",
                    "id": len(calls) + 1,
                    "method": "eth_getLogs",
                    "params": [
                        {
                            "address": normalize_address(protocol["factory"]),
                            "fromBlock": "0x0",
                            "toBlock": "latest",
                            "topics": topics,
                        }
                    ],
                }
            )
            metadata.append((protocol, indexed_position))
    pools_by_token: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reasons: dict[str, str] = {}
    try:
        latest_response, latest_request_id = rpc.call("eth_blockNumber", [])
        if latest_response.get("error") or not latest_response.get("result"):
            raise RequestFailure(f"eth_blockNumber failed: {json_dump(latest_response)}")
        latest_block = as_int(latest_response["result"])
    except RequestFailure as exc:
        reason = f"rpc_pool_scope_request_failed:{exc}"
        for row in selected:
            reasons[row["token_address"]] = reason
        write_json(output / "manifests" / "pool_scope_rpc_failure.json", {"error": str(exc)})
        return pools_by_token, reasons

    range_manifest: list[dict[str, Any]] = []
    protocol_map = protocol_by_name(config)

    def collect_range(
        protocol: dict[str, Any],
        indexed_position: int,
        topics: list[Any],
        from_block: int,
        to_block: int,
        depth: int = 0,
    ) -> None:
        call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getLogs",
            "params": [
                {
                    "address": normalize_address(protocol["factory"]),
                    "fromBlock": hex(from_block),
                    "toBlock": hex(to_block),
                    "topics": topics,
                }
            ],
        }
        try:
            responses, request_id = rpc.batch([call])
        except RequestFailure as exc:
            reason = f"rpc_pool_scope_request_failed:{exc}"
            for row in selected:
                reasons[row["token_address"]] = reason
            range_manifest.append(
                {
                    "protocol": protocol["name"],
                    "indexed_position": indexed_position,
                    "from_block": from_block,
                    "to_block": to_block,
                    "depth": depth,
                    "request_id": None,
                    "count": None,
                    "complete": False,
                    "failure": reason,
                }
            )
            return
        response = responses[0] if responses else {}
        if response.get("error"):
            reason = f"rpc_pool_scope_error:{response['error']}"
            for row in selected:
                reasons[row["token_address"]] = reason
            range_manifest.append(
                {
                    "protocol": protocol["name"],
                    "indexed_position": indexed_position,
                    "from_block": from_block,
                    "to_block": to_block,
                    "depth": depth,
                    "request_id": request_id,
                    "count": None,
                    "complete": False,
                    "failure": reason,
                }
            )
            return
        logs = response.get("result") or []
        capped = len(logs) >= MAX_RESPONSE_ITEMS
        range_manifest.append(
            {
                "protocol": protocol["name"],
                "indexed_position": indexed_position,
                "from_block": from_block,
                "to_block": to_block,
                "depth": depth,
                "request_id": request_id,
                "count": len(logs),
                "complete": not capped,
                "failure": None if not capped else "response_cap_requires_bisection",
            }
        )
        if capped and from_block < to_block and depth < 24:
            midpoint = (from_block + to_block) // 2
            collect_range(protocol, indexed_position, topics, from_block, midpoint, depth + 1)
            collect_range(protocol, indexed_position, topics, midpoint + 1, to_block, depth + 1)
            return
        if capped:
            for row in selected:
                reasons[row["token_address"]] = "rpc_pool_scope_response_cap_at_minimum_range"
        for item in logs:
            parsed = parse_factory_rpc(protocol_map[protocol["name"]], item, request_id)
            if not parsed:
                continue
            for token in (parsed["token0"], parsed["token1"]):
                if token in token_addresses:
                    pools_by_token[token].append(parsed)

    for protocol, indexed_position in metadata:
        token_topics = [address_topic(address) for address in token_addresses]
        topics: list[Any] = [protocol["creation_topic"]]
        topics.extend([token_topics] if indexed_position == 1 else [None, token_topics])
        collect_range(protocol, indexed_position, topics, 0, latest_block)
    write_json(
        output / "manifests" / "pool_scope_rpc_response.json",
        {"latest_block": latest_block, "calls": calls, "ranges": range_manifest},
    )
    for token in token_addresses:
        deduped = {event_key(row): row for row in pools_by_token[token]}
        pools_by_token[token] = sorted(deduped.values(), key=lambda row: (row["block_number"], row["log_index"]))
        if not pools_by_token[token] and token not in reasons:
            reasons[token] = "rpc_pool_scope_returned_no_matching_pool"
    return pools_by_token, reasons


def enrich_entities(
    selected: list[dict[str, Any]],
    exact_pools: dict[str, list[dict[str, Any]]],
    exact_reasons: dict[str, str],
) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for row in selected:
        exact = exact_pools.get(row["token_address"], [])
        observed = row["observed_pools"]
        if exact:
            pools = [
                {
                    "pool_address": pool["pool_address"],
                    "protocol": pool["protocol"],
                    "token0": pool["token0"],
                    "token1": pool["token1"],
                    "creation_block": pool["block_number"],
                    "creation_timestamp": pool.get("block_timestamp"),
                    "creation_transaction_hash": pool.get("transaction_hash"),
                }
                for pool in exact
            ]
            complete = row["token_address"] not in exact_reasons
            scope_reason = exact_reasons.get(row["token_address"], "rpc_exact_pool_scope")
        else:
            pools = observed
            complete = False
            scope_reason = exact_reasons.get(row["token_address"], "using_window_observed_pool_scope")
        entities.append(
            {
                "token_address": row["token_address"],
                "launch_period": row["launch_period"],
                "first_observed_block": row["first_observed_block"],
                "first_observed_timestamp": row["first_observed_timestamp"],
                "observed_pool_count": row["observed_pool_count"],
                "pool_count_stratum": row["pool_count_stratum"],
                "observed_protocols": row["observed_protocols"],
                "counterparty_count": row["counterparty_count"],
                "sampling_rank": row["sampling_rank"],
                "sampling_label_inspected": False,
                "pool_scope_complete": complete,
                "pool_scope_reason": scope_reason,
                "pools": sorted({pool["pool_address"]: pool for pool in pools}.values(), key=lambda p: p["pool_address"]),
                "activity_collected": False,
            }
        )
    return entities


def event_name_for_topic(protocol: dict[str, Any], topic: str | None) -> str | None:
    if not topic:
        return None
    for name, details in protocol["activity_events"].items():
        if topic.lower() == details["topic"].lower():
            return name
    return None


def normalize_activity_item(
    protocol: dict[str, Any],
    pool: dict[str, Any],
    item: dict[str, Any],
    request_id: str,
) -> dict[str, Any] | None:
    topics = item.get("topics") or []
    event_name = event_name_for_topic(protocol, topics[0] if topics else None)
    if event_name is None:
        return None
    return {
        "protocol": protocol["name"],
        "pool_address": normalize_address(pool["pool_address"]),
        "token0": normalize_address(pool["token0"]),
        "token1": normalize_address(pool["token1"]),
        "token_address": None,
        "event_type": event_name,
        "block_number": as_int(item["block_number"]),
        "block_hash": item.get("block_hash"),
        "block_timestamp": item.get("block_timestamp"),
        "transaction_hash": item.get("transaction_hash"),
        "log_index": as_int(item.get("index", 0)),
        "topics": topics,
        "data": item.get("data"),
        "source_request_id": request_id,
        "source": "blockscout_rest",
    }


def normalize_rpc_activity_item(
    protocol: dict[str, Any],
    pool: dict[str, Any],
    item: dict[str, Any],
    request_id: str,
    block_timestamp: str | None,
) -> dict[str, Any] | None:
    topics = item.get("topics") or []
    event_name = event_name_for_topic(protocol, topics[0] if topics else None)
    if event_name is None:
        return None
    return {
        "protocol": protocol["name"],
        "pool_address": normalize_address(pool["pool_address"]),
        "token0": normalize_address(pool["token0"]),
        "token1": normalize_address(pool["token1"]),
        "token_address": None,
        "event_type": event_name,
        "block_number": as_int(item["blockNumber"]),
        "block_hash": item.get("blockHash"),
        "block_timestamp": block_timestamp,
        "transaction_hash": item.get("transactionHash"),
        "log_index": as_int(item.get("logIndex", 0)),
        "topics": topics,
        "data": item.get("data"),
        "source_request_id": request_id,
        "source": "tenderly_rpc",
    }


def iso_block_timestamp(value: int) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def collect_activity_rpc(
    config: dict[str, Any],
    entities: list[dict[str, Any]],
    rpc: RpcClient,
    output: Path,
    *,
    token_limit: int,
    block_horizon: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect bounded pool histories through an archive-capable JSON-RPC source."""
    protocol_map = protocol_by_name(config)
    selected_entities = sorted(entities, key=lambda row: row["sampling_rank"])[:token_limit]
    activity_topics = sorted(
        {
            details["topic"]
            for protocol in config["protocols"]
            for details in protocol["activity_events"].values()
        }
    )
    try:
        latest_response, latest_request_id = rpc.call("eth_blockNumber", [])
        if latest_response.get("error") or not latest_response.get("result"):
            raise RequestFailure(f"eth_blockNumber failed: {json_dump(latest_response)}")
        latest_block = as_int(latest_response["result"])
    except RequestFailure as exc:
        coverage = []
        for entity in selected_entities:
            for pool in entity["pools"]:
                coverage.append(
                    {
                        "token_address": entity["token_address"],
                        "pool_address": pool["pool_address"],
                        "protocol": pool["protocol"],
                        "launch_block": pool["creation_block"],
                        "horizon_blocks": block_horizon,
                        "pages": 0,
                        "request_ids": [],
                        "crossed_launch": False,
                        "complete": False,
                        "failure": str(exc),
                    }
                )
        write_jsonl(output / "raw_events.jsonl", [])
        write_jsonl(output / "events.jsonl", [])
        write_jsonl(output / "manifests" / "activity_coverage.jsonl", coverage)
        write_json(output / "manifests" / "activity_rpc_failure.json", {"error": str(exc)})
        return [], coverage

    pool_records: list[dict[str, Any]] = []
    block_numbers: set[int] = set()
    for entity in selected_entities:
        for pool in entity["pools"]:
            launch_block = as_int(pool["creation_block"])
            end_block = min(latest_block, launch_block + block_horizon)
            request_ids: list[str] = []
            logs: list[dict[str, Any]] = []
            failure: str | None = None
            complete = True

            def collect_range(from_block: int, to_block: int, depth: int = 0) -> None:
                nonlocal failure, complete
                if failure:
                    return
                call = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_getLogs",
                    "params": [
                        {
                            "address": normalize_address(pool["pool_address"]),
                            "fromBlock": hex(from_block),
                            "toBlock": hex(to_block),
                            "topics": [activity_topics],
                        }
                    ],
                }
                response: dict[str, Any] = {}
                range_split = False
                for attempt in range(1, 5):
                    try:
                        responses, request_id = rpc.batch([call])
                    except RequestFailure as exc:
                        if attempt < 4:
                            time.sleep(min(2**attempt, 8))
                            continue
                        failure = str(exc)
                        complete = False
                        return
                    request_ids.append(request_id)
                    response = responses[0] if responses else {}
                    error = response.get("error")
                    if not error:
                        break
                    if is_rpc_range_error(error):
                        range_split = True
                        break
                    if error.get("code") in {-32005, -32603} and attempt < 4:
                        time.sleep(min(2**attempt, 8))
                        continue
                    failure = f"rpc_activity_error:{error}"
                    complete = False
                    return
                if range_split:
                    if from_block >= to_block or depth >= 24:
                        failure = "rpc_activity_range_error_at_minimum_range"
                        complete = False
                        return
                    midpoint = (from_block + to_block) // 2
                    collect_range(from_block, midpoint, depth + 1)
                    collect_range(midpoint + 1, to_block, depth + 1)
                    return
                range_logs = response.get("result") or []
                capped = len(range_logs) >= MAX_RESPONSE_ITEMS
                if capped and from_block < to_block and depth < 24:
                    midpoint = (from_block + to_block) // 2
                    collect_range(from_block, midpoint, depth + 1)
                    collect_range(midpoint + 1, to_block, depth + 1)
                    return
                if capped:
                    failure = "rpc_activity_response_cap_at_minimum_range"
                    complete = False
                    return
                logs.extend({**item, "_request_id": request_id} for item in range_logs)

            if launch_block <= end_block:
                collect_range(launch_block, end_block)
            else:
                failure = "pool_creation_after_latest_block"
                complete = False
            for item in logs:
                try:
                    block_numbers.add(as_int(item["blockNumber"]))
                except (KeyError, TypeError, ValueError):
                    complete = False
                    failure = failure or "rpc_activity_missing_block_number"
            pool_records.append(
                {
                    "entity": entity,
                    "pool": pool,
                    "logs": logs,
                    "request_ids": request_ids,
                    "complete": complete,
                    "failure": failure,
                }
            )

    block_timestamps: dict[int, str] = {}
    timestamp_request_ids: list[str] = []
    timestamp_failure: str | None = None
    block_list = sorted(block_numbers)
    for start in range(0, len(block_list), 50):
        block_chunk = block_list[start : start + 50]
        calls = [
            {
                "jsonrpc": "2.0",
                "id": index + 1,
                "method": "eth_getBlockByNumber",
                "params": [hex(block_number), False],
            }
            for index, block_number in enumerate(block_chunk)
        ]
        for attempt in range(1, 5):
            try:
                responses, request_id = rpc.batch(calls)
                break
            except RequestFailure as exc:
                if attempt == 4:
                    timestamp_failure = str(exc)
                    responses = []
                    request_id = ""
                    break
                time.sleep(min(2**attempt, 8))
        if not responses:
            break
        timestamp_request_ids.append(request_id)
        response_by_id = {response.get("id"): response for response in responses}
        for index, block_number in enumerate(block_chunk, start=1):
            response = response_by_id.get(index, {})
            if response.get("error") or not response.get("result", {}).get("timestamp"):
                timestamp_failure = timestamp_failure or f"missing_block_timestamp:{block_number}"
                continue
            block_timestamps[block_number] = iso_block_timestamp(as_int(response["result"]["timestamp"]))

    events: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []
    for record in pool_records:
        entity = record["entity"]
        pool = record["pool"]
        request_ids = record["request_ids"] + timestamp_request_ids
        pool_failure = record["failure"] or timestamp_failure
        for item in record["logs"]:
            block_number = as_int(item["blockNumber"])
            block_timestamp = block_timestamps.get(block_number)
            if block_timestamp is None:
                continue
            protocol = protocol_map[pool["protocol"]]
            source_request_id = item.get("_request_id")
            if not source_request_id:
                source_request_id = timestamp_request_ids[-1] if timestamp_request_ids else latest_request_id
            parsed = normalize_rpc_activity_item(protocol, pool, item, source_request_id, block_timestamp)
            if parsed:
                parsed["token_address"] = entity["token_address"]
                events[event_key(parsed)] = parsed
        coverage.append(
            {
                "token_address": entity["token_address"],
                "pool_address": pool["pool_address"],
                "protocol": pool["protocol"],
                "launch_block": as_int(pool["creation_block"]),
                "horizon_blocks": block_horizon,
                "pages": len(record["request_ids"]),
                "request_ids": request_ids + timestamp_request_ids,
                "crossed_launch": True,
                "complete": record["complete"] and pool_failure is None,
                "failure": pool_failure,
            }
        )
    result = sorted(events.values(), key=lambda row: (row["token_address"], row["block_number"], row["log_index"]))
    coverage_by_token: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in coverage:
        coverage_by_token[row["token_address"]].append(row)
    for entity in selected_entities:
        entity_coverage = coverage_by_token[entity["token_address"]]
        entity["activity_collected"] = bool(entity_coverage) and all(
            row["complete"] for row in entity_coverage
        )
        failures = [row["failure"] for row in entity_coverage if row["failure"]]
        entity["activity_collection_reason"] = ";".join(failures) if failures else "bounded_history_collected"
    write_jsonl(output / "raw_events.jsonl", result)
    write_jsonl(output / "events.jsonl", result)
    write_jsonl(output / "manifests" / "activity_coverage.jsonl", coverage)
    return result, coverage


def collect_activity_rpc_batched(
    config: dict[str, Any],
    entities: list[dict[str, Any]],
    rpc: RpcClient,
    output: Path,
    *,
    token_limit: int,
    block_horizon: int,
    pool_group_size: int = 20,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect pool histories with multi-address filters to reduce RPC calls."""
    protocol_map = protocol_by_name(config)
    selected_entities = sorted(entities, key=lambda row: row["sampling_rank"])[:token_limit]
    pool_records: dict[str, dict[str, Any]] = {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entity in selected_entities:
        for pool in entity["pools"]:
            record = {
                "entity": entity,
                "pool": pool,
                "logs": [],
                "request_ids": [],
                "complete": True,
                "failure": None,
            }
            pool_address = normalize_address(pool["pool_address"])
            pool_records[pool_address] = record
            groups[(entity["launch_period"], pool["protocol"])].append(record)

    try:
        latest_response, latest_request_id = rpc.call("eth_blockNumber", [])
        if latest_response.get("error") or not latest_response.get("result"):
            raise RequestFailure(f"eth_blockNumber failed: {json_dump(latest_response)}")
        latest_block = as_int(latest_response["result"])
    except RequestFailure as exc:
        for record in pool_records.values():
            record["complete"] = False
            record["failure"] = str(exc)
        write_json(output / "manifests" / "activity_rpc_failure.json", {"error": str(exc)})
        return _finish_rpc_activity(
            config,
            pool_records,
            {},
            [],
            output,
            latest_request_id="",
            block_horizon=block_horizon,
        )

    for (period, protocol_name), records in sorted(groups.items()):
        protocol = protocol_map[protocol_name]
        topic_values = sorted(details["topic"] for details in protocol["activity_events"].values())
        for start in range(0, len(records), pool_group_size):
            group = records[start : start + pool_group_size]
            addresses = sorted(normalize_address(record["pool"]["pool_address"]) for record in group)
            from_block = min(as_int(record["pool"]["creation_block"]) for record in group)
            to_block = min(latest_block, max(as_int(record["pool"]["creation_block"]) for record in group) + block_horizon)

            def collect_range(group_from: int, group_to: int, depth: int = 0) -> None:
                call = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_getLogs",
                    "params": [
                        {
                            "address": addresses,
                            "fromBlock": hex(group_from),
                            "toBlock": hex(group_to),
                            "topics": [topic_values],
                        }
                    ],
                }
                response: dict[str, Any] = {}
                request_id = ""
                split_required = False
                failure: str | None = None
                for attempt in range(1, 5):
                    try:
                        responses, request_id = rpc.batch([call])
                    except RequestFailure as exc:
                        if attempt < 4:
                            time.sleep(min(2**attempt, 8))
                            continue
                        failure = str(exc)
                        break
                    response = responses[0] if responses else {}
                    error = response.get("error")
                    if not error:
                        break
                    if is_rpc_range_error(error):
                        split_required = True
                        break
                    if error.get("code") in {-32005, -32603} and attempt < 4:
                        time.sleep(min(2**attempt, 8))
                        continue
                    failure = f"rpc_activity_error:{error}"
                    break
                if split_required:
                    if group_from >= group_to or depth >= 24:
                        failure = "rpc_activity_range_error_at_minimum_range"
                    else:
                        midpoint = (group_from + group_to) // 2
                        collect_range(group_from, midpoint, depth + 1)
                        collect_range(midpoint + 1, group_to, depth + 1)
                        return
                if failure:
                    for record in group:
                        record["complete"] = False
                        record["failure"] = record["failure"] or failure
                    return
                for record in group:
                    record["request_ids"].append(request_id)
                logs = response.get("result") or []
                if len(logs) >= MAX_RESPONSE_ITEMS and group_from < group_to and depth < 24:
                    midpoint = (group_from + group_to) // 2
                    collect_range(group_from, midpoint, depth + 1)
                    collect_range(midpoint + 1, group_to, depth + 1)
                    return
                if len(logs) >= MAX_RESPONSE_ITEMS:
                    for record in group:
                        record["complete"] = False
                        record["failure"] = record["failure"] or "rpc_activity_response_cap_at_minimum_range"
                    return
                by_address = {normalize_address(record["pool"]["pool_address"]): record for record in group}
                for item in logs:
                    record = by_address.get(normalize_address(item.get("address")))
                    if record is not None:
                        record["logs"].append({**item, "_request_id": request_id})

            if from_block <= to_block:
                collect_range(from_block, to_block)
            else:
                for record in group:
                    record["complete"] = False
                    record["failure"] = "pool_creation_after_latest_block"

    block_numbers = sorted(
        {
            as_int(item["blockNumber"])
            for record in pool_records.values()
            for item in record["logs"]
            if item.get("blockNumber") is not None
        }
    )
    block_timestamps: dict[int, str] = {}
    missing_timestamps: set[int] = set()
    timestamp_request_ids: list[str] = []
    for start in range(0, len(block_numbers), 100):
        block_chunk = block_numbers[start : start + 100]
        calls = [
            {
                "jsonrpc": "2.0",
                "id": index + 1,
                "method": "eth_getBlockByNumber",
                "params": [hex(block_number), False],
            }
            for index, block_number in enumerate(block_chunk)
        ]
        responses: list[dict[str, Any]] = []
        request_id = ""
        for attempt in range(1, 5):
            try:
                responses, request_id = rpc.batch(calls)
                break
            except RequestFailure:
                if attempt == 4:
                    responses = []
                    break
                time.sleep(min(2**attempt, 8))
        if request_id:
            timestamp_request_ids.append(request_id)
        response_by_id = {response.get("id"): response for response in responses}
        for index, block_number in enumerate(block_chunk, start=1):
            response = response_by_id.get(index, {})
            if response.get("error") or not response.get("result", {}).get("timestamp"):
                missing_timestamps.add(block_number)
                continue
            block_timestamps[block_number] = iso_block_timestamp(as_int(response["result"]["timestamp"]))

    return _finish_rpc_activity(
        config,
        pool_records,
        block_timestamps,
        timestamp_request_ids,
        output,
        latest_request_id=latest_request_id,
        missing_timestamps=missing_timestamps,
        block_horizon=block_horizon,
    )


def _finish_rpc_activity(
    config: dict[str, Any],
    pool_records: dict[str, dict[str, Any]],
    block_timestamps: dict[int, str],
    timestamp_request_ids: list[str],
    output: Path,
    *,
    latest_request_id: str,
    missing_timestamps: set[int] | None = None,
    block_horizon: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    protocol_map = protocol_by_name(config)
    missing_timestamps = missing_timestamps or set()
    events: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []
    for record in pool_records.values():
        entity = record["entity"]
        pool = record["pool"]
        pool_blocks = {as_int(item["blockNumber"]) for item in record["logs"] if item.get("blockNumber") is not None}
        missing_pool_timestamps = pool_blocks & missing_timestamps
        failure = record["failure"]
        if missing_pool_timestamps:
            failure = failure or f"missing_block_timestamps:{len(missing_pool_timestamps)}"
        for item in record["logs"]:
            block_number = as_int(item["blockNumber"])
            block_timestamp = block_timestamps.get(block_number)
            if block_timestamp is None:
                continue
            parsed = normalize_rpc_activity_item(
                protocol_map[pool["protocol"]],
                pool,
                item,
                item.get("_request_id") or latest_request_id,
                block_timestamp,
            )
            if parsed:
                parsed["token_address"] = entity["token_address"]
                events[event_key(parsed)] = parsed
        record["complete"] = record["complete"] and failure is None
        record["failure"] = failure
        coverage.append(
            {
                "token_address": entity["token_address"],
                "pool_address": pool["pool_address"],
                "protocol": pool["protocol"],
                "launch_block": as_int(pool["creation_block"]),
                "horizon_blocks": block_horizon,
                "pages": len(record["request_ids"]),
                "request_ids": record["request_ids"] + timestamp_request_ids,
                "crossed_launch": True,
                "complete": record["complete"],
                "failure": record["failure"],
            }
        )
    by_token: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in coverage:
        by_token[row["token_address"]].append(row)
    entities_by_token = {
        record["entity"]["token_address"]: record["entity"] for record in pool_records.values()
    }
    for entity in entities_by_token.values():
        entity_coverage = by_token[entity["token_address"]]
        entity["activity_collected"] = bool(entity_coverage) and all(row["complete"] for row in entity_coverage)
        failures = [row["failure"] for row in entity_coverage if row["failure"]]
        entity["activity_collection_reason"] = ";".join(failures) if failures else "bounded_history_collected"
    result = sorted(events.values(), key=lambda row: (row["token_address"], row["block_number"], row["log_index"]))
    write_jsonl(output / "raw_events.jsonl", result)
    write_jsonl(output / "events.jsonl", result)
    write_jsonl(output / "manifests" / "activity_coverage.jsonl", coverage)
    return result, coverage


def collect_activity(
    config: dict[str, Any],
    entities: list[dict[str, Any]],
    rest: RestClient,
    output: Path,
    *,
    token_limit: int,
    max_pages: int,
    block_horizon: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    protocol_map = protocol_by_name(config)
    selected_entities = sorted(entities, key=lambda row: row["sampling_rank"])[:token_limit]
    events: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []
    for entity in entities:
        if entity not in selected_entities:
            continue
        entity_failure: str | None = None
        entity_complete = True
        for pool in entity["pools"]:
            protocol = protocol_map[pool["protocol"]]
            launch_block = as_int(pool["creation_block"])
            params: dict[str, Any] = {
                "block_number": launch_block + block_horizon,
                "index": 0,
                "items_count": 50,
            }
            pages = 0
            request_ids: list[str] = []
            crossed_launch = False
            failure: str | None = None
            while pages < max_pages:
                try:
                    payload, request_id = rest.get(
                        f"addresses/{normalize_address(pool['pool_address'])}/logs", params
                    )
                except RequestFailure as exc:
                    failure = str(exc)
                    entity_complete = False
                    break
                request_ids.append(request_id)
                pages += 1
                items = payload.get("items") or []
                for item in items:
                    try:
                        block_number = as_int(item["block_number"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if block_number < launch_block:
                        continue
                    parsed = normalize_activity_item(protocol, pool, item, request_id)
                    if parsed:
                        parsed["token_address"] = entity["token_address"]
                        events[event_key(parsed)] = parsed
                if items and min(as_int(item["block_number"]) for item in items if item.get("block_number") is not None) <= launch_block:
                    crossed_launch = True
                    break
                next_params = payload.get("next_page_params")
                if not next_params:
                    crossed_launch = True
                    break
                params = next_params
            if not crossed_launch and failure is None:
                failure = f"page_limit_reached:{max_pages}"
                entity_complete = False
            if failure:
                entity_failure = failure if entity_failure is None else f"{entity_failure};{failure}"
            coverage.append(
                {
                    "token_address": entity["token_address"],
                    "pool_address": pool["pool_address"],
                    "protocol": pool["protocol"],
                    "launch_block": launch_block,
                    "horizon_blocks": block_horizon,
                    "pages": pages,
                    "request_ids": request_ids,
                    "crossed_launch": crossed_launch,
                    "complete": crossed_launch and failure is None,
                    "failure": failure,
                }
            )
        entity["activity_collected"] = entity_complete
        entity["activity_collection_reason"] = entity_failure or "bounded_history_collected"
    result = sorted(events.values(), key=lambda row: (row["token_address"], row["block_number"], row["log_index"]))
    write_jsonl(output / "raw_events.jsonl", result)
    write_jsonl(output / "events.jsonl", result)
    write_jsonl(output / "manifests" / "activity_coverage.jsonl", coverage)
    return result, coverage


def outcome_for_entity(
    entity: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    now: datetime,
    followup_days: int,
    observation_swaps: int,
) -> dict[str, Any]:
    token_events = sorted(events, key=lambda row: (row["block_number"], row["log_index"]))
    qualifying = [row for row in token_events if row["event_type"] in EVENT_NAMES]
    swaps = [row for row in token_events if row["event_type"] == "swap"]
    t0 = parse_time(qualifying[0].get("block_timestamp")) if qualifying else None
    base = {
        "token_address": entity["token_address"],
        "launch_period": entity["launch_period"],
        "t0": t0.isoformat().replace("+00:00", "Z") if t0 else None,
        "first_observed_block": entity["first_observed_block"],
        "observation_swap_count": len(swaps),
        "pool_count": len(entity["pools"]),
        "pool_scope_complete": entity["pool_scope_complete"],
        "activity_collected": entity["activity_collected"],
        "censoring_reason": None,
        "exclusion_reason": None,
        "evidence_event_ids": [event_key(row) for row in token_events[:10]],
    }
    if not entity["pool_scope_complete"]:
        base["label"] = "censored"
        base["censoring_reason"] = f"pool_scope_incomplete:{entity['pool_scope_reason']}"
        return base
    if not entity["activity_collected"]:
        base["label"] = "censored"
        base["censoring_reason"] = f"activity_retrieval_incomplete:{entity.get('activity_collection_reason')}"
        return base
    if len(swaps) < observation_swaps:
        base["label"] = "excluded_early_death"
        base["exclusion_reason"] = "fewer_than_10_qualifying_swaps_in_retrieved_history"
        return base
    cutoff = parse_time(swaps[observation_swaps - 1].get("block_timestamp"))
    if cutoff is None:
        base["label"] = "censored"
        base["censoring_reason"] = "missing_cutoff_timestamp"
        return base
    followup_end = cutoff + timedelta(days=followup_days)
    base["cutoff"] = cutoff.isoformat().replace("+00:00", "Z")
    base["followup_end"] = followup_end.isoformat().replace("+00:00", "Z")
    base["cutoff_event_id"] = event_key(swaps[observation_swaps - 1])
    if followup_end > now:
        base["label"] = "censored"
        base["censoring_reason"] = "followup_not_complete_at_retrieval"
        return base
    followup_events = [
        row
        for row in qualifying
        if parse_time(row.get("block_timestamp")) and cutoff < parse_time(row["block_timestamp"]) <= followup_end
    ]
    base["followup_event_count"] = len(followup_events)
    base["followup_evidence_event_ids"] = [event_key(row) for row in followup_events[:50]]
    if followup_events:
        base["label"] = "continued_activity"
    else:
        base["label"] = "failure"
    return base


def partition_for_outcome(outcome: dict[str, Any], config: dict[str, Any]) -> tuple[str, str | None]:
    if outcome["label"] not in {"failure", "continued_activity"}:
        return "excluded", outcome.get("censoring_reason") or outcome.get("exclusion_reason")
    t0 = parse_time(outcome.get("t0"))
    if t0 is None:
        return "excluded", "missing_t0"
    train_end = parse_time(config["split"]["train_end"])
    validation_end = parse_time(config["split"]["validation_end"])
    test_end = parse_time(config["split"]["test_end"])
    if train_end and t0 < train_end:
        return "train", None
    if validation_end and t0 < validation_end:
        return "validation", None
    if test_end and t0 <= test_end:
        return "test", None
    return "excluded", "launch_after_test_cutoff"


def build_outcomes(
    config: dict[str, Any],
    entities: list[dict[str, Any]],
    events: list[dict[str, Any]],
    output: Path,
    *,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_token: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_token[event["token_address"]].append(event)
    outcomes: list[dict[str, Any]] = []
    split_rows: list[dict[str, Any]] = []
    censoring: list[dict[str, Any]] = []
    for entity in entities:
        outcome = outcome_for_entity(
            entity,
            by_token[entity["token_address"]],
            now=now,
            followup_days=config["labels"]["followup_days"],
            observation_swaps=config["labels"]["observation_swap_count"],
        )
        outcomes.append(outcome)
        partition, exclusion_reason = partition_for_outcome(outcome, config)
        split_rows.append(
            {
                "token_address": entity["token_address"],
                "t0": outcome.get("t0"),
                "cutoff": outcome.get("cutoff"),
                "followup_end": outcome.get("followup_end"),
                "label": outcome["label"],
                "censoring_status": outcome["label"] == "censored",
                "censoring_reason": outcome.get("censoring_reason"),
                "overlap_group": entity["token_address"],
                "partition": partition,
                "exclusion_reason": exclusion_reason,
                "split_frozen_before_test_labels": False,
            }
        )
        if outcome["label"] == "censored":
            censoring.append(
                {
                    "token_address": entity["token_address"],
                    "reason": outcome.get("censoring_reason"),
                    "retrieved_at": now.isoformat().replace("+00:00", "Z"),
                }
            )
    write_jsonl(output / "outcomes.jsonl", outcomes)
    write_jsonl(output / "censoring_reasons.jsonl", censoring)
    write_jsonl(output / "split_manifest.jsonl", split_rows)
    return outcomes, split_rows


def make_report(
    config: dict[str, Any],
    factory_events: list[dict[str, Any]],
    factory_coverage: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    activity_events: list[dict[str, Any]],
    activity_coverage: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    split_rows: list[dict[str, Any]],
    output: Path,
    *,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    outcome_counts = Counter(row["label"] for row in outcomes)
    partition_counts = Counter(row["partition"] for row in split_rows)
    labels = {"failure", "continued_activity"}
    eligible = [row for row in outcomes if row["observation_swap_count"] >= config["labels"]["observation_swap_count"]]
    eligible_censored = sum(row["label"] == "censored" for row in eligible)
    test_outcomes = [row for row in split_rows if row["partition"] == "test"]
    test_labels = Counter(row["label"] for row in test_outcomes)
    test_periods = sorted({row.get("t0", "")[:4] for row in test_outcomes if row.get("t0")})
    source_request_log = read_jsonl(output / "manifests" / "request_log.jsonl")
    status_counts = Counter(str(row.get("status")) for row in source_request_log)
    gate_checks = {
        "overall_30_each_outcome": outcome_counts["failure"] >= 30 and outcome_counts["continued_activity"] >= 30,
        "validation_10_each_where_feasible": True,
        "test_10_each_where_feasible": test_labels["failure"] >= 10 and test_labels["continued_activity"] >= 10,
        "test_spans_two_launch_periods": len(test_periods) >= 2,
        "eligible_censoring_below_20_percent": bool(eligible) and eligible_censored / len(eligible) < 0.20,
        "event_histories_and_labels_reproducible": bool(activity_events) and all(
            row["complete"] for row in activity_coverage
        ),
        "source_terms_limits_cost_documented": config["source"].get("terms_status") == "audited",
    }
    limitations = [
        "This is a Week 1 pilot and does not authorize modelling or a GNN.",
        "The selected DEX scope is Uniswap V2 and V3 Ethereum mainnet factories only.",
        "Blockscout REST address-log endpoints return keyset pages; the pilot records bounded cursor coverage and does not infer completeness when a page limit or source error is hit.",
        "Pool-scope completeness depends on the filtered Blockscout RPC request; failed or capped requests are censored rather than treated as healthy.",
        "Observed pool-count strata describe pools seen in the sampled windows, not all pools for a token; the pilot must not treat a stratum of 1 as a complete pool count.",
        "Public RPC endpoints can return rate-limit or transient-service errors; affected pool histories are censored rather than treated as healthy.",
        "Source terms and data licensing require institutional review before publication or redistribution.",
    ]
    report = {
        "report_version": "week1-feasibility-0.1",
        "retrieval_started_at": started_at,
        "retrieval_finished_at": finished_at,
        "source": config["source"],
        "protocols": config["protocols"],
        "counts": {
            "factory_events": len(factory_events),
            "sampling_candidates": len(read_jsonl(output / "sampling_frame.jsonl")),
            "selected_token_entities": len(entities),
            "activity_events": len(activity_events),
            "outcomes": len(outcomes),
            "outcome_counts": dict(outcome_counts),
            "partition_counts": dict(partition_counts),
            "request_status_counts": dict(status_counts),
            "sampling_pool_strata": dict(
                Counter(row["pool_count_stratum"] for row in read_jsonl(output / "sampling_frame.jsonl"))
            ),
            "archive": archive_integrity(output),
        },
        "coverage": {
            "factory_windows_complete": sum(row["complete"] for row in factory_coverage),
            "factory_windows_total": len(factory_coverage),
            "activity_pools_complete": sum(row["complete"] for row in activity_coverage),
            "activity_pools_total": len(activity_coverage),
            "entities_with_complete_pool_scope": sum(row["pool_scope_complete"] for row in entities),
            "entities_with_activity_collected": sum(row["activity_collected"] for row in entities),
        },
        "gate_checks": gate_checks,
        "go_no_go": all(gate_checks.values()),
        "limitations": limitations,
        "next_action": "Do not implement the GNN; repair source coverage or reduce scope until the gate is satisfied.",
    }
    write_json(output / "audit_report.json", report)
    return report


def repair_duplicate_archive_paths(output: Path) -> int:
    """Give each existing manifest row its own raw response path."""
    manifest_path = output / "manifests" / "request_log.jsonl"
    rows = read_jsonl(manifest_path)
    seen_paths: set[str] = set()
    repaired = 0
    for sequence, row in enumerate(rows, start=1):
        raw_path_value = row.get("raw_path")
        if str(raw_path_value or "").endswith(".jsonl.gz"):
            continue
        if not raw_path_value or raw_path_value not in seen_paths:
            if raw_path_value:
                seen_paths.add(raw_path_value)
            continue
        raw_path = output / raw_path_value
        if not raw_path.exists():
            continue
        response_id = sha256_bytes(
            f"{row.get('response_id', '')}|archive-repair-sequence={sequence}".encode("utf-8")
        )
        repaired_path = output / "raw" / f"{response_id}.json"
        payload = read_json(raw_path)
        payload["response_id"] = response_id
        write_json(repaired_path, payload)
        row["response_id"] = response_id
        row["raw_path"] = str(repaired_path.relative_to(output))
        seen_paths.add(row["raw_path"])
        repaired += 1
    if repaired:
        write_jsonl(manifest_path, rows)
    return repaired


def archive_integrity(output: Path) -> dict[str, int]:
    rows = read_jsonl(output / "manifests" / "request_log.jsonl")
    paths = [row["raw_path"] for row in rows if row.get("raw_path")]
    missing = 0
    checksum_failures = 0
    references = [
        (
            row["raw_path"],
            int(row["raw_line"]) if str(row.get("raw_path", "")).endswith(".jsonl.gz") else None,
        )
        for row in rows
        if row.get("raw_path")
    ]
    bundle_rows: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    plain_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        raw_path_value = row.get("raw_path")
        if not raw_path_value:
            continue
        if str(raw_path_value).endswith(".jsonl.gz"):
            bundle_rows[str(raw_path_value)][int(row["raw_line"])] = row
        else:
            plain_rows[str(raw_path_value)].append(row)

    def verify_payload(payload: dict[str, Any]) -> None:
        nonlocal checksum_failures
        response = payload.get("response", {})
        expected = response.get("body_sha256")
        actual = sha256_bytes(json_dump(response.get("body")).encode("utf-8"))
        checksum_failures += expected != actual

    for raw_path_value, referenced_rows in plain_rows.items():
        raw_path = output / raw_path_value
        if not raw_path.exists():
            missing += len(referenced_rows)
            continue
        payload = read_json(raw_path)
        for _ in referenced_rows:
            verify_payload(payload)
    for raw_path_value, line_rows in bundle_rows.items():
        raw_path = output / raw_path_value
        if not raw_path.exists():
            missing += len(line_rows)
            continue
        found: set[int] = set()
        with gzip.open(raw_path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if line_number not in line_rows:
                    continue
                verify_payload(json.loads(line))
                found.add(line_number)
        missing += len(set(line_rows) - found)

    raw_directory = output / "raw"
    raw_files = sum(1 for path in raw_directory.iterdir() if path.is_file()) if raw_directory.exists() else 0
    return {
        "request_manifest_rows": len(rows),
        "unique_raw_paths": len(set(paths)),
        "unique_raw_records": len(set(references)),
        "raw_files": raw_files,
        "duplicate_raw_paths": len(references) - len(set(references)),
        "missing_raw_files": missing,
        "checksum_failures": checksum_failures,
    }


def source_manifest(config: dict[str, Any], output: Path, *, started_at: str, finished_at: str) -> None:
    requests = read_jsonl(output / "manifests" / "request_log.jsonl")
    write_json(
        output / "source_retrieval_manifest.json",
        {
            "manifest_version": "week1-source-retrieval-0.1",
            "started_at": started_at,
            "finished_at": finished_at,
            "source": config["source"],
            "request_count": len(requests),
            "status_counts": dict(Counter(str(row.get("status")) for row in requests)),
            "failed_requests": [row for row in requests if row.get("error")],
            "raw_response_directory": "raw/",
            "raw_response_storage": "gzip JSONL bundles; request_log.raw_path and request_log.raw_line identify each record",
            "raw_request_log": "manifests/request_log.jsonl",
            "checksums": "Each raw response stores a SHA-256 checksum of its canonical JSON body.",
        },
    )


def rebuild_report(config: dict[str, Any], output: Path) -> dict[str, Any]:
    config = reporting_config(config)
    metadata = read_json(output / "run_metadata.json")
    repair_duplicate_archive_paths(output)
    report = make_report(
        config,
        read_jsonl(output / "factory_events.jsonl"),
        read_jsonl(output / "manifests" / "factory_coverage.jsonl"),
        read_jsonl(output / "token_entities.jsonl"),
        read_jsonl(output / "events.jsonl"),
        read_jsonl(output / "manifests" / "activity_coverage.jsonl"),
        read_jsonl(output / "outcomes.jsonl"),
        read_jsonl(output / "split_manifest.jsonl"),
        output,
        started_at=metadata["started_at"],
        finished_at=utc_now(),
    )
    source_manifest(config, output, started_at=metadata["started_at"], finished_at=report["retrieval_finished_at"])
    return report


def git_head(project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def run(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    output = (project_root / args.output).resolve()
    config = read_json(project_root / args.config)
    output.mkdir(parents=True, exist_ok=True)
    if args.report_only:
        report = rebuild_report(config, output)
        print(json.dumps({"output": str(output), "go_no_go": report["go_no_go"], "counts": report["counts"]}, indent=2))
        return 0
    started_at = utc_now()
    write_json(
        output / "run_metadata.json",
        {
            "started_at": started_at,
            "python": sys.version,
            "executable": sys.executable,
            "git_head": git_head(project_root),
            "config_path": args.config,
            "config_sha256": sha256_bytes((project_root / args.config).read_bytes()),
            "arguments": vars(args),
        },
    )
    archive = RawArchive(output)
    http = HttpClient(
        archive,
        user_agent=config["source"]["user_agent"],
        interval=args.request_interval,
        timeout=args.timeout,
    )
    rest = RestClient(http, config["source"]["rest_url"])
    resolved_rpc = resolve_archive_rpc(
        project_root / ".env",
        fallback_url=config["source"]["rpc_url"],
    )
    rpc = RpcClient(http, resolved_rpc.authenticated_url, archive_url=resolved_rpc.redacted_url)

    if args.factory_source == "rpc":
        factory_events, factory_coverage = collect_factory_windows(config, rpc, output)
    elif args.factory_source == "rest":
        factory_events, factory_coverage = collect_factory_windows_rest(
            config, rest, output, max_pages=args.max_factory_pages
        )
    else:
        try:
            factory_events, factory_coverage = collect_factory_windows(config, rpc, output)
        except RequestFailure:
            factory_events, factory_coverage = collect_factory_windows_rest(
                config, rest, output, max_pages=args.max_factory_pages
            )
    frame = candidate_rows(factory_events, config)
    write_jsonl(output / "sampling_frame.jsonl", frame)
    selected = select_candidates(frame, args.pilot_size)
    write_json(output / "sampling_manifest.json", {
        "sampling_rule": "deterministic SHA-256 order within launch-period quotas and observed-pool strata; labels not inspected before selection",
        "target_tokens": args.pilot_size,
        "selected_tokens": len(selected),
        "candidate_count": len(frame),
        "candidate_period_counts": dict(Counter(row["launch_period"] for row in frame)),
        "selected_period_counts": dict(Counter(row["launch_period"] for row in selected)),
        "selected_stratum_counts": dict(Counter(row["pool_count_stratum"] for row in selected)),
    })

    if args.skip_exact_pool_scope:
        exact_pools = defaultdict(list)
        exact_reasons = {
            row["token_address"]: "exact_pool_scope_skipped_rpc_unavailable"
            for row in selected
        }
        write_json(
            output / "manifests" / "pool_scope_rpc_failure.json",
            {"error": "exact pool scope skipped by CLI; observed-window pools retained and labels censored"},
        )
    else:
        exact_pools, exact_reasons = collect_exact_pool_scope(config, selected, rpc, output)
    entities = enrich_entities(selected, exact_pools, exact_reasons)
    write_jsonl(output / "token_entities.jsonl", entities)

    activity_source = args.activity_source or config["source"].get("activity_source", "rest")
    if activity_source == "rpc":
        activity_rpc = RpcClient(http, resolved_rpc.authenticated_url, archive_url=resolved_rpc.redacted_url)
        activity_events, activity_coverage = collect_activity_rpc_batched(
            config,
            entities,
            activity_rpc,
            output,
            token_limit=args.activity_tokens,
            block_horizon=args.activity_horizon_blocks,
        )
    else:
        activity_events, activity_coverage = collect_activity(
            config,
            entities,
            rest,
            output,
            token_limit=args.activity_tokens,
            max_pages=args.max_activity_pages,
            block_horizon=args.activity_horizon_blocks,
        )
    write_jsonl(output / "token_entities.jsonl", entities)
    now = datetime.now(UTC)
    outcomes, split_rows = build_outcomes(config, entities, activity_events, output, now=now)
    finished_at = utc_now()
    report_config = reporting_config(
        config,
        rpc_url=resolved_rpc.redacted_url,
        rpc_source=resolved_rpc.source,
    )
    report = make_report(
        report_config,
        factory_events,
        factory_coverage,
        entities,
        activity_events,
        activity_coverage,
        outcomes,
        split_rows,
        output,
        started_at=started_at,
        finished_at=finished_at,
    )
    source_manifest(report_config, output, started_at=started_at, finished_at=finished_at)
    print(json.dumps({"output": str(output), "go_no_go": report["go_no_go"], "counts": report["counts"]}, indent=2))
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--config", default="config/week1_config.json")
    parser.add_argument("--output", default="data/week1_pilot")
    parser.add_argument("--pilot-size", type=int, default=100)
    parser.add_argument("--factory-source", choices=("rest", "rpc", "auto"), default="rest")
    parser.add_argument("--max-factory-pages", type=int, default=6)
    parser.add_argument("--skip-exact-pool-scope", action="store_true")
    parser.add_argument("--activity-source", choices=("rest", "rpc"), default=None)
    parser.add_argument("--activity-tokens", type=int, default=20)
    parser.add_argument("--max-activity-pages", type=int, default=8)
    parser.add_argument("--activity-horizon-blocks", type=int, default=2_000_000)
    parser.add_argument("--request-interval", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--report-only", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(make_parser().parse_args()))
