"""Decode chain facts and describe transaction participants without assigning guilt."""
from __future__ import annotations

from typing import Any

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
V2_TOPICS = {
    "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9": "pair_created",
    "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f": "mint",
    "0xdccd412f0b1252819cb1fd330b93224ca42612892bb3f4f789976e6d81936496": "burn",
    "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822": "swap",
    "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1": "sync",
}


def address(value: Any) -> str | None:
    value = str(value or "").lower()
    if len(value) == 42 and value.startswith("0x"):
        try:
            int(value[2:], 16)
            return value
        except ValueError:
            pass
    return None


def integer(value: Any, *, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    # Etherscan getLogs encodes zero log/transaction indices as bare `0x`.
    if str(value).lower() == "0x":
        return 0
    try:
        return int(str(value), 16 if str(value).lower().startswith("0x") else 10)
    except (ValueError, TypeError):
        return default


def _topic_address(value: Any) -> str | None:
    text = str(value or "")
    if len(text) != 66 or not text.startswith("0x") or text[2:26] != "0" * 24:
        raise ValueError("invalid_abi_address")
    parsed = address("0x" + text[-40:])
    if parsed is None:
        raise ValueError("invalid_abi_address")
    return parsed


def decode_v2_log(log: dict[str, Any]) -> dict[str, Any] | None:
    """Decode supported fixed-width events; return None for unrelated logs.

    A signature match is not proof that the emitter is an official pool.
    Factory/pool allowlists are checked by the collection/graph task adapter.
    """
    topics = [str(item).lower() for item in log.get("topics", [])]
    if not topics:
        return None
    topic = topics[0]
    kind = V2_TOPICS.get(topic)
    if topic != TRANSFER_TOPIC and kind is None:
        return None
    data = str(log.get("data") or "0x")
    encoded = data[2:] if data.startswith("0x") else data
    if len(encoded) % 64:
        raise ValueError("invalid_abi_word_length")
    try:
        words = [int(encoded[i:i + 64], 16) for i in range(0, len(encoded), 64)]
    except ValueError as exc:
        raise ValueError("invalid_abi_uint") from exc
    emitter = address(log.get("address"))
    if emitter is None:
        raise ValueError("invalid_log_emitter")
    if topic == TRANSFER_TOPIC:
        if len(topics) != 3 or len(words) != 1:
            # ERC721 uses the same signature with a fourth indexed topic.
            raise ValueError("not_erc20_transfer_shape")
        return {"relation": "erc20_transfer", "src": _topic_address(topics[1]),
                "dst": _topic_address(topics[2]), "asset": emitter,
                "raw_amount": str(words[0])}
    if kind == "pair_created":
        if len(topics) != 3 or len(words) != 2:
            raise ValueError("invalid_pair_created_shape")
        if words[0] >= 2 ** 160:
            raise ValueError("invalid_abi_address")
        pair = address("0x" + format(words[0], "064x")[-40:])
        return {"relation": kind, "src": emitter, "dst": pair, "pool": pair,
                "token0": _topic_address(topics[1]), "token1": _topic_address(topics[2]),
                "pair_count": str(words[1])}
    if kind == "sync":
        if len(topics) != 1 or len(words) != 2:
            raise ValueError("invalid_sync_shape")
        return {"relation": kind, "src": emitter, "dst": emitter, "pool": emitter,
                "reserve0": str(words[0]), "reserve1": str(words[1])}
    needed_words = 4 if kind == "swap" else 2
    needed_topics = 2 if kind == "mint" else 3
    if len(words) != needed_words or len(topics) != needed_topics:
        raise ValueError(f"invalid_{kind}_shape")
    sender = _topic_address(topics[1])
    recipient = emitter if kind == "mint" else _topic_address(topics[2])
    result = {"relation": kind, "src": emitter if kind == "burn" else sender,
              "dst": recipient, "pool": emitter, "event_sender": sender}
    if kind == "swap":
        result.update(dict(zip(("amount0_in", "amount1_in", "amount0_out", "amount1_out"), map(str, words))))
    else:
        result.update(amount0=str(words[0]), amount1=str(words[1]))
    return result


def resolve_transaction(tx: dict[str, Any], receipt: dict[str, Any] | None = None,
                        known_entities: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return participant/address roles, never inherited malicious labels."""
    known_entities = {str(k).lower(): v for k, v in (known_entities or {}).items()}
    roles: dict[str, set[str]] = {}

    def add(value: Any, role: str) -> None:
        parsed = address(value)
        if parsed:
            roles.setdefault(parsed, set()).add(role)

    add(tx.get("from"), "transaction_sender")
    add(tx.get("to"), "transaction_recipient")
    add((receipt or {}).get("contractAddress") or tx.get("contractAddress"), "created_contract")
    for log in (receipt or {}).get("logs", []):
        add(log.get("address"), "log_emitter")
        try:
            decoded = decode_v2_log(log)
        except ValueError:
            continue
        if decoded:
            add(decoded.get("src"), "event_sender")
            add(decoded.get("dst"), "event_recipient")
            for key in ("pool", "token0", "token1"):
                add(decoded.get(key), key)
    return [{"address": item, "roles": sorted(item_roles),
             "known_entity": known_entities.get(item), "label_inherited": False}
            for item, item_roles in sorted(roles.items())]
