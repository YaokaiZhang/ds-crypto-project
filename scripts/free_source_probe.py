#!/usr/bin/env python3
"""Probe free-only Ethereum data sources without reading project credentials.

This is a transport and historical-capability probe. It does not collect a
cohort, infer labels, or change the archive-backed Week 1 collector.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.week1_audit import (  # noqa: E402
    HttpClient,
    RawArchive,
    RequestFailure,
    redact_url,
    utc_now,
    write_json,
)


HISTORICAL_START = 15_000_000
HISTORICAL_END_10 = HISTORICAL_START + 10
HISTORICAL_END_1000 = HISTORICAL_START + 1_000
KNOWN_V2_POOL = "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc"
V2_SWAP_TOPIC = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"

GRAPH_SUBGRAPHS = {
    "the_graph_v2": {
        "id": "A3Np3RQbaBA6oKJgiwDJeo5T3zrYfGHPWFYayMwtNDum",
        "entity": "uniswapFactory",
        "field": "pairCount",
        "factory": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
    },
    "the_graph_v3": {
        "id": "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV",
        "entity": "factory",
        "collection": "factories",
        "field": "poolCount",
        "factory": "0x1F98431c8aD98523631AE4A59f267346ea31F984",
    },
}


def _safe_text(value: Any, secrets: Iterable[str] = ()) -> str:
    text = str(value)
    for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
        text = text.replace(secret, "REDACTED")
    return text[:500]


def classify_rpc_result(payload: Any) -> dict[str, Any]:
    """Return a small, non-secret summary of one JSON-RPC response."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": f"unexpected_payload:{type(payload).__name__}"}
    if payload.get("error"):
        error = payload["error"]
        if isinstance(error, dict):
            return {
                "ok": False,
                "error_code": error.get("code"),
                "error_message": _safe_text(error.get("message", "rpc_error")),
            }
        return {"ok": False, "error": _safe_text(error)}
    if "result" not in payload:
        return {"ok": False, "error": "missing_result"}
    result = payload["result"]
    summary: dict[str, Any] = {"ok": True, "result_type": type(result).__name__}
    if isinstance(result, list):
        summary["count"] = len(result)
    return summary


def build_graph_endpoint(subgraph_id: str, api_key: str) -> str:
    return (
        "https://gateway.thegraph.com/api/"
        f"{quote(api_key, safe='')}/subgraphs/id/{subgraph_id}"
    )


def _rpc_request(
    http: HttpClient,
    endpoint: str,
    method: str,
    params: list[Any],
    *,
    secrets: Iterable[str] = (),
) -> tuple[Any | None, str | None, str | None]:
    try:
        payload, request_id = http.request(
            "POST",
            endpoint,
            body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            archive_url=redact_url(endpoint, secrets=secrets),
        )
    except RequestFailure as exc:
        return None, None, _safe_text(exc, secrets)
    return payload, request_id, None


def probe_rpc_source(
    http: HttpClient,
    *,
    name: str,
    endpoint: str,
    credential_env: str | None = None,
    secrets: Iterable[str] = (),
) -> dict[str, Any]:
    """Probe current connectivity plus 10- and 1000-block historical logs."""
    safe_endpoint = redact_url(endpoint, secrets=secrets)
    latest, latest_request_id, latest_failure = _rpc_request(
        http, endpoint, "eth_blockNumber", [], secrets=secrets
    )
    small, small_request_id, small_failure = _rpc_request(
        http,
        endpoint,
        "eth_getLogs",
        [
            {
                "address": KNOWN_V2_POOL,
                "fromBlock": hex(HISTORICAL_START),
                "toBlock": hex(HISTORICAL_END_10),
                "topics": [V2_SWAP_TOPIC],
            }
        ],
        secrets=secrets,
    )
    wide, wide_request_id, wide_failure = _rpc_request(
        http,
        endpoint,
        "eth_getLogs",
        [
            {
                "address": KNOWN_V2_POOL,
                "fromBlock": hex(HISTORICAL_START),
                "toBlock": hex(HISTORICAL_END_1000),
                "topics": [V2_SWAP_TOPIC],
            }
        ],
        secrets=secrets,
    )
    latest_summary = classify_rpc_result(latest) if latest is not None else {
        "ok": False,
        "error": latest_failure or "no_response",
    }
    small_summary = classify_rpc_result(small) if small is not None else {
        "ok": False,
        "error": small_failure or "no_response",
    }
    wide_summary = classify_rpc_result(wide) if wide is not None else {
        "ok": False,
        "error": wide_failure or "no_response",
    }
    wide_error = str(wide_summary.get("error_message", wide_summary.get("error", ""))).lower()
    if latest_summary["ok"] and small_summary["ok"] and wide_summary["ok"]:
        status = "pass"
    elif latest_summary["ok"] and small_summary["ok"] and (
        "block" in wide_error or "range" in wide_error or "free tier" in wide_error
    ):
        status = "historical_range_limited"
    elif "unauthorized" in wide_error or "api key" in wide_error or "authenticate" in wide_error:
        status = "unauthorized"
    elif latest_summary["ok"] and small_summary["ok"]:
        status = "historical_probe_partial"
    else:
        status = "error"

    latest_block = None
    if isinstance(latest, dict) and isinstance(latest.get("result"), str):
        try:
            latest_block = int(latest["result"], 16)
        except ValueError:
            latest_block = None
    return {
        "name": name,
        "kind": "rpc",
        "endpoint": safe_endpoint,
        "credential_env": credential_env,
        "credential_present": bool(tuple(secrets)),
        "status": status,
        "latest_block": latest_block,
        "historical_10_block_logs": small_summary.get("count"),
        "historical_1000_block_logs": wide_summary.get("count"),
        "checks": {
            "current_block": latest_summary,
            "historical_10_block_logs": small_summary,
            "historical_1000_block_logs": wide_summary,
        },
        "request_ids": [
            request_id
            for request_id in (latest_request_id, small_request_id, wide_request_id)
            if request_id
        ],
    }


def _graph_query(spec: dict[str, str]) -> str:
    field = spec["field"]
    factory = spec["factory"]
    collection = spec.get("collection")
    if collection:
        return (
            "query { "
            f'current: {collection}(first: 1) '
            f"{{ id {field} }} "
            f'historical: {collection}(first: 1, '
            f"block: {{ number: {HISTORICAL_START} }}) {{ id {field} }} "
            "}"
        )
    entity = spec["entity"]
    return (
        "query { "
        f"current: {entity}(id: \"{factory}\") {{ {field} }} "
        f"historical: {entity}(id: \"{factory}\", block: {{ number: {HISTORICAL_START} }}) "
        f"{{ {field} }} "
        "}"
    )


def probe_graph_source(
    http: HttpClient,
    *,
    name: str,
    spec: dict[str, str],
    api_key: str | None,
    credential_env: str,
) -> dict[str, Any]:
    if not api_key:
        return {
            "name": name,
            "kind": "graphql",
            "status": "not_configured",
            "credential_env": credential_env,
            "credential_present": False,
            "reason": "free Studio API key is required; no request was sent",
        }
    endpoint = build_graph_endpoint(spec["id"], api_key)
    try:
        payload, request_id = http.request(
            "POST",
            endpoint,
            body={"query": _graph_query(spec)},
            archive_url=redact_url(endpoint, secrets=(api_key,)),
        )
    except RequestFailure as exc:
        return {
            "name": name,
            "kind": "graphql",
            "status": "request_error",
            "endpoint": redact_url(endpoint, secrets=(api_key,)),
            "credential_env": credential_env,
            "credential_present": True,
            "error": _safe_text(exc, (api_key,)),
        }
    if not isinstance(payload, dict):
        return {
            "name": name,
            "kind": "graphql",
            "status": "invalid_response",
            "endpoint": redact_url(endpoint, secrets=(api_key,)),
            "credential_env": credential_env,
            "credential_present": True,
            "request_id": request_id,
        }
    errors = payload.get("errors") or []
    data = payload.get("data") or {}
    current = data.get("current")
    historical = data.get("historical")
    if isinstance(current, list):
        current = current[0] if current else None
    if isinstance(historical, list):
        historical = historical[0] if historical else None
    status = "pass" if not errors and current and historical else "query_incomplete"
    return {
        "name": name,
        "kind": "graphql",
        "status": status,
        "endpoint": redact_url(endpoint, secrets=(api_key,)),
        "credential_env": credential_env,
        "credential_present": True,
        "current_fields": sorted(current) if isinstance(current, dict) else [],
        "historical_fields": sorted(historical) if isinstance(historical, dict) else [],
        "graphql_error_count": len(errors),
        "graphql_errors": [_safe_text(error, (api_key,)) for error in errors[:3]],
        "request_ids": [request_id],
    }


def probe_blockscout(http: HttpClient) -> dict[str, Any]:
    endpoint = "https://eth.blockscout.com/api/v2/stats"
    try:
        payload, request_id = http.request("GET", endpoint, archive_url=endpoint)
    except RequestFailure as exc:
        return {
            "name": "blockscout_rest",
            "kind": "rest",
            "endpoint": endpoint,
            "status": "request_error",
            "error": _safe_text(exc),
        }
    return {
        "name": "blockscout_rest",
        "kind": "rest",
        "endpoint": endpoint,
        "status": "pass" if isinstance(payload, dict) else "invalid_response",
        "request_ids": [request_id],
        "response_fields": sorted(payload) if isinstance(payload, dict) else [],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    output = (project_root / args.output).resolve()
    archive = RawArchive(output)
    http = HttpClient(
        archive,
        user_agent="week1-free-source-probe/0.1",
        interval=args.request_interval,
        timeout=args.timeout,
    )

    results: list[dict[str, Any]] = []
    results.append(
        probe_rpc_source(
            http,
            name="1rpc_public",
            endpoint="https://1rpc.io/eth",
        )
    )

    ankr_key = os.environ.get(args.ankr_api_key_env, "").strip()
    ankr_endpoint = "https://rpc.ankr.com/eth"
    if ankr_key:
        ankr_endpoint = f"{ankr_endpoint}/{quote(ankr_key, safe='')}"
    results.append(
        probe_rpc_source(
            http,
            name="ankr_freemium" if ankr_key else "ankr_public",
            endpoint=ankr_endpoint,
            credential_env=args.ankr_api_key_env,
            secrets=(ankr_key,) if ankr_key else (),
        )
    )

    graph_key = os.environ.get(args.graph_api_key_env, "").strip() or None
    for name, spec in GRAPH_SUBGRAPHS.items():
        results.append(
            probe_graph_source(
                http,
                name=name,
                spec=spec,
                api_key=graph_key,
                credential_env=args.graph_api_key_env,
            )
        )
    results.append(probe_blockscout(http))

    graph_pass = [
        row["name"]
        for row in results
        if row["kind"] == "graphql" and row["status"] == "pass"
    ]
    report = {
        "report_version": "free-source-probe-0.1",
        "retrieved_at": utc_now(),
        "reads_project_env": False,
        "credential_environment": {
            "graph_api_key_env": args.graph_api_key_env,
            "graph_api_key_present": bool(graph_key),
            "ankr_api_key_env": args.ankr_api_key_env,
            "ankr_api_key_present": bool(ankr_key),
        },
        "results": results,
        "historical_graph_sources_passing": graph_pass,
        "labels_ready": False,
        "go_no_go": False,
        "decision": (
            "Transport probe only. Do not infer labels or start modelling; "
            "complete the frozen cohort and 90-day follow-up audit first."
        ),
    }
    write_json(output / "free_source_probe.json", report)
    return report


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output", default="data/week1_free_source_probe")
    parser.add_argument("--graph-api-key-env", default="THE_GRAPH_API_KEY")
    parser.add_argument("--ankr-api-key-env", default="ANKR_API_KEY")
    parser.add_argument("--request-interval", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


if __name__ == "__main__":
    parsed_args = make_parser().parse_args()
    report = run(parsed_args)
    print(
        json.dumps(
            {
                "output": str((Path(parsed_args.project_root) / parsed_args.output).resolve()),
                "results": [
                    {"name": row["name"], "status": row["status"]}
                    for row in report["results"]
                ],
                "labels_ready": report["labels_ready"],
            },
            indent=2,
            sort_keys=True,
        )
    )
