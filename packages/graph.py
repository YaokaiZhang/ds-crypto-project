"""Cutoff-bounded Scam graphs and label-free tensor conversion.

The JSON protocol retains original directed edges. Reverse *message* edges are
created only when batching, with separate relation IDs and shared provenance.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .token import (TOKEN_TASKS, TOKEN_VIEW_VERSION, TOKEN_SCOPE_VERSION,
    TOKEN_NODE_FEATURES, TOKEN_EDGE_FEATURES, token_scope,
    token_coverage_complete, annotate_token_events, mechanism_features)

SCHEMA_VERSION = "chainrisk-graph-1.0"
GRAPH_VIEW_VERSION = "scam-egonet-1.0"
RELATION_NAMES = [
    "external_eth", "internal_eth", "call", "failed_call", "erc20_transfer",
    "lp_transfer", "swap", "mint", "burn", "sync", "pair_created", "contains", "deployed", "participates",
]
FEATURE_NAMES = [
    "is_root", "role_token", "role_pool", "role_deployer", "role_lp",
    "log_in_events", "log_out_events", "log_in_degree", "log_out_degree",
    "log_native_in", "log_native_out", "log_target_token_in", "log_target_token_out",
    "amount_missing_fraction", "failed_fraction", "success_missing_fraction",
    "oldest_age", "newest_age", "mean_age", "log_calls",
]
EDGE_FEATURE_NAMES = [
    "log_event_count", "log_amount", "amount_missing_fraction", "oldest_age",
    "newest_age", "mean_age", "failed_fraction", "success_missing_fraction",
    "asset_native", "asset_target_token", "asset_other",
]
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_MONEY_RELATIONS = {"external_eth", "internal_eth", "erc20_transfer", "lp_transfer"}
_NODE_UNSCALED = set(range(5)) | {13, 14, 15}
_EDGE_UNSCALED = {2, 6, 7, 8, 9, 10}


def graph_schema(task_id: str) -> tuple[str, list[str], list[str]]:
    if task_id in TOKEN_TASKS:
        return TOKEN_VIEW_VERSION, FEATURE_NAMES + TOKEN_NODE_FEATURES, EDGE_FEATURE_NAMES + TOKEN_EDGE_FEATURES
    return GRAPH_VIEW_VERSION, list(FEATURE_NAMES), list(EDGE_FEATURE_NAMES)


def _address(value: Any) -> str:
    result = str(value).lower()
    if not _ADDRESS.fullmatch(result):
        raise ValueError(f"invalid Ethereum address: {value!r}")
    return result


def _rank(seed: int, *parts: str) -> str:
    return hashlib.sha256((str(seed) + "|" + "|".join(parts)).encode()).hexdigest()


def select_neighbor_addresses(root: str, node: str, neighbors: Iterable[str], fanout: int, seed: int = 20261008) -> list[str]:
    """Shared deterministic BFS choice for collection and graph construction."""
    if fanout < 1:
        raise ValueError("fanout must be positive")
    return sorted(set(neighbors), key=lambda other: _rank(seed, root, node, other))[:fanout]


def _amount(event: Mapping[str, Any]) -> float | None:
    """Decode an amount only when units are known; failure is never a zero."""
    if event.get("relation") not in _MONEY_RELATIONS or event.get("success") is not True:
        return None
    raw = event.get("raw_amount")
    decimals = event.get("decimals")
    if raw is None or not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 255:
        return None
    try:
        value = Decimal(str(raw)) / (Decimal(10) ** decimals)
        if not value.is_finite() or value < 0:
            return None
        decoded = float(value)
        return decoded if math.isfinite(decoded) else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _log(value: float) -> float:
    return math.log1p(max(0.0, value))


def _coverage_complete(coverage: Any, start: int, cutoff: int, sampling: Mapping[str, Any]) -> bool:
    if not isinstance(coverage, dict) or coverage.get("complete") is not True:
        return False
    covered_start = coverage.get("start_timestamp", coverage.get("observation_start", start))
    covered_end = coverage.get("end_timestamp", coverage.get("cutoff", cutoff))
    # A bounded BFS collection only covers the same deterministic neighborhood.
    # Imported full-history fixtures can omit BFS metadata; collected coverage
    # must carry all fields together and match the recipe used here.
    recipe_keys = ("hops", "fanouts", "seed", "max_nodes")
    if any(key in coverage for key in recipe_keys):
        if any(coverage.get(key) != sampling[key] for key in recipe_keys):
            return False
    return (isinstance(covered_start, int) and not isinstance(covered_start, bool)
            and isinstance(covered_end, int) and not isinstance(covered_end, bool)
            and covered_start <= start and covered_end == cutoff
            and coverage.get("neighborhood_history_complete") is not False)


@dataclass(frozen=True)
class GraphBuilder:
    """Small strategy object: topology shares mechanics, relation policy differs."""
    name: str
    task_ids: frozenset[str]
    allowed_relations: frozenset[str]

    def build(self, target: Mapping[str, Any], events: Iterable[Mapping[str, Any]], **options: Any) -> dict[str, Any]:
        if target.get("task_id") not in self.task_ids:
            raise ValueError(f"{self.name} graph strategy cannot build task {target.get('task_id')}")
        return _build_graph_sample(target, events, builder=self, **options)


GRAPH_BUILDERS = MappingProxyType({
    "address_flow": GraphBuilder("address_flow", frozenset({"phishing", "ponzi"}),
        frozenset({"external_eth", "internal_eth", "call", "failed_call", "erc20_transfer", "deployed"})),
    "token_v2": GraphBuilder("token_v2", frozenset({"honeypot", "rug_pull"}), frozenset(RELATION_NAMES)),
})
_TASK_BUILDERS = MappingProxyType({"phishing": "address_flow", "ponzi": "address_flow",
    "honeypot": "token_v2", "rug_pull": "token_v2"})


def get_graph_builder(name_or_task: str) -> GraphBuilder:
    name = _TASK_BUILDERS.get(name_or_task, name_or_task)
    try:
        return GRAPH_BUILDERS[name]
    except KeyError as error:
        raise ValueError(f"unsupported graph strategy/task: {name_or_task}") from error


def build_graph_sample(target: Mapping[str, Any], events: Iterable[Mapping[str, Any]], **options: Any) -> dict[str, Any]:
    """Select a registered strategy and build a graph without labels."""
    builder_name = options.pop("builder_name", target.get("task_id"))
    return get_graph_builder(builder_name).build(target, events, **options)


def _build_graph_sample(
    target: Mapping[str, Any], events: Iterable[Mapping[str, Any]], *,
    window_days: int = 30, hops: int = 2, fanouts: Sequence[int] = (32, 16),
    max_nodes: int = 512, max_edges: int = 4096, seed: int = 20261008, builder: GraphBuilder,
) -> dict[str, Any]:
    """Build one deterministic address graph without consulting labels.

    Token pool-membership is derived from historical events carrying token0/1
    and pool, not from today's mutable metadata. Transfer amounts of different
    assets are never summed into the same edge. Sampling is label-blind.
    """
    if window_days <= 0 or hops < 1 or len(fanouts) < hops or min(fanouts) <= 0:
        raise ValueError("positive window/hops and one positive fanout per hop required")
    if max_nodes < 1 or max_edges < 1:
        raise ValueError("positive graph budgets required")
    root = _address(target["target"])
    task = target["task_id"]
    if task not in {"phishing", "ponzi", "honeypot", "rug_pull"}:
        raise ValueError(f"unknown task_id: {task}")
    if target.get("chain_id", 1) != 1:
        raise ValueError("Scam v1 only supports Ethereum chain_id=1")
    cutoff = target["cutoff"]
    if not isinstance(cutoff, int) or isinstance(cutoff, bool):
        raise ValueError("cutoff must be an integer Unix timestamp")
    start = cutoff - window_days * 86400
    view_version, feature_names, edge_feature_names = graph_schema(task)
    scope, scope_error = None, None
    if task in TOKEN_TASKS:
        events = list(events)
        try:
            scope = token_scope(target)
            current = [row for row in events if isinstance(row.get("timestamp"), int) and start < row["timestamp"] <= cutoff]
            excluded = [row for row in events if not isinstance(row.get("timestamp"), int) or row["timestamp"] > cutoff]
            events = annotate_token_events(current, scope) + excluded
        except (ValueError, TypeError, KeyError) as exc:
            scope_error = str(exc)
            scope = None
    eligible: list[dict[str, Any]] = []
    structural: dict[tuple[str, str, str], dict[str, Any]] = {}
    seen: dict[str, dict[str, Any]] = {}
    invalid = duplicates = conflicting = future = 0
    roles: dict[str, set[str]] = defaultdict(set)
    selected_pools = {_address(value) for value in target.get("pools", [])}
    if task in {"honeypot", "rug_pull"}:
        roles[root].add("token")
    for source in events:
        row = dict(source)
        try:
            timestamp = row["timestamp"]
            if (not isinstance(timestamp, int) or isinstance(timestamp, bool)
                    or row.get("chain_id", 1) != 1 or row.get("relation") not in RELATION_NAMES):
                raise ValueError("invalid event metadata")
            row["src"], row["dst"] = _address(row["src"]), _address(row["dst"])
            if not isinstance(row.get("event_id"), str) or not row["event_id"]:
                raise ValueError("event_id required")
            if row.get("success") is not None and not isinstance(row["success"], bool):
                raise ValueError("success must be boolean or null")
            if row["relation"] not in builder.allowed_relations:
                continue
            previous = seen.get(row["event_id"])
            if previous is not None:
                # Retrieval provenance may differ, but chain facts must agree.
                fields = ("timestamp", "src", "dst", "relation", "asset", "raw_amount", "decimals", "success",
                          "amount0_in", "amount1_in", "amount0_out", "amount1_out", "amount0", "amount1",
                          "reserve0", "reserve1", "pool", "token0", "token1", "block_number", "log_index")
                if any(previous.get(key) != row.get(key) for key in fields):
                    conflicting += 1
                else:
                    duplicates += 1
                continue
            seen[row["event_id"]] = row
            if timestamp > cutoff:
                future += 1
                continue
            if scope and (not isinstance(row.get("block_number"), int) or isinstance(row["block_number"], bool)
                          or row["block_number"] < 0 or row["block_number"] > scope["cutoff_block"]):
                raise ValueError("event_outside_verified_cutoff_block")
            if task in {"honeypot", "rug_pull"} and start < timestamp <= cutoff:
                if scope and row.get("pool") in selected_pools and row["relation"] in {"swap", "mint", "burn"}:
                    pool = row["pool"]
                    for participant in {row["src"], row["dst"]} - {pool, root}:
                        key = (pool, participant, "participates")
                        context = {"event_id": "pool-participant:" + row["event_id"] + ":" + participant,
                                   "chain_id": 1, "timestamp": timestamp, "src": pool, "dst": participant,
                                   "relation": "participates", "asset": root, "raw_amount": None,
                                   "decimals": None, "success": None, "lineage": [row["event_id"]]}
                        if key not in structural or timestamp < structural[key]["timestamp"]:
                            structural[key] = context
                # Transfer endpoints are wallets, not the token contract. The
                # historical emitter/asset is evidence of participation, never
                # ownership or a malicious role.
                if row["relation"] == "erc20_transfer" and str(row.get("asset", "")).lower() == root:
                    for participant in (row["src"], row["dst"]):
                        if participant == root:
                            continue
                        key = (root, participant, "participates")
                        context = {"event_id": "participant:" + row["event_id"] + ":" + participant,
                                   "chain_id": 1, "timestamp": timestamp, "src": root, "dst": participant,
                                   "relation": "participates", "asset": root, "raw_amount": None,
                                   "decimals": None, "success": None, "lineage": [row["event_id"]]}
                        if key not in structural or timestamp < structural[key]["timestamp"]:
                            structural[key] = context
                # Explicit verified target/pool mapping plus a historical pool
                # observation remains usable when PairCreated predates the window.
                observed_pools = selected_pools.intersection({row["src"], row["dst"],
                    str(row.get("pool", "")).lower(), str(row.get("asset", "")).lower()})
                for pool in observed_pools:
                    roles[pool].update({"pool", "lp"})
                    key = (root, pool, "contains")
                    context = {"event_id": "pool-context:" + row["event_id"] + ":" + pool,
                               "chain_id": 1, "timestamp": timestamp, "src": root, "dst": pool,
                               "relation": "contains", "asset": root, "raw_amount": None,
                               "decimals": None, "success": None, "lineage": [row["event_id"]]}
                    if key not in structural or timestamp < structural[key]["timestamp"]:
                        structural[key] = context
            if row.get("pool"):
                pool = _address(row["pool"])
                roles[pool].add("pool")
                if task in {"honeypot", "rug_pull"} and root in {
                    str(row.get("token0", "")).lower(), str(row.get("token1", "")).lower()
                }:
                    context = {
                        "event_id": "context:" + row["event_id"], "chain_id": 1,
                        "timestamp": timestamp, "src": root, "dst": pool,
                        "relation": "contains", "asset": root, "raw_amount": None,
                        "decimals": None, "success": None,
                        "lineage": [row["event_id"]],
                    }
                    key = (root, pool, "contains")
                    previous_context = structural.get(key)
                    if previous_context is None or (timestamp, context["event_id"]) < (previous_context["timestamp"], previous_context["event_id"]):
                        structural[key] = context
            if row["relation"] == "deployed":
                roles[row["src"]].add("deployer")
                if row["dst"] == root:
                    key = (row["src"], root, "deployed")
                    previous_context = structural.get(key)
                    if previous_context is None or (timestamp, row["event_id"]) < (previous_context["timestamp"], previous_context["event_id"]):
                        structural[key] = row
            if row["relation"] == "lp_transfer":
                # A v2 pair contract is both the pool and its LP-token contract.
                asset = row.get("asset")
                if isinstance(asset, str) and _ADDRESS.fullmatch(asset.lower()):
                    roles[asset.lower()].update({"pool", "lp"})
            if start < timestamp <= cutoff:
                eligible.append(row)
        except (KeyError, ValueError, TypeError):
            invalid += 1
    # Structural membership valid at cutoff may predate the observation window.
    combined = {row["event_id"]: row for row in eligible}
    combined.update({row["event_id"]: row for row in structural.values()})
    rows = list(combined.values())
    adjacency: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        adjacency[row["src"]].add(row["dst"])
        adjacency[row["dst"]].add(row["src"])
    mandatory = {root, *selected_pools} if task in TOKEN_TASKS else {root}
    if len(mandatory) > max_nodes:
        raise ValueError("graph_budget_cannot_retain_selected_pools")
    selected = set(mandatory)
    frontier = sorted(mandatory)
    sampling_truncated = False
    for hop in range(hops):
        next_frontier: list[str] = []
        for node in sorted(frontier):
            neighbors = adjacency[node]
            sampling_truncated |= len(neighbors) > fanouts[hop]
            for other in select_neighbor_addresses(root, node, neighbors, fanouts[hop], seed):
                if other in selected:
                    continue
                if len(selected) >= max_nodes:
                    sampling_truncated = True
                    continue
                selected.add(other)
                next_frontier.append(other)
        frontier = next_frontier
    node_refs = [root] + sorted(selected - {root})
    index = {node: number for number, node in enumerate(node_refs)}
    retained = [row for row in rows if row["src"] in selected and row["dst"] in selected]
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in retained:
        asset = str(row.get("asset") or "unknown")
        if asset != "ETH":
            asset = asset.lower()
        groups[(row["src"], row["dst"], row["relation"], asset)].append(row)
    keys = sorted(groups, key=lambda key: (0 if task in TOKEN_TASKS and key[2] == "contains" else 1,
                                         root not in key[:2], _rank(seed, *key)))
    sampling_truncated |= len(keys) > max_edges
    keys = keys[:max_edges]
    retained = [row for key in keys for row in groups[key]]
    node_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in retained:
        node_events[row["src"]].append(row)
        if row["dst"] != row["src"]:
            node_events[row["dst"]].append(row)
    window_seconds = window_days * 86400

    def age(row: Mapping[str, Any]) -> float:
        return min(1.0, max(0.0, (cutoff - row["timestamp"]) / window_seconds))

    node_features: list[list[float]] = []
    mechanism_lineage = {}
    for node in node_refs:
        activity = [row for row in node_events[node] if row["relation"] not in {"contains", "deployed", "pair_created", "participates"}]
        # Token summaries use all admitted emitter events before graph sampling;
        # pool summaries include events whose endpoints are router/recipient.
        if task in TOKEN_TASKS:
            scoped_activity = ([row for row in rows if row["relation"] not in {"contains", "deployed", "pair_created", "participates"}]
                               if node == root else
                               [row for row in rows if row.get("pool") == node or row.get("asset") == node
                                or row["src"] == node or row["dst"] == node])
            mechanism_lineage[node] = sorted(row["event_id"] for row in scoped_activity
                                            if row["relation"] in {"swap", "mint", "burn", "sync", "lp_transfer"})
        incoming = [row for row in activity if row["dst"] == node]
        outgoing = [row for row in activity if row["src"] == node]
        monetary = [row for row in activity if row["relation"] in _MONEY_RELATIONS]
        values = [_amount(row) for row in monetary]
        def total(subset: list[dict[str, Any]], asset: str) -> float:
            return sum(_amount(row) or 0.0 for row in subset if str(row.get("asset")).lower() == asset.lower())
        ages = [age(row) for row in activity]
        count = len(activity)
        node_features.append([
            float(node == root), *(float(role in roles[node]) for role in ("token", "pool", "deployer", "lp")),
            _log(len(incoming)), _log(len(outgoing)),
            _log(len({row["src"] for row in incoming})), _log(len({row["dst"] for row in outgoing})),
            _log(total(incoming, "ETH")), _log(total(outgoing, "ETH")),
            _log(total(incoming, root)), _log(total(outgoing, root)),
            sum(value is None for value in values) / len(values) if values else 0.0,
            sum(row.get("success") is False for row in activity) / count if count else 0.0,
            sum(row.get("success") is None for row in activity) / count if count else 0.0,
            max(ages, default=0.0), min(ages, default=0.0), sum(ages) / count if count else 0.0,
            _log(sum(row["relation"] in {"call", "failed_call"} for row in activity)),
        ])
        if task in TOKEN_TASKS:
            node_features[-1].extend(mechanism_features(scoped_activity, node=True))
    edge_index: list[list[int]] = [[], []]
    relation_ids: list[int] = []
    edge_attributes: list[list[float]] = []
    edge_lineage: list[dict[str, Any]] = []
    for key in keys:
        src, dst, relation, asset = key
        group = sorted(groups[key], key=lambda row: (row["timestamp"], row["event_id"]))
        amounts = [_amount(row) for row in group]
        ages = [age(row) for row in group]
        size = len(group)
        edge_index[0].append(index[src]); edge_index[1].append(index[dst])
        relation_ids.append(RELATION_NAMES.index(relation))
        edge_attributes.append([
            _log(size), _log(sum(amount for amount in amounts if amount is not None)),
            sum(amount is None for amount in amounts) / size,
            max(ages), min(ages), sum(ages) / size,
            sum(row.get("success") is False for row in group) / size,
            sum(row.get("success") is None for row in group) / size,
            float(asset == "ETH"), float(asset == root), float(asset not in {"ETH", root}),
        ])
        if task in TOKEN_TASKS:
            edge_attributes[-1].extend(mechanism_features(group, node=False))
        edge_lineage.append({"relation": relation, "asset": asset, "event_ids": [row["event_id"] for row in group]})
    lp_flows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in retained:
        if row["relation"] != "lp_transfer" or row.get("success") is not True:
            continue
        try:
            amount = int(str(row.get("raw_amount")))
            if amount < 0:
                raise ValueError("negative LP amount")
        except (ValueError, TypeError):
            amount = None
        for participant, sign in ((row["src"], -1), (row["dst"], 1)):
            flow = lp_flows.setdefault((str(row.get("asset")), participant),
                {"net": 0, "missing": False, "event_ids": []})
            flow["missing"] |= amount is None
            flow["net"] += sign * (amount or 0)
            flow["event_ids"].append(row["event_id"])
    lp_positions = [{"pool": pool, "address": participant, "holding_raw": None,
                     "holding_status": "unknown_history_not_verified",
                     "observed_raw_net_flow": None if flow["missing"] else str(flow["net"]),
                     "scope": "sampled_observed_subgraph", "event_ids": sorted(set(flow["event_ids"]))}
                    for (pool, participant), flow in sorted(lp_flows.items())]
    sampling = {"hops": hops, "fanouts": list(fanouts[:hops]), "seed": seed,
                "max_nodes": max_nodes}
    complete = (bool(scope) and token_coverage_complete(target.get("coverage"), scope, start, cutoff)
                if task in TOKEN_TASKS else _coverage_complete(target.get("coverage"), start, cutoff, sampling))
    activity_count = sum(row["relation"] not in {"contains", "deployed", "pair_created", "participates"} for row in retained)
    status = "ok" if complete else "data_incomplete"
    if complete and not activity_count:
        status = "insufficient_history"
    if invalid or conflicting:
        status = "data_incomplete"
    result = {
        "schema_version": SCHEMA_VERSION, "graph_view_version": view_version,
        "task_id": task, "sample_id": str(target["sample_id"]), "target": root,
        "chain_id": 1, "cutoff": cutoff, "feature_start": start,
        "node_features": node_features, "edge_index": edge_index,
        "edge_attributes": edge_attributes, "relation_ids": relation_ids,
        "root_index": 0, "node_refs": node_refs,
        "feature_names": feature_names, "edge_feature_names": edge_feature_names,
        "relation_names": list(RELATION_NAMES),
        "quality": {"status": status, "coverage_complete": complete,
            "collection_coverage": dict(target.get("coverage") or {}),
            "neighborhood_history_complete": (target.get("coverage") or {}).get("neighborhood_history_complete"),
            "stat_scope": "sampled_observed_subgraph",
            "invalid_events": invalid, "duplicate_events": duplicates, "conflicting_events": conflicting,
            "excluded_future_events": future, "sampling_truncated": sampling_truncated,
            "observed_events": activity_count},
        "lineage": {"source_snapshot": target.get("source_snapshot"), "edge_groups": edge_lineage,
            "selected_pools": sorted(selected_pools), "pool_mapping_evidence_ref": target.get("pool_evidence_ref"),
            "lp_positions": lp_positions,
            "graph_builder": builder.name,
            "sampling": {"seed": seed, "hops": hops, "fanouts": list(fanouts[:hops]),
                "max_nodes": max_nodes, "max_edges": max_edges, "window_days": window_days}},
    }
    if task in TOKEN_TASKS:
        result["quality"].update(scope_status="verified" if scope else "unverified", scope_reason=scope_error,
                                 stat_scope="selected_token_pool_emitters")
        result["lineage"].update(token_scope=scope, scope_version=TOKEN_SCOPE_VERSION,
                                 mechanism_summary_event_ids=mechanism_lineage,
                                 mechanism_summary_scope="selected_token_pool_emitters_before_sampling")
        result["lineage"]["sampling"].update(mandatory_selected_pools=True)
    validate_graph_sample(result)
    return result


def validate_graph_sample(sample: Mapping[str, Any]) -> None:
    view, features, edge_features = graph_schema(sample.get("task_id"))
    if sample.get("schema_version") != SCHEMA_VERSION or sample.get("graph_view_version") != view:
        raise ValueError("unsupported graph schema/view version")
    if sample.get("feature_names") != features or sample.get("edge_feature_names") != edge_features:
        raise ValueError("graph feature order/schema mismatch")
    if sample.get("relation_names") != RELATION_NAMES:
        raise ValueError("graph relation schema mismatch")
    if sample.get("chain_id") != 1 or sample.get("task_id") not in {"phishing", "ponzi", "honeypot", "rug_pull"}:
        raise ValueError("unsupported chain/task")
    if sample["target"] != _address(sample["target"]):
        raise ValueError("target must be a canonical lowercase address")
    if not isinstance(sample.get("quality"), dict) or not sample["quality"].get("status"):
        raise ValueError("explicit graph quality status required")
    nodes = sample["node_features"]
    if not nodes or any(len(row) != len(features) for row in nodes):
        raise ValueError("invalid node feature shape")
    root = sample["root_index"]
    if not isinstance(root, int) or isinstance(root, bool) or not 0 <= root < len(nodes):
        raise ValueError("root_index outside graph")
    refs = sample["node_refs"]
    if len(refs) != len(nodes) or len(set(refs)) != len(refs) or refs[root] != sample["target"]:
        raise ValueError("node identity/root mismatch")
    for ref in refs:
        if ref != _address(ref):
            raise ValueError("node_refs must use canonical lowercase addresses")
    if nodes[root][0] != 1.0 or sum(row[0] for row in nodes) != 1.0:
        raise ValueError("exactly one node must carry the root flag")
    edge_index = sample["edge_index"]
    if len(edge_index) != 2 or len(edge_index[0]) != len(edge_index[1]):
        raise ValueError("edge_index must have shape [2, E]")
    edge_count = len(edge_index[0])
    if len(sample["edge_attributes"]) != edge_count or len(sample["relation_ids"]) != edge_count:
        raise ValueError("edge attribute/relation count mismatch")
    if any(len(row) != len(edge_features) for row in sample["edge_attributes"]):
        raise ValueError("invalid edge feature shape")
    if any(not isinstance(node, int) or isinstance(node, bool) or not 0 <= node < len(nodes) for side in edge_index for node in side):
        raise ValueError("edge endpoint outside graph")
    if any(not isinstance(rel, int) or isinstance(rel, bool) or not 0 <= rel < len(RELATION_NAMES) for rel in sample["relation_ids"]):
        raise ValueError("invalid relation id")
    allowed = get_graph_builder(sample["task_id"]).allowed_relations
    if any(RELATION_NAMES[relation] not in allowed for relation in sample["relation_ids"]):
        raise ValueError("graph relation not admitted for task strategy")
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
           for rows in (nodes, sample["edge_attributes"]) for row in rows for value in row):
        raise ValueError("features must be finite numbers")
    if not isinstance(sample.get("cutoff"), int) or not isinstance(sample.get("feature_start"), int) or sample["feature_start"] >= sample["cutoff"]:
        raise ValueError("invalid observation interval")


def graph_is_usable(sample: Mapping[str, Any]) -> bool:
    validate_graph_sample(sample)
    quality = sample["quality"]
    if sample["task_id"] in TOKEN_TASKS:
        scope = sample.get("lineage", {}).get("token_scope")
        if (not isinstance(scope, dict) or quality.get("scope_status") != "verified"
                or scope.get("token") != sample["target"]
                or sorted(item["pool"] for item in scope.get("pools", [])) != sample["lineage"]["selected_pools"]
                or not token_coverage_complete(quality.get("collection_coverage"), scope,
                                               sample["feature_start"], sample["cutoff"])):
            return False
    return (quality.get("status") == "ok" and quality.get("coverage_complete") is True
            and isinstance(quality.get("observed_events"), int) and quality["observed_events"] > 0)


def graph_recipe(sample: Mapping[str, Any]) -> dict[str, Any]:
    lineage = sample.get("lineage", {})
    builder, sampling = lineage.get("graph_builder"), lineage.get("sampling")
    if builder != get_graph_builder(sample["task_id"]).name or not isinstance(sampling, dict):
        raise ValueError("graph builder/sampling recipe missing or incompatible")
    required = {"seed", "hops", "fanouts", "max_nodes", "max_edges", "window_days"}
    extras = {"mandatory_selected_pools"} if sample["task_id"] in TOKEN_TASKS else set()
    if set(sampling) != required | extras or extras and sampling.get("mandatory_selected_pools") is not True:
        raise ValueError("graph sampling recipe schema mismatch")
    if (any(not isinstance(sampling[key], int) or isinstance(sampling[key], bool) for key in required - {"fanouts"})
            or sampling["hops"] < 1 or sampling["window_days"] < 1
            or sampling["max_nodes"] < 1 or sampling["max_edges"] < 1
            or not isinstance(sampling["fanouts"], list) or len(sampling["fanouts"]) != sampling["hops"]
            or any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in sampling["fanouts"])):
        raise ValueError("invalid graph sampling recipe")
    if sample["cutoff"] - sample["feature_start"] != sampling["window_days"] * 86400:
        raise ValueError("observation window contradicts graph sampling recipe")
    return {"builder": builder, "sampling": {**sampling, "fanouts": list(sampling["fanouts"])}}


def fit_scaler(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fit only on the supplied training graphs; caller owns split admission."""
    if not samples:
        raise ValueError("cannot fit an empty training cohort")
    for sample in samples:
        validate_graph_sample(sample)
        if not graph_is_usable(sample):
            raise ValueError("scaler requires quality-approved training samples")
    recipe = graph_recipe(samples[0])
    if any(graph_recipe(sample) != recipe for sample in samples):
        raise ValueError("training scaler cannot mix graph recipes")
    def stats(key: str, dimension: int, unscaled: set[int]) -> tuple[list[float], list[float]]:
        rows = [row for sample in samples for row in sample[key]]
        if not rows:
            return [0.0] * dimension, [1.0] * dimension
        mean = [sum(row[column] for row in rows) / len(rows) for column in range(dimension)]
        std = [max(1e-6, math.sqrt(sum((row[column] - mean[column]) ** 2 for row in rows) / len(rows))) for column in range(dimension)]
        for column in unscaled:
            mean[column], std[column] = 0.0, 1.0
        return mean, std
    view, features, edge_features = graph_schema(samples[0]["task_id"])
    if any(graph_schema(sample["task_id"]) != (view, features, edge_features) for sample in samples):
        raise ValueError("scaler cannot mix feature schemas")
    node_unscaled = _NODE_UNSCALED | (set(range(len(FEATURE_NAMES) + 9, len(features))) if samples[0]["task_id"] in TOKEN_TASKS else set())
    edge_unscaled = _EDGE_UNSCALED | (set(range(len(EDGE_FEATURE_NAMES) + 4, len(edge_features))) if samples[0]["task_id"] in TOKEN_TASKS else set())
    node_mean, node_std = stats("node_features", len(features), node_unscaled)
    edge_mean, edge_std = stats("edge_attributes", len(edge_features), edge_unscaled)
    return {"version": "train-only-scaler-1.0", "feature_names": features,
        "edge_feature_names": edge_features, "node_mean": node_mean, "node_std": node_std,
        "edge_mean": edge_mean, "edge_std": edge_std,
        "graph_recipe": recipe,
        "fitted_sample_ids": [sample["sample_id"] for sample in samples]}


@dataclass
class GraphBatch:
    x: Any
    edge_index: Any
    edge_attr: Any
    relation_ids: Any
    root_indices: Any
    graph_ids: Any
    sample_ids: list[str]
    qualities: list[dict[str, Any]]

    def to(self, device: Any) -> "GraphBatch":
        return GraphBatch(*(getattr(self, key).to(device) for key in (
            "x", "edge_index", "edge_attr", "relation_ids", "root_indices", "graph_ids")),
            self.sample_ids, self.qualities)


def batch_graph_samples(
    samples: Sequence[Mapping[str, Any]], scaler: Mapping[str, Any],
    device: Any = "cpu", add_reverse: bool = True,
) -> GraphBatch:
    import torch
    if not samples:
        raise ValueError("cannot batch an empty graph list")
    _, features, edge_features = graph_schema(samples[0]["task_id"])
    if scaler.get("feature_names") != features or scaler.get("edge_feature_names") != edge_features:
        raise ValueError("scaler feature schema mismatch")
    for kind, dimension in (("node", len(features)), ("edge", len(edge_features))):
        mean, std = scaler[kind + "_mean"], scaler[kind + "_std"]
        if len(mean) != dimension or len(std) != dimension or any(not math.isfinite(value) for value in mean) or any(not math.isfinite(value) or value <= 0 for value in std):
            raise ValueError("invalid scaler statistics")
    x_parts, edge_parts, attr_parts, rel_parts, roots, ids = [], [], [], [], [], []
    offset = 0
    for number, sample in enumerate(samples):
        validate_graph_sample(sample)
        if sample["feature_names"] != features or sample["edge_feature_names"] != edge_features:
            raise ValueError("batch cannot mix feature schemas")
        if graph_recipe(sample) != scaler.get("graph_recipe"):
            raise ValueError("prediction graph sampling recipe differs from training scaler")
        x = torch.tensor(sample["node_features"], dtype=torch.float32)
        attrs = torch.tensor(sample["edge_attributes"], dtype=torch.float32).reshape(-1, len(edge_features))
        x = (x - torch.tensor(scaler["node_mean"])) / torch.tensor(scaler["node_std"])
        attrs = (attrs - torch.tensor(scaler["edge_mean"])) / torch.tensor(scaler["edge_std"])
        edges = torch.tensor(sample["edge_index"], dtype=torch.long).reshape(2, -1) + offset
        relations = torch.tensor(sample["relation_ids"], dtype=torch.long)
        if add_reverse:
            edges = torch.cat((edges, edges.flip(0)), dim=1)
            attrs = torch.cat((attrs, attrs), dim=0)
            relations = torch.cat((relations, relations + len(RELATION_NAMES)))
        x_parts.append(x); edge_parts.append(edges); attr_parts.append(attrs); rel_parts.append(relations)
        roots.append(offset + sample["root_index"])
        ids.extend([number] * len(x))
        offset += len(x)
    return GraphBatch(torch.cat(x_parts).to(device), torch.cat(edge_parts, 1).to(device),
        torch.cat(attr_parts).to(device), torch.cat(rel_parts).to(device),
        torch.tensor(roots, dtype=torch.long, device=device), torch.tensor(ids, dtype=torch.long, device=device),
        [sample["sample_id"] for sample in samples], [dict(sample["quality"]) for sample in samples])
