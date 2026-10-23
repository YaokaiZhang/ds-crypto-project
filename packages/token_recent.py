"""Bounded backwards token/pool histories, separate from complete-window inputs."""
from __future__ import annotations

from pathlib import Path

from .collection import CollectionError, EtherscanClient
from .data import normalize_records
from .graph import build_graph_sample, graph_is_usable
from .io import save_json, write_records
from .token import TOKEN_RECENT_SAMPLING, TOKEN_RECENT_SCOPE_VERSION, token_scope
from .transactions import address, integer


def sampling_recipe(graph):
    return {key: graph[key] for key in ("hops", "fanouts", "seed", "max_nodes", "sampling_mode",
                                        "rows_per_action", "pages_per_action")}


def _lineage(rows, bundle, action):
    return [{**row, "source_kind": "logs" if action == "getLogs" else "normal" if action == "txlist" else "internal",
             "request_id": bundle["request_id"], "source_row": index,
             "raw_path": bundle["raw_path"], "retrieved_at": bundle["retrieved_at"]}
            for index, row in enumerate(rows)]


def latest_logs(client, entity, end_block, cutoff, limit, *, initial_span=50000, max_queries=96):
    """Etherscan logs have no documented desc sort: scan newest ranges first.

    A full response is subdivided, never misinterpreted as the newest page.
    Single-block overflow is paged completely before selecting the newest rows.
    """
    selected, requests = [], []
    queries = 0

    def fetch(low, high):
        nonlocal queries
        if len(selected) >= limit:
            return
        rows = []
        page = 1
        while True:
            queries += 1
            if queries > max_queries:
                raise CollectionError("token_recent_log_scan_budget_exhausted")
            bundle = client.request("logs", "getLogs", address=entity, fromBlock=low, toBlock=high,
                                    page=page, offset=1000)
            raw = bundle["response"]["result"] or []
            if len(raw) > 1000:
                raise CollectionError("token_recent_log_page_size_exceeded")
            for row in raw:
                block, stamp = integer(row.get("blockNumber")), integer(row.get("timeStamp"))
                if (address(row.get("address")) != entity or block is None or not low <= block <= high
                        or stamp is not None and stamp > cutoff):
                    raise CollectionError("token_recent_log_outside_cutoff_or_emitter")
            requests.append(bundle["request_id"])
            if len(raw) == 1000 and low < high:
                middle = (low + high) // 2
                fetch(middle + 1, high)
                fetch(low, middle)
                return
            rows.extend(_lineage(raw, bundle, "getLogs"))
            if len(raw) < 1000:
                break
            page += 1
            if page > 16:
                raise CollectionError("token_recent_single_block_log_budget_exhausted")
        identities = [(r.get("transactionHash"), integer(r.get("logIndex"))) for r in rows]
        if len(set(identities)) != len(identities):
            raise CollectionError("token_recent_duplicate_log_identity")
        rows.sort(key=lambda r: (integer(r["blockNumber"]), integer(r.get("logIndex"), default=-1)), reverse=True)
        selected.extend(rows[:limit - len(selected)])

    high, span = end_block, initial_span
    while high >= 0 and len(selected) < limit:
        low = max(0, high - span + 1)
        fetch(low, high)
        high, span = low - 1, min(span * 2, 2000000)
    return selected, {"request_ids": requests, "history_exhausted": high < 0 and len(selected) < limit}


def recent_account(client, entity, action, end_block, cutoff, rows, pages):
    retained, requests, exhausted = [], [], False
    previous = end_block
    for page in range(1, pages + 1):
        bundle = client.request("account", action, address=entity, startblock=0, endblock=end_block,
                                sort="desc", page=page, offset=rows)
        raw = bundle["response"]["result"] or []
        if len(raw) > rows:
            raise CollectionError("token_recent_account_page_size_exceeded")
        for row in raw:
            block, stamp = integer(row.get("blockNumber")), integer(row.get("timeStamp"))
            participants = {address(row.get("from")), address(row.get("to")), address(row.get("contractAddress"))}
            if block is None or not 0 <= block <= previous or stamp is None or stamp > cutoff or entity not in participants:
                raise CollectionError("token_recent_account_outside_cutoff_or_order")
            previous = block
        retained.extend(_lineage(raw, bundle, action))
        requests.append(bundle["request_id"])
        if len(raw) < rows:
            exhausted = True
            break
    return retained, {"request_ids": requests, "history_exhausted": exhausted}


def collect_token_recent(target, out, graph, settings=None):
    """Increase bounded histories until a graph budget, source end or page cap.

    Coverage complete means this bounded recipe completed, never full history.
    Normalization errors are preserved and fail the sample, rather than silently
    changing provider facts. Outputs are lossless normalized replay records.
    """
    out, settings = Path(out), dict(settings or {})
    scope = token_scope(target)
    if graph["sampling_mode"] != TOKEN_RECENT_SAMPLING:
        raise ValueError("token_recent_requires_versioned_sampling_mode")
    client = EtherscanClient(out, settings)
    client.settings["logical_query_progress"] = True
    client.on_progress = settings.get("on_progress")
    emitters = sorted({target["target"], *target["pools"]})
    maximum = graph["pages_per_action"]
    rows_per_action = graph["rows_per_action"]
    if not 1 <= rows_per_action <= 1000 or not 1 <= maximum <= 10:
        raise ValueError("invalid_token_recent_rows_or_pages")
    for round_number in range(1, maximum + 1):
        raw, sources = [], []
        for entity in emitters:
            for action in ("getLogs", "txlist", "txlistinternal"):
                if client.on_progress:
                    client.on_progress({"phase": f"round {round_number}/{maximum} {action}"})
                if action == "getLogs":
                    rows, evidence = latest_logs(client, entity, target["cutoff_block"], target["cutoff"],
                        rows_per_action * round_number, initial_span=int(settings.get("log_initial_span", 50000)),
                        max_queries=int(settings.get("log_scan_queries", 96)))
                else:
                    rows, evidence = recent_account(client, entity, action, target["cutoff_block"], target["cutoff"],
                                                     rows_per_action, round_number)
                raw.extend(rows)
                sources.append({"address": entity, "action": action, "complete": True, "gaps": [],
                                "start_block": 0, "end_block": target["cutoff_block"], "rows": len(rows), **evidence})
        # Some RPC-style provider logs omit timestamps. Hydrate by block using
        # the normal cached Etherscan header endpoint, retaining exact lineage.
        for row in raw:
            if integer(row.get("timeStamp")) is None:
                header = client.block(integer(row["blockNumber"]))["response"]["result"]
                row["timeStamp"] = str(integer(header["timestamp"]))
                if integer(row["timeStamp"]) > target["cutoff"]:
                    raise CollectionError("token_recent_hydrated_event_after_cutoff")
        events, audit = normalize_records(raw, known_entities={p: "pool" for p in target["pools"]})
        save_json(out / "normalization_audit.json", audit)
        if not audit["complete"]:
            raise CollectionError("token_recent_normalization_failed_see_audit")
        coverage = {"complete": True, "scope_version": TOKEN_RECENT_SCOPE_VERSION, "scope_sha256": scope["sha256"],
                    "required_emitters": emitters, "start_timestamp": target["cutoff"] - graph["window_days"] * 86400,
                    "end_timestamp": target["cutoff"], "start_block": 0, "end_block": target["cutoff_block"],
                    "full_history_complete": False, "neighborhood_history_complete": False,
                    "sampling": sampling_recipe(graph), "stop_reason": "record_budget_reached",
                    "rounds_used": round_number, "sources": sources}
        scoped = {**target, "coverage": coverage}
        preview = build_graph_sample(scoped, events, **graph)
        if (len(preview["node_refs"]) >= graph["max_nodes"]
                or len(preview["edge_index"][0]) >= graph["max_edges"]):
            coverage["stop_reason"] = "graph_budget_reached"
            break
        if all(source["history_exhausted"] for source in sources):
            coverage["stop_reason"] = "source_exhausted"
            break
    write_records(out / "events.jsonl.gz", events)
    save_json(out / "target.json", scoped)
    save_json(out / "coverage.json", coverage)
    final = build_graph_sample(scoped, events, **graph)
    # Empty or invalid graphs are an auditable sample failure, never invented.
    if not graph_is_usable(final):
        raise CollectionError("token_recent_unusable_graph:" + final["quality"]["status"])
    return {"event_count": len(events), "coverage": coverage, "request_count": client.request_count,
            "cached_request_count": client.cached_count}
