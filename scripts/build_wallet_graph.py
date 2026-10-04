#!/usr/bin/env python3
"""Build cutoff-bounded wallet-pool-token graphs for a frozen split manifest.

The builder keeps one local graph per target token. Wallet identity comes from
the canonical ``swap_sender`` field; optional participant fields contribute
role coverage but are never used to impute a missing sender. Incomplete target
graphs are retained in ``graph_quality.jsonl`` and excluded from ``graphs.jsonl``.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.participant_fields import normalize_address  # noqa: E402


GRAPH_VERSION = "wallet-graph-input-0.1"
EVENT_SCHEMA_VERSION = "week1-events-0.2"
NODE_FEATURE_NAMES = [
    "node_type_center",
    "node_type_pool",
    "node_type_wallet",
    "log1p_event_count",
    "log1p_swap_count",
    "log1p_mint_count",
    "log1p_burn_count",
    "log1p_positive_volume_usd",
    "active_day_fraction",
    "log1p_degree",
    "log1p_connected_pool_count",
    "sender_role_fraction",
    "recipient_role_fraction",
    "transaction_from_role_fraction",
    "missing_amount_fraction",
    "protocol_v2",
    "protocol_v3",
    "pool_age_years",
]
EDGE_FEATURE_NAMES = [
    "relation_contains_token",
    "relation_swap_activity",
    "log1p_swap_count",
    "log1p_positive_volume_usd",
    "active_day_fraction",
    "first_swap_offset_fraction",
    "last_swap_offset_fraction",
    "sender_role_fraction",
    "recipient_role_fraction",
    "transaction_from_role_fraction",
    "missing_amount_fraction",
]


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


def lower(value: Any) -> str:
    return str(value or "").strip().lower()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def positive_amount(value: Any) -> tuple[Decimal | None, str]:
    if value is None or value == "":
        return None, "missing"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, "invalid"
    if not amount.is_finite():
        return None, "invalid"
    if amount <= 0:
        return None, "nonpositive"
    return amount, "positive"


def decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def nonnegative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def positive_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed > 0 else 0.0


def log1p(value: Any) -> float:
    return math.log1p(max(positive_float(value), 0.0))


def fraction(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def protocol_flags(protocols: Iterable[str]) -> tuple[float, float]:
    values = {lower(value) for value in protocols}
    return float("uniswap_v2" in values), float("uniswap_v3" in values)


def normalise_targets(rows: list[dict[str, Any]], source: Path) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows:
        row = dict(raw)
        row["token_address"] = lower(row.get("token_address"))
        row["source_dataset"] = str(row.get("source_dataset") or "")
        row["partition"] = str(row.get("partition") or "")
        if row["partition"] not in {"train", "validation", "test"}:
            raise ValueError(f"{source}: invalid target partition: {row['partition']!r}")
        if not row["token_address"] or not row["source_dataset"]:
            raise ValueError(f"{source}: target has no canonical key: {raw}")
        if parse_time(row.get("t0")) is None or parse_time(row.get("cutoff")) is None:
            raise ValueError(f"{source}: target has incomplete time bounds: {raw}")
        key = (row["token_address"], row["source_dataset"])
        if key in seen:
            raise ValueError(f"{source}: duplicate target key: {key}")
        seen.add(key)
        row["graph_role"] = "test_holdout" if row["partition"] == "test" else "development"
        targets.append(row)
    return targets


def selected_pools(
    target: dict[str, Any],
    rows: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    token = lower(target["token_address"])
    cutoff = parse_time(target["cutoff"])
    if cutoff is None:
        raise ValueError(f"missing cutoff for {token}")
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    quality = Counter()
    for raw in rows:
        pool_address = lower(raw.get("pool_address"))
        protocol = lower(raw.get("protocol"))
        token0 = lower(raw.get("token0"))
        token1 = lower(raw.get("token1"))
        creation = parse_time(raw.get("creation_timestamp"))
        if raw.get("pool_scope_complete") is not True:
            quality["pool_scope_incomplete_rows"] += 1
            continue
        if not pool_address or not protocol or not token0 or not token1 or creation is None:
            quality["invalid_pool_rows"] += 1
            continue
        if creation > cutoff:
            quality["post_cutoff_pools_excluded"] += 1
            continue
        if token not in {token0, token1} or token0 == token1:
            quality["invalid_pool_rows"] += 1
            continue
        key = (protocol, pool_address)
        candidate = {
            "pool_address": pool_address,
            "protocol": protocol,
            "token0": token0,
            "token1": token1,
            "creation_timestamp": creation.isoformat().replace("+00:00", "Z"),
        }
        previous = selected.get(key)
        if previous is not None and (
            previous["token0"], previous["token1"]
        ) != (token0, token1):
            raise ValueError(f"conflicting pool identity for {token}/{protocol}/{pool_address}")
        selected[key] = candidate
    quality["selected_pool_count"] = len(selected)
    return [selected[key] for key in sorted(selected)], dict(quality)


def _empty_edge(key: tuple[str, str, str]) -> dict[str, Any]:
    protocol, pool_address, wallet_address = key
    return {
        "protocol": protocol,
        "pool_address": pool_address,
        "wallet_address": wallet_address,
        "swap_count": 0,
        "positive_volume_usd": Decimal("0"),
        "positive_amount_count": 0,
        "missing_amount_usd_count": 0,
        "nonpositive_amount_usd_count": 0,
        "active_day_dates": set(),
        "first_timestamp": None,
        "last_timestamp": None,
        "sender_role_count": 0,
        "recipient_role_count": 0,
        "transaction_from_role_count": 0,
        "recipient_present_count": 0,
        "transaction_from_present_count": 0,
        "event_ids": set(),
    }


def aggregate_wallet_edges(
    target: dict[str, Any],
    events: Iterable[dict[str, Any]],
    pools: list[dict[str, Any]],
    *,
    pool_scope_complete: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate sender-wallet activity in the target's inclusive cutoff window."""
    token = lower(target["token_address"])
    source = str(target["source_dataset"])
    t0 = parse_time(target["t0"])
    cutoff = parse_time(target["cutoff"])
    if t0 is None or cutoff is None:
        raise ValueError(f"missing target bounds for {token}")
    pool_keys = {(pool["protocol"], pool["pool_address"]) for pool in pools}
    aggregates: dict[tuple[str, str, str], dict[str, Any]] = {}
    quality = Counter()

    for raw in events:
        if lower(raw.get("token_address")) != token or str(raw.get("source_dataset") or "") != source:
            continue
        if lower(raw.get("event_type")) != "swap":
            continue
        timestamp = parse_time(raw.get("block_timestamp"))
        if timestamp is None:
            quality["missing_swap_timestamp"] += 1
            continue
        if timestamp < t0:
            quality["pre_t0_swaps_excluded"] += 1
            continue
        if timestamp > cutoff:
            quality["post_cutoff_swaps_excluded"] += 1
            continue
        quality["swap_events_in_window"] += 1
        protocol = lower(raw.get("protocol"))
        pool_address = lower(raw.get("pool_address"))
        if (protocol, pool_address) not in pool_keys:
            quality["out_of_scope_swaps_excluded"] += 1
            continue
        quality["in_scope_swap_events"] += 1
        recipient = normalize_address(raw.get("swap_recipient"))
        transaction_from = normalize_address(raw.get("transaction_from"))
        if recipient is None:
            quality["missing_swap_recipient"] += 1
        if transaction_from is None:
            quality["missing_transaction_from"] += 1
        event_id = str(raw.get("event_id") or "")
        if not event_id:
            quality["missing_event_id"] += 1
        sender = normalize_address(raw.get("swap_sender"))
        if sender is None:
            quality["missing_swap_sender"] += 1
            continue
        quality["swap_events_with_sender"] += 1
        key = (protocol, pool_address, sender)
        current = aggregates.setdefault(key, _empty_edge(key))
        current["swap_count"] += 1
        current["active_day_dates"].add(timestamp.date().isoformat())
        current["first_timestamp"] = min(
            filter(None, (current["first_timestamp"], timestamp)), default=timestamp
        )
        current["last_timestamp"] = max(
            filter(None, (current["last_timestamp"], timestamp)), default=timestamp
        )
        amount, amount_status = positive_amount(raw.get("amount_usd"))
        if amount is None:
            if amount_status == "nonpositive":
                current["nonpositive_amount_usd_count"] += 1
            else:
                current["missing_amount_usd_count"] += 1
        else:
            current["positive_volume_usd"] += amount
            current["positive_amount_count"] += 1
        current["sender_role_count"] += 1
        if recipient is not None:
            current["recipient_present_count"] += 1
            if recipient == sender:
                current["recipient_role_count"] += 1
        if transaction_from is not None:
            current["transaction_from_present_count"] += 1
            if transaction_from == sender:
                current["transaction_from_role_count"] += 1
        if event_id:
            current["event_ids"].add(event_id)

    edge_rows: list[dict[str, Any]] = []
    for key in sorted(aggregates):
        current = aggregates[key]
        first = current["first_timestamp"]
        last = current["last_timestamp"]
        edge_rows.append(
            {
                "token_address": token,
                "source_dataset": source,
                "partition": target["partition"],
                "graph_version": GRAPH_VERSION,
                "target_t0": target["t0"],
                "target_cutoff": target["cutoff"],
                "protocol": current["protocol"],
                "pool_address": current["pool_address"],
                "wallet_address": current["wallet_address"],
                "swap_count": current["swap_count"],
                "positive_volume_usd": decimal_text(
                    current["positive_volume_usd"] if current["positive_amount_count"] else None
                ),
                "positive_amount_count": current["positive_amount_count"],
                "missing_amount_usd_count": current["missing_amount_usd_count"],
                "nonpositive_amount_usd_count": current["nonpositive_amount_usd_count"],
                "volume_usd_available": current["positive_amount_count"] > 0,
                "active_day_count": len(current["active_day_dates"]),
                "active_day_dates": sorted(current["active_day_dates"]),
                "first_swap_timestamp": first.isoformat().replace("+00:00", "Z") if first else None,
                "last_swap_timestamp": last.isoformat().replace("+00:00", "Z") if last else None,
                "first_swap_offset_days": (first - t0).total_seconds() / 86400 if first else None,
                "last_swap_offset_days": (last - t0).total_seconds() / 86400 if last else None,
                "sender_role_count": current["sender_role_count"],
                "recipient_role_count": current["recipient_role_count"],
                "transaction_from_role_count": current["transaction_from_role_count"],
                "recipient_present_count": current["recipient_present_count"],
                "transaction_from_present_count": current["transaction_from_present_count"],
                "event_ids": sorted(current["event_ids"]),
                "event_id_count": len(current["event_ids"]),
            }
        )

    quality.update(
        {
            "pool_scope_complete": bool(pool_scope_complete),
            "selected_pool_count": len(pools),
            "wallet_edge_count": len(edge_rows),
        }
    )
    for field in (
        "missing_swap_sender",
        "missing_swap_recipient",
        "missing_transaction_from",
        "missing_swap_timestamp",
        "missing_event_id",
    ):
        quality[field] = int(quality.get(field, 0))
    quality["participant_sender_coverage"] = fraction(
        quality["swap_events_with_sender"], quality["in_scope_swap_events"]
    )
    quality["model_ready"] = bool(
        pool_scope_complete
        and quality["selected_pool_count"] > 0
        and quality["missing_swap_sender"] == 0
        and quality["missing_swap_timestamp"] == 0
        and quality["missing_event_id"] == 0
    )
    if not pool_scope_complete:
        quality["status"] = "pool_scope_incomplete"
    elif quality["selected_pool_count"] == 0:
        quality["status"] = "no_selected_pools"
    elif quality["missing_swap_sender"]:
        quality["status"] = "missing_swap_sender"
    elif quality["missing_swap_timestamp"]:
        quality["status"] = "missing_swap_timestamp"
    elif quality["missing_event_id"]:
        quality["status"] = "missing_event_id"
    else:
        quality["status"] = "complete"
    return edge_rows, dict(quality)


def _pool_event_stats(
    target: dict[str, Any],
    events: Iterable[dict[str, Any]],
    pools: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    t0 = parse_time(target["t0"])
    cutoff = parse_time(target["cutoff"])
    if t0 is None or cutoff is None:
        raise ValueError("missing target bounds")
    pool_keys = {(pool["protocol"], pool["pool_address"]) for pool in pools}
    stats: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "event_count": 0,
            "swap_count": 0,
            "mint_count": 0,
            "burn_count": 0,
            "positive_volume_usd": Decimal("0"),
            "positive_amount_count": 0,
            "active_days": set(),
        }
    )
    for raw in events:
        timestamp = parse_time(raw.get("block_timestamp"))
        key = (lower(raw.get("protocol")), lower(raw.get("pool_address")))
        if timestamp is None or not (t0 <= timestamp <= cutoff) or key not in pool_keys:
            continue
        current = stats[key]
        current["event_count"] += 1
        event_type = lower(raw.get("event_type"))
        if event_type == "swap":
            current["swap_count"] += 1
            amount, _ = positive_amount(raw.get("amount_usd"))
            if amount is not None:
                current["positive_volume_usd"] += amount
                current["positive_amount_count"] += 1
        elif event_type == "mint":
            current["mint_count"] += 1
        elif event_type == "burn":
            current["burn_count"] += 1
        current["active_days"].add(timestamp.date().isoformat())
    return stats


def _edge_feature_row(edge: dict[str, Any]) -> list[float]:
    swap_count = nonnegative_int(edge["swap_count"])
    active_days = nonnegative_int(edge["active_day_count"])
    first_offset = positive_float(edge.get("first_swap_offset_days"))
    last_offset = positive_float(edge.get("last_swap_offset_days"))
    recipient_roles = nonnegative_int(edge.get("recipient_role_count"))
    caller_roles = nonnegative_int(edge.get("transaction_from_role_count"))
    missing_amounts = nonnegative_int(edge.get("missing_amount_usd_count"))
    return [
        0.0,
        1.0,
        log1p(swap_count),
        log1p(positive_float(edge.get("positive_volume_usd"))),
        min(active_days / 7.0, 1.0),
        min(first_offset / 7.0, 1.0),
        min(last_offset / 7.0, 1.0),
        fraction(1, swap_count),
        fraction(recipient_roles, swap_count),
        fraction(caller_roles, swap_count),
        fraction(missing_amounts, swap_count),
    ]


def _node_features(
    *,
    kind: str,
    event_count: int = 0,
    swap_count: int = 0,
    mint_count: int = 0,
    burn_count: int = 0,
    positive_volume_usd: Any = None,
    active_day_count: int = 0,
    degree: int = 0,
    connected_pool_count: int = 0,
    sender_role_count: int = 0,
    recipient_role_count: int = 0,
    transaction_from_role_count: int = 0,
    missing_amount_usd_count: int = 0,
    pool_age_years: float = 0.0,
    protocols: Iterable[str] = (),
) -> list[float]:
    v2, v3 = protocol_flags(protocols)
    return [
        float(kind == "center"),
        float(kind == "pool"),
        float(kind == "wallet"),
        log1p(event_count),
        log1p(swap_count),
        log1p(mint_count),
        log1p(burn_count),
        log1p(positive_float(positive_volume_usd)),
        min(nonnegative_int(active_day_count) / 7.0, 1.0),
        log1p(degree),
        log1p(connected_pool_count),
        fraction(sender_role_count, swap_count),
        fraction(recipient_role_count, swap_count),
        fraction(transaction_from_role_count, swap_count),
        fraction(missing_amount_usd_count, swap_count),
        v2,
        v3,
        min(max(pool_age_years, 0.0), 20.0),
    ]


def wallet_graph_for_target(
    target: dict[str, Any],
    pools: list[dict[str, Any]],
    edge_rows: list[dict[str, Any]],
    events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Create a deterministic token/pool/wallet graph with local node ids."""
    token = lower(target["token_address"])
    cutoff = parse_time(target["cutoff"])
    if cutoff is None:
        raise ValueError(f"missing cutoff for {token}")
    pool_stats = _pool_event_stats(target, events, pools)
    wallets = sorted({row["wallet_address"] for row in edge_rows})
    pool_keys = [(pool["protocol"], pool["pool_address"]) for pool in pools]
    pool_index = {key: index for index, key in enumerate(pool_keys, start=1)}
    wallet_start = 1 + len(pools)
    wallet_index = {wallet: wallet_start + index for index, wallet in enumerate(wallets)}

    nodes: list[dict[str, Any]] = [{"kind": "center", "id": token, "protocol": None}]
    features: list[list[float]] = [
        _node_features(
            kind="center",
            event_count=nonnegative_int(target.get("event_count")),
            swap_count=nonnegative_int(target.get("swap_count")),
            mint_count=nonnegative_int(target.get("mint_count")),
            burn_count=nonnegative_int(target.get("burn_count")),
            positive_volume_usd=target.get("pre_cutoff_volume_usd"),
            active_day_count=nonnegative_int(target.get("active_day_count")),
            degree=len(pools),
            connected_pool_count=len(pools),
            protocols=[pool["protocol"] for pool in pools],
        )
    ]

    for pool in pools:
        key = (pool["protocol"], pool["pool_address"])
        stats = pool_stats.get(key, {})
        pool_wallets = [row for row in edge_rows if (row["protocol"], row["pool_address"]) == key]
        creation = parse_time(pool["creation_timestamp"])
        age_years = ((cutoff - creation).total_seconds() / (365.25 * 86400)) if creation else 0.0
        nodes.append({"kind": "pool", "id": pool["pool_address"], "protocol": pool["protocol"]})
        features.append(
            _node_features(
                kind="pool",
                event_count=stats.get("event_count", 0),
                swap_count=stats.get("swap_count", 0),
                mint_count=stats.get("mint_count", 0),
                burn_count=stats.get("burn_count", 0),
                positive_volume_usd=decimal_text(
                    stats.get("positive_volume_usd") if stats.get("positive_amount_count") else None
                ),
                active_day_count=len(stats.get("active_days", set())),
                degree=1 + len(pool_wallets),
                connected_pool_count=len(pool_wallets),
                pool_age_years=age_years,
                protocols=[pool["protocol"]],
            )
        )

    wallet_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "swap_count": 0,
            "volume_usd": Decimal("0"),
            "volume_count": 0,
            "active_days": set(),
            "pool_count": 0,
            "sender_roles": 0,
            "recipient_roles": 0,
            "transaction_from_roles": 0,
            "missing_amounts": 0,
        }
    )
    for edge in edge_rows:
        total = wallet_totals[edge["wallet_address"]]
        total["swap_count"] += nonnegative_int(edge["swap_count"])
        if edge.get("positive_volume_usd") is not None:
            total["volume_usd"] += Decimal(str(edge["positive_volume_usd"]))
            total["volume_count"] += nonnegative_int(edge.get("positive_amount_count"))
        total["active_days"].update(edge.get("active_day_dates") or [])
        total["pool_count"] += 1
        total["sender_roles"] += nonnegative_int(edge.get("sender_role_count"))
        total["recipient_roles"] += nonnegative_int(edge.get("recipient_role_count"))
        total["transaction_from_roles"] += nonnegative_int(edge.get("transaction_from_role_count"))
        total["missing_amounts"] += nonnegative_int(edge.get("missing_amount_usd_count"))

    for wallet in wallets:
        total = wallet_totals[wallet]
        nodes.append({"kind": "wallet", "id": wallet, "protocol": None})
        features.append(
            _node_features(
                kind="wallet",
                swap_count=total["swap_count"],
                positive_volume_usd=decimal_text(total["volume_usd"] if total["volume_count"] else None),
                active_day_count=len(total["active_days"]),
                degree=total["pool_count"],
                connected_pool_count=total["pool_count"],
                sender_role_count=total["sender_roles"],
                recipient_role_count=total["recipient_roles"],
                transaction_from_role_count=total["transaction_from_roles"],
                missing_amount_usd_count=total["missing_amounts"],
            )
        )

    sources: list[int] = []
    destinations: list[int] = []
    edge_features: list[list[float]] = []
    edge_refs: list[dict[str, Any]] = []

    def add_edge(source: int, destination: int, relation: str, features_row: list[float], ref: dict[str, Any]) -> None:
        sources.append(source)
        destinations.append(destination)
        edge_features.append(features_row)
        edge_refs.append({"source_index": source, "destination_index": destination, "relation": relation, **ref})

    contains_features = [1.0, 0.0] + [0.0] * (len(EDGE_FEATURE_NAMES) - 2)
    for pool in pools:
        pool_key = (pool["protocol"], pool["pool_address"])
        pool_idx = pool_index[pool_key]
        ref = {"pool_address": pool["pool_address"], "protocol": pool["protocol"], "event_ids": []}
        add_edge(0, pool_idx, "contains_token", contains_features, ref)
        add_edge(pool_idx, 0, "contains_token", contains_features, ref)

    for edge in edge_rows:
        pool_idx = pool_index[(edge["protocol"], edge["pool_address"])]
        wallet_idx = wallet_index[edge["wallet_address"]]
        ref = {
            "pool_address": edge["pool_address"],
            "protocol": edge["protocol"],
            "wallet_address": edge["wallet_address"],
            "event_ids": edge["event_ids"],
        }
        features_row = _edge_feature_row(edge)
        add_edge(wallet_idx, pool_idx, "swap_activity", features_row, ref)
        add_edge(pool_idx, wallet_idx, "swap_activity", features_row, ref)

    graph = {
        "graph_version": GRAPH_VERSION,
        "token_address": token,
        "source_dataset": str(target["source_dataset"]),
        "graph_role": target["graph_role"],
        "partition": target["partition"],
        "label": target.get("label"),
        "t0": target.get("t0"),
        "cutoff": target.get("cutoff"),
        "node_features": features,
        "node_feature_names": NODE_FEATURE_NAMES,
        "node_refs": nodes,
        "edge_index": [sources, destinations],
        "edge_features": edge_features,
        "edge_feature_names": EDGE_FEATURE_NAMES,
        "edge_refs": edge_refs,
        "stats": {
            "pool_count": len(pools),
            "wallet_count": len(wallets),
            "node_count": len(nodes),
            "edge_count": len(sources),
            "wallet_pool_edge_count": len(edge_rows),
            "window_swap_count": sum(nonnegative_int(row["swap_count"]) for row in edge_rows),
        },
    }
    validate_graph(graph)
    return graph


def validate_graph(graph: dict[str, Any]) -> None:
    features = graph["node_features"]
    refs = graph["node_refs"]
    edge_index = graph["edge_index"]
    if len(features) != len(refs):
        raise ValueError("node feature/reference length mismatch")
    if len(edge_index) != 2 or len(edge_index[0]) != len(edge_index[1]):
        raise ValueError("edge index must contain two equal-length rows")
    if len(edge_index[0]) != len(graph["edge_features"]) or len(edge_index[0]) != len(graph["edge_refs"]):
        raise ValueError("edge metadata length mismatch")
    if len(features) == 0 or refs[0]["kind"] != "center":
        raise ValueError("node zero must be the target center")
    if any(index < 0 or index >= len(features) for row in edge_index for index in row):
        raise ValueError("edge index points outside node feature matrix")
    if any(len(row) != len(NODE_FEATURE_NAMES) for row in features):
        raise ValueError("node feature width mismatch")
    if any(len(row) != len(EDGE_FEATURE_NAMES) for row in graph["edge_features"]):
        raise ValueError("edge feature width mismatch")
    if any(not math.isfinite(float(value)) for row in features for value in row):
        raise ValueError("non-finite node feature")
    if any(not math.isfinite(float(value)) for row in graph["edge_features"] for value in row):
        raise ValueError("non-finite edge feature")


def _target_table(connection: Any, targets: list[dict[str, Any]]) -> None:
    connection.execute("DROP TABLE IF EXISTS wallet_graph_targets")
    connection.execute(
        "CREATE TEMP TABLE wallet_graph_targets(token_address VARCHAR, source_dataset VARCHAR, t0 TIMESTAMPTZ, cutoff TIMESTAMPTZ, partition VARCHAR, label VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO wallet_graph_targets VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                row["token_address"],
                row["source_dataset"],
                parse_time(row["t0"]),
                parse_time(row["cutoff"]),
                row["partition"],
                row.get("label"),
            )
            for row in targets
        ],
    )


def _rows(connection: Any, query: str) -> list[dict[str, Any]]:
    result = connection.execute(query)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def _empty_outputs(output: Path) -> None:
    write_jsonl(output / "graphs.jsonl", [])
    write_jsonl(output / "wallet_graph_edges.jsonl", [])
    write_jsonl(output / "graph_quality.jsonl", [])
    write_json(output / "feature_schema.json", {"node_feature_names": NODE_FEATURE_NAMES})
    write_json(output / "edge_schema.json", {"edge_feature_names": EDGE_FEATURE_NAMES})


def build(args: argparse.Namespace) -> dict[str, Any]:
    import duckdb

    database = Path(args.database).resolve()
    targets_path = Path(args.targets).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    targets = normalise_targets(read_jsonl(targets_path), targets_path)
    connection = duckdb.connect(str(database), read_only=True)
    try:
        event_columns = {str(row[0]) for row in connection.execute("DESCRIBE normalized_events").fetchall()}
        required_columns = {"swap_sender", "swap_recipient", "transaction_from"}
        missing_columns = sorted(required_columns - event_columns)
        if missing_columns:
            _empty_outputs(output)
            write_jsonl(
                output / "graph_quality.jsonl",
                [
                    {
                        "graph_version": GRAPH_VERSION,
                        "token_address": row["token_address"],
                        "source_dataset": row["source_dataset"],
                        "partition": row["partition"],
                        "status": "blocked_missing_participant_columns",
                        "model_ready": False,
                        "missing_normalized_event_columns": missing_columns,
                    }
                    for row in targets
                ],
            )
            manifest = {
                "manifest_version": GRAPH_VERSION,
                "status": "blocked_missing_participant_columns",
                "database": str(database),
                "targets": str(targets_path),
                "output": str(output),
                "source_schema_version": EVENT_SCHEMA_VERSION,
                "missing_normalized_event_columns": missing_columns,
                "target_rows": len(targets),
                "quality_rows": len(targets),
                "model_ready_graphs": 0,
                "decision": "Rebuild the normalized data product from participant-aware source collections before graph construction.",
            }
            write_json(output / "graph_manifest.json", manifest)
            return manifest

        _target_table(connection, targets)
        pool_rows = _rows(
            connection,
            """
            SELECT p.token_address, p.source_dataset, p.pool_address, p.protocol,
                   p.token0, p.token1, p.creation_timestamp, p.pool_scope_complete
            FROM pool_entities p
            JOIN wallet_graph_targets t USING (token_address, source_dataset)
            ORDER BY p.token_address, p.source_dataset, p.protocol, p.pool_address
            """,
        )
        scope_rows = _rows(
            connection,
            """
            SELECT t.token_address, t.source_dataset, COALESCE(bool_and(COALESCE(p.pool_scope_complete, FALSE)), FALSE) AS pool_scope_complete
            FROM wallet_graph_targets t
            LEFT JOIN pool_entities p USING (token_address, source_dataset)
            GROUP BY t.token_address, t.source_dataset
            """,
        )
        event_rows = _rows(
            connection,
            """
            SELECT e.token_address, e.source_dataset, e.protocol, e.pool_address,
                   e.event_type, e.event_id, e.block_timestamp, e.amount_usd,
                   e.swap_sender, e.swap_recipient, e.transaction_from
            FROM normalized_events e
            JOIN wallet_graph_targets t USING (token_address, source_dataset)
            ORDER BY e.token_address, e.source_dataset, e.block_timestamp, e.event_id
            """,
        )
    finally:
        connection.close()

    pools_by_target: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in pool_rows:
        pools_by_target[(lower(row["token_address"]), str(row["source_dataset"]))].append(row)
    events_by_target: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        events_by_target[(lower(row["token_address"]), str(row["source_dataset"]))].append(row)
    scope_by_target = {
        (lower(row["token_address"]), str(row["source_dataset"])): bool(row["pool_scope_complete"])
        for row in scope_rows
    }

    graph_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    for target in targets:
        key = (target["token_address"], target["source_dataset"])
        pools, pool_quality = selected_pools(target, pools_by_target.get(key, []))
        edges, quality = aggregate_wallet_edges(
            target,
            events_by_target.get(key, []),
            pools,
            pool_scope_complete=scope_by_target.get(key, False),
        )
        quality_row = {
            "graph_version": GRAPH_VERSION,
            "token_address": target["token_address"],
            "source_dataset": target["source_dataset"],
            "partition": target["partition"],
            **pool_quality,
            **quality,
        }
        quality_rows.append(quality_row)
        for edge in edges:
            edge_rows.append({**edge, "model_ready": quality["model_ready"], "quality_status": quality["status"]})
        if quality["model_ready"]:
            graph_rows.append(wallet_graph_for_target(target, pools, edges, events_by_target.get(key, [])))

    write_jsonl(output / "graphs.jsonl", graph_rows)
    write_jsonl(output / "wallet_graph_edges.jsonl", edge_rows)
    write_jsonl(output / "graph_quality.jsonl", quality_rows)
    write_json(output / "feature_schema.json", {"node_feature_names": NODE_FEATURE_NAMES})
    write_json(output / "edge_schema.json", {"edge_feature_names": EDGE_FEATURE_NAMES})

    status_counts = Counter(str(row["status"]) for row in quality_rows)
    manifest = {
        "manifest_version": GRAPH_VERSION,
        "status": "complete" if len(graph_rows) == len(targets) else "partial_incomplete_targets",
        "database": str(database),
        "targets": str(targets_path),
        "output": str(output),
        "source_schema_version": EVENT_SCHEMA_VERSION,
        "target_rows": len(targets),
        "model_ready_graphs": len(graph_rows),
        "excluded_graphs": len(targets) - len(graph_rows),
        "wallet_graph_edge_rows": len(edge_rows),
        "quality_status_counts": dict(sorted(status_counts.items())),
        "partition_counts": dict(sorted(Counter(row["partition"] for row in graph_rows).items())),
        "participant_policy": {
            "wallet_identity": "swap_sender",
            "missing_swap_sender": "exclude_target_graph_and_record_quality_row",
            "missing_swap_recipient": "retain_graph_and_record_role_coverage",
            "missing_transaction_from": "retain_graph_and_record_role_coverage",
            "missing_amount_usd": "retain_graph_with_explicit_volume_quality_fields",
        },
        "split_isolation": {
            "one_local_graph_per_target": True,
            "learned_wallet_state_shared_across_graphs": False,
            "target_keys_unique": len({(row["token_address"], row["source_dataset"]) for row in targets}) == len(targets),
        },
        "outputs": {
            "graphs": str(output / "graphs.jsonl"),
            "wallet_graph_edges": str(output / "wallet_graph_edges.jsonl"),
            "graph_quality": str(output / "graph_quality.jsonl"),
        },
    }
    write_json(output / "graph_manifest.json", manifest)
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--database", required=True)
    result.add_argument("--targets", required=True)
    result.add_argument("--output", required=True)
    return result


if __name__ == "__main__":
    print(json.dumps(build(parser().parse_args()), indent=2, sort_keys=True))
