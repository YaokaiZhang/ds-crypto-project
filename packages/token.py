"""Versioned selected-pool inputs for token risk screening, independent of labels."""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from decimal import Decimal
from typing import Any, Mapping, Sequence

from .transactions import address, integer

TOKEN_TASKS = frozenset({"honeypot", "rug_pull"})
TOKEN_VIEW_VERSION = "token-v2-scoped-2.0"
TOKEN_SCOPE_VERSION = "selected-token-pools-1.0"
TOKEN_RECENT_SAMPLING = "token_recent_bounded_v1"
TOKEN_RECENT_VIEW_VERSION = "token-v2-recent-1.0"
TOKEN_RECENT_SCOPE_VERSION = "selected-token-pools-recent-1.0"
UNISWAP_V2_FACTORY = "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f"
TOKEN_NODE_FEATURES = [
    "log_buy_swaps", "log_sell_swaps", "log_mints", "log_burns", "log_lp_transfers",
    "log_buy_target_amount", "log_sell_target_amount", "log_mint_target_amount",
    "log_burn_target_amount", "max_reserve_drop_fraction", "reserve_history_missing",
    "dex_amount_missing_fraction", "swap_direction_missing_fraction",
    "lp_flow_concentration", "lp_flow_missing",
]
TOKEN_EDGE_FEATURES = [
    "log_buy_events", "log_sell_events", "log_dex_target_in", "log_dex_target_out",
    "dex_amount_missing_fraction", "swap_direction_missing_fraction",
]


def token_scope(target: Mapping[str, Any]) -> dict[str, Any]:
    """Require point-in-time pair identity; a supplied address is not verification."""
    root = address(target.get("target"))
    pools = target.get("pools", [])
    if not root or not isinstance(pools, list) or not pools:
        raise ValueError("token_scope_requires_selected_pools")
    selected = [address(value) for value in pools]
    if None in selected or root in selected or len(set(selected)) != len(selected):
        raise ValueError("invalid_or_duplicate_selected_pool")
    block = target.get("cutoff_block", target.get("end_block"))
    if not isinstance(block, int) or isinstance(block, bool) or block < 0:
        raise ValueError("token_scope_requires_cutoff_block")
    facts = target.get("pool_metadata", [])
    if not isinstance(facts, list):
        raise ValueError("pool_metadata_requires_list")
    metadata = {}
    for item in facts:
        if not isinstance(item, dict):
            raise ValueError("invalid_pool_metadata")
        pool = address(item.get("pool"))
        if pool in metadata:
            raise ValueError("duplicate_pool_metadata")
        metadata[pool] = item
    verified = []
    for pool in sorted(selected):
        item = metadata.get(pool, {})
        tokens = [address(item.get(key)) for key in ("token0", "token1")]
        if (None in tokens or tokens[0] >= tokens[1] or root not in tokens
                or address(item.get("factory")) != UNISWAP_V2_FACTORY
                or item.get("verified_at_block") != block or not item.get("evidence_ref")):
            raise ValueError("unverified_or_incompatible_v2_pool")
        verified.append({"pool": pool, "token0": tokens[0], "token1": tokens[1],
                         "factory": UNISWAP_V2_FACTORY, "verified_at_block": block,
                         "evidence_ref": str(item["evidence_ref"])})
    token_facts = target.get("token_metadata", {})
    if not isinstance(token_facts, dict):
        raise ValueError("invalid_token_metadata")
    decimals = token_facts.get("decimals")
    if (not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 255
            or token_facts.get("verified_at_block") != block or not token_facts.get("evidence_ref")):
        raise ValueError("token_scope_requires_historical_decimals")
    scope = {"version": TOKEN_SCOPE_VERSION, "token": root, "pools": verified,
             "cutoff_block": block, "decimals": decimals,
             "token_evidence_ref": str(token_facts["evidence_ref"])}
    scope["sha256"] = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    return scope


def token_coverage_complete(coverage: Any, scope: Mapping[str, Any], start: int, cutoff: int,
                            sampling: Mapping[str, Any] | None = None) -> bool:
    if not isinstance(coverage, dict):
        return False
    digest = hashlib.sha256(json.dumps({key: value for key, value in scope.items() if key != "sha256"}, sort_keys=True).encode()).hexdigest()
    if scope.get("sha256") != digest:
        return False
    required = {scope["token"], *(item["pool"] for item in scope["pools"])}
    recent = sampling is not None and sampling.get("sampling_mode") == TOKEN_RECENT_SAMPLING
    version = TOKEN_RECENT_SCOPE_VERSION if recent else TOKEN_SCOPE_VERSION
    if (coverage.get("complete") is not True or coverage.get("scope_version") != version
            or coverage.get("scope_sha256") != scope["sha256"]
            or coverage.get("start_timestamp") != start or coverage.get("end_timestamp") != cutoff
            or set(coverage.get("required_emitters", [])) != required
            or coverage.get("end_block") != scope["cutoff_block"]):
        return False
    if recent:
        if (coverage.get("full_history_complete") is not False or coverage.get("sampling") != dict(sampling)
                or coverage.get("stop_reason") not in {"graph_budget_reached", "source_exhausted", "record_budget_reached"}):
            return False
    sources = coverage.get("sources", [])
    if not isinstance(sources, list) or any(not isinstance(item, dict) for item in sources):
        return False
    for entity in required:
        for action in ("getLogs", "txlist", "txlistinternal"):
            matches = [item for item in sources if item.get("address") == entity and item.get("action") == action]
            if (len(matches) != 1 or matches[0].get("complete") is not True
                    or matches[0].get("gaps") or matches[0].get("end_block") != scope["cutoff_block"]
                    or matches[0].get("start_block") != coverage.get("start_block")):
                return False
            if recent and (type(matches[0].get("rows")) is not int
                           or not 0 <= matches[0]["rows"] <= sampling["rows_per_action"] * sampling["pages_per_action"]):
                return False
    return True


def annotate_token_events(events: Sequence[dict[str, Any]], scope: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Use verified pair order, never external risk flags, to interpret amounts."""
    pools = {item["pool"]: item for item in scope["pools"]}
    root = scope["token"]
    result = []
    for original in events:
        row = dict(original)
        relation = row.get("relation")
        pool = address(row.get("pool"))
        emitter = address(row.get("address"))
        if relation == "erc20_transfer" and str(row.get("asset", "")).lower() == root:
            row["decimals"] = scope["decimals"]
        elif relation == "lp_transfer" and str(row.get("asset", "")).lower() in pools:
            row["decimals"] = 18  # Canonical Uniswap v2 LP ERC20 constant.
        if pool in pools:
            facts = pools[pool]
            if any(row.get(key) and str(row[key]).lower() != facts[key] for key in ("token0", "token1")):
                raise ValueError("pool_event_asset_mapping_mismatch")
            row.update(token0=facts["token0"], token1=facts["token1"])
            # DEX edge endpoints denote event participants; pool is retained separately.
            side = "0" if facts["token0"] == root else "1"
            if relation == "swap":
                incoming = integer(row.get(f"amount{side}_in"))
                outgoing = integer(row.get(f"amount{side}_out"))
                direction = ("sell" if incoming and outgoing == 0 else
                             "buy" if outgoing and incoming == 0 else "unknown")
                row["swap_direction"] = direction
                row["target_in_raw"], row["target_out_raw"] = incoming, outgoing
            elif relation in {"mint", "burn"}:
                amount = integer(row.get(f"amount{side}"))
                row["target_in_raw"] = amount if relation == "mint" else 0
                row["target_out_raw"] = amount if relation == "burn" else 0
            elif relation == "sync":
                row["target_reserve_raw"] = integer(row.get(f"reserve{side}"))
            row["target_decimals"] = scope["decimals"]
        # Ignore facts outside this sample's emitters, even when batch collection
        # has fetched shared wallets or another target token's logs.
        if (relation in {"swap", "mint", "burn", "sync"} and pool not in pools
                or relation == "lp_transfer" and str(row.get("asset", "")).lower() not in pools
                or relation == "erc20_transfer" and str(row.get("asset", "")).lower() != root
                or relation == "pair_created"
                or relation in {"external_eth", "internal_eth", "call", "failed_call", "deployed"}
                and not {row.get("src"), row.get("dst")}.intersection({root, *pools})):
            continue
        if emitter and relation in {"swap", "mint", "burn", "sync"} and emitter != pool:
            raise ValueError("pool_event_emitter_mismatch")
        result.append(row)
    return result


def _amount(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    decimals = row.get("target_decimals")
    if value is None or value < 0 or not isinstance(decimals, int):
        return None
    result = float(Decimal(value) / (Decimal(10) ** decimals))
    return result if math.isfinite(result) else None


def mechanism_features(rows: Sequence[Mapping[str, Any]], *, node: bool) -> list[float]:
    """Window summaries; reserves are ordered by block/transaction/log identity."""
    swaps = [row for row in rows if row["relation"] == "swap"]
    dex = [row for row in rows if row["relation"] in {"swap", "mint", "burn"}]
    buys = [row for row in swaps if row.get("swap_direction") == "buy"]
    sells = [row for row in swaps if row.get("swap_direction") == "sell"]
    missing = sum(_amount(row, "target_in_raw") is None or _amount(row, "target_out_raw") is None for row in dex)
    direction_missing = sum(row.get("swap_direction", "unknown") == "unknown" for row in swaps) / len(swaps) if swaps else 0.0
    def total(subset, key):
        return math.log1p(sum(_amount(row, key) or 0.0 for row in subset))
    if not node:
        return [math.log1p(len(buys)), math.log1p(len(sells)), total(dex, "target_in_raw"),
                total(dex, "target_out_raw"), missing / len(dex) if dex else 0.0, direction_missing]
    mints = [row for row in dex if row["relation"] == "mint"]
    burns = [row for row in dex if row["relation"] == "burn"]
    reserves = defaultdict(list)
    for row in rows:
        if row["relation"] == "sync" and row.get("target_reserve_raw") is not None:
            reserves[row.get("pool")].append(row)
    drops = []
    for observations in reserves.values():
        ordered = sorted(observations, key=lambda row: (row.get("block_number", 0), row.get("transaction_index") or 0, row.get("log_index") or 0))
        drops.extend(max(0.0, (a["target_reserve_raw"] - b["target_reserve_raw"]) / a["target_reserve_raw"])
                     for a, b in zip(ordered, ordered[1:]) if a["target_reserve_raw"] > 0)
    lp = [row for row in rows if row["relation"] == "lp_transfer"]
    flows = defaultdict(lambda: defaultdict(int))
    for row in lp:
        amount = integer(row.get("raw_amount"))
        if amount is not None and amount >= 0:
            flows[row.get("asset")][row["src"]] += amount
    concentrations = [max(values.values()) / sum(values.values()) for values in flows.values() if sum(values.values()) > 0]
    return [math.log1p(len(buys)), math.log1p(len(sells)), math.log1p(len(mints)),
            math.log1p(len(burns)), math.log1p(len(lp)), total(buys, "target_out_raw"),
            total(sells, "target_in_raw"), total(mints, "target_in_raw"), total(burns, "target_out_raw"),
            max(drops, default=0.0), float(not drops), missing / len(dex) if dex else 0.0,
            direction_missing, max(concentrations, default=0.0),
            float(not concentrations or any(integer(row.get("raw_amount")) is None for row in lp))]
