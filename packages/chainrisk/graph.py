"""Cutoff-bounded Task B graphs and label-free tensor conversion.

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
        raise ValueError("Task B v1 only supports Ethereum chain_id=1")
    cutoff = target["cutoff"]
    if not isinstance(cutoff, int) or isinstance(cutoff, bool):
        raise ValueError("cutoff must be an integer Unix timestamp")
    start = cutoff - window_days * 86400
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
                fields = ("timestamp", "src", "dst", "relation", "asset", "raw_amount", "decimals", "success")
                if any(previous.get(key) != row.get(key) for key in fields):
                    conflicting += 1
                else:
                    duplicates += 1
                continue
            seen[row["event_id"]] = row
            if timestamp > cutoff:
                future += 1
                continue
            if task in {"honeypot", "rug_pull"} and start < timestamp <= cutoff:
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
    selected = {root}
    frontier = [root]
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
    keys = sorted(groups, key=lambda key: (root not in key[:2], _rank(seed, *key)))
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
    for node in node_refs:
        activity = [row for row in node_events[node] if row["relation"] not in {"contains", "deployed", "pair_created", "participates"}]
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
    complete = _coverage_complete(target.get("coverage"), start, cutoff, sampling)
    activity_count = sum(row["relation"] not in {"contains", "deployed", "pair_created", "participates"} for row in retained)
    status = "ok" if complete else "data_incomplete"
    if complete and not activity_count:
        status = "insufficient_history"
    if invalid or conflicting:
        status = "data_incomplete"
    result = {
        "schema_version": SCHEMA_VERSION, "graph_view_version": GRAPH_VIEW_VERSION,
        "task_id": task, "sample_id": str(target["sample_id"]), "target": root,
        "chain_id": 1, "cutoff": cutoff, "feature_start": start,
        "node_features": node_features, "edge_index": edge_index,
        "edge_attributes": edge_attributes, "relation_ids": relation_ids,
        "root_index": 0, "node_refs": node_refs,
        "feature_names": list(FEATURE_NAMES), "edge_feature_names": list(EDGE_FEATURE_NAMES),
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
    validate_graph_sample(result)
    return result


def validate_graph_sample(sample: Mapping[str, Any]) -> None:
    if sample.get("schema_version") != SCHEMA_VERSION or sample.get("graph_view_version") != GRAPH_VIEW_VERSION:
        raise ValueError("unsupported graph schema/view version")
    if sample.get("feature_names") != FEATURE_NAMES or sample.get("edge_feature_names") != EDGE_FEATURE_NAMES:
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
    if not nodes or any(len(row) != len(FEATURE_NAMES) for row in nodes):
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
    if any(len(row) != len(EDGE_FEATURE_NAMES) for row in sample["edge_attributes"]):
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
    return (quality.get("status") == "ok" and quality.get("coverage_complete") is True
            and isinstance(quality.get("observed_events"), int) and quality["observed_events"] > 0)


def graph_recipe(sample: Mapping[str, Any]) -> dict[str, Any]:
    lineage = sample.get("lineage", {})
    builder, sampling = lineage.get("graph_builder"), lineage.get("sampling")
    if builder != get_graph_builder(sample["task_id"]).name or not isinstance(sampling, dict):
        raise ValueError("graph builder/sampling recipe missing or incompatible")
    required = {"seed", "hops", "fanouts", "max_nodes", "max_edges", "window_days"}
    if set(sampling) != required:
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
    node_mean, node_std = stats("node_features", len(FEATURE_NAMES), _NODE_UNSCALED)
    edge_mean, edge_std = stats("edge_attributes", len(EDGE_FEATURE_NAMES), _EDGE_UNSCALED)
    return {"version": "train-only-scaler-1.0", "feature_names": list(FEATURE_NAMES),
        "edge_feature_names": list(EDGE_FEATURE_NAMES), "node_mean": node_mean, "node_std": node_std,
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
    if scaler.get("feature_names") != FEATURE_NAMES or scaler.get("edge_feature_names") != EDGE_FEATURE_NAMES:
        raise ValueError("scaler feature schema mismatch")
    for kind, dimension in (("node", len(FEATURE_NAMES)), ("edge", len(EDGE_FEATURE_NAMES))):
        mean, std = scaler[kind + "_mean"], scaler[kind + "_std"]
        if len(mean) != dimension or len(std) != dimension or any(not math.isfinite(value) for value in mean) or any(not math.isfinite(value) or value <= 0 for value in std):
            raise ValueError("invalid scaler statistics")
    x_parts, edge_parts, attr_parts, rel_parts, roots, ids = [], [], [], [], [], []
    offset = 0
    for number, sample in enumerate(samples):
        validate_graph_sample(sample)
        if graph_recipe(sample) != scaler.get("graph_recipe"):
            raise ValueError("prediction graph sampling recipe differs from training scaler")
        x = torch.tensor(sample["node_features"], dtype=torch.float32)
        attrs = torch.tensor(sample["edge_attributes"], dtype=torch.float32).reshape(-1, len(EDGE_FEATURE_NAMES))
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
