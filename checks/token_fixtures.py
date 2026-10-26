"""Invented token facts for engineering checks, never a training dataset."""
from packages.token import TOKEN_SCOPE_VERSION, UNISWAP_V2_FACTORY, token_scope


def addr(number):
    return f"0x{number:040x}"


def token_target(task="honeypot", index=0, cutoff=10_000_000, window_days=30):
    root, pool, quote = addr(1000 + index), addr(2000 + index), addr(3000 + index)
    target = {"sample_id": f"synthetic-{task}-{index}", "task_id": task, "target": root,
              "chain_id": 1, "cutoff": cutoff, "start_block": 1, "end_block": 100,
              "cutoff_block": 100, "pools": [pool], "synthetic": True,
              "pool_metadata": [{"pool": pool, "token0": root, "token1": quote,
                                 "factory": UNISWAP_V2_FACTORY, "verified_at_block": 100,
                                 "evidence_ref": "synthetic://pair/getters"}],
              "token_metadata": {"decimals": 18, "verified_at_block": 100,
                                 "evidence_ref": "synthetic://token/decimals"}}
    return attach_coverage(target, window_days)


def attach_coverage(target, window_days=30):
    scope = token_scope(target)
    emitters = sorted({target["target"], *target["pools"]})
    target["coverage"] = {"complete": True, "neighborhood_history_complete": False,
                          "scope_version": TOKEN_SCOPE_VERSION, "scope_sha256": scope["sha256"],
                          "required_emitters": emitters, "start_block": target["start_block"],
                          "end_block": target["end_block"],
                          "start_timestamp": target["cutoff"] - window_days * 86400,
                          "end_timestamp": target["cutoff"],
                          "sources": [{"address": entity, "action": action, "complete": True, "gaps": [],
                                       "start_block": target["start_block"], "end_block": target["end_block"]}
                                      for entity in emitters for action in ("getLogs", "txlist", "txlistinternal")]}
    return target


def token_events(target):
    root, pool = target["target"], target["pools"][0]
    wallet = addr(4000 + int(root, 16))
    def event(index, relation, src, dst, **fields):
        return {"event_id": f'{target["sample_id"]}:{index}', "chain_id": 1,
                "timestamp": target["cutoff"] - 100 + index, "block_number": 80 + index,
                "tx_hash": f"0x{index + int(root, 16):064x}", "log_index": index,
                "relation": relation, "src": src, "dst": dst, "raw_amount": None,
                "asset": None, "decimals": None, "success": True, "synthetic": True, **fields}
    return [event(0, "erc20_transfer", wallet, pool, asset=root, raw_amount=str(10**18), address=root),
            event(1, "swap", wallet, wallet, pool=pool, address=pool,
                  amount0_in=str(10**18), amount0_out="0", amount1_in="0", amount1_out=str(10**16)),
            event(2, "swap", wallet, wallet, pool=pool, address=pool,
                  amount0_in="0", amount0_out=str(2 * 10**18), amount1_in=str(2 * 10**16), amount1_out="0"),
            event(3, "mint", wallet, pool, pool=pool, address=pool, amount0=str(100 * 10**18), amount1=str(10**18)),
            event(4, "sync", pool, pool, pool=pool, address=pool, reserve0=str(500 * 10**18), reserve1=str(5 * 10**18)),
            event(5, "burn", pool, wallet, pool=pool, address=pool, amount0=str(200 * 10**18), amount1=str(2 * 10**18)),
            event(6, "sync", pool, pool, pool=pool, address=pool, reserve0=str(300 * 10**18), reserve1=str(3 * 10**18)),
            event(7, "lp_transfer", wallet, pool, asset=pool, raw_amount=str(10**18), address=pool)]


def token_label(target, positive=True):
    return {"task_id": target["task_id"], "entity_id": target["target"], "mapped_label": int(positive),
            "label_status": "supported_positive" if positive else "supported_negative",
            "role": "token_contract", "audit_decision": "reviewed",
            "valid_from": target["cutoff"] - 50, "valid_to": target["cutoff"],
            "label_available_at": target["cutoff"], "pool_addresses": target["pools"],
            "incident_tx": "0x" + "a" * 64, "controller_evidence_ref": "synthetic://controller",
            "source_id": "synthetic", "source_sha256": "synthetic-only",
            "evidence_ref": "synthetic://label", "label_version": "synthetic-only"}
