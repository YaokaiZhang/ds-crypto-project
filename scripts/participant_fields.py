"""Source mappings and validation for swap participant addresses."""

from __future__ import annotations

import re
from typing import Any


ADDRESS_PATTERN = re.compile(r"^0x[0-9a-f]{40}$")

# These fields are protocol-level Swap fields, not inferred from one another.
PARTICIPANT_SOURCE_FIELDS: dict[str, dict[str, str]] = {
    "uniswap_v2": {
        "swap_sender": "sender",
        "swap_recipient": "to",
        "transaction_from": "from",
    },
    "uniswap_v3": {
        "swap_sender": "sender",
        "swap_recipient": "recipient",
        "transaction_from": "origin",
    },
}

CANONICAL_PARTICIPANT_FIELDS = tuple(PARTICIPANT_SOURCE_FIELDS["uniswap_v2"])


def normalize_address(value: Any) -> str | None:
    """Return a canonical lowercase EVM address, or None when invalid/missing."""
    if value is None:
        return None
    candidate = str(value).strip().lower()
    return candidate if ADDRESS_PATTERN.fullmatch(candidate) else None


def normalize_source_participants(
    protocol: str,
    event_type: str,
    row: dict[str, Any],
) -> dict[str, str | None]:
    """Map source-specific Swap fields to the canonical event fields."""
    empty = {field: None for field in CANONICAL_PARTICIPANT_FIELDS}
    if event_type != "swap":
        return empty
    try:
        source_fields = PARTICIPANT_SOURCE_FIELDS[protocol]
    except KeyError as exc:
        raise ValueError(f"unsupported protocol for participant fields: {protocol}") from exc
    return {
        field: normalize_address(row.get(source_field))
        for field, source_field in source_fields.items()
    }


def normalize_canonical_participants(row: dict[str, Any]) -> dict[str, str | None]:
    """Validate participant fields already present in a normalized event row."""
    return {
        field: normalize_address(row.get(field))
        for field in CANONICAL_PARTICIPANT_FIELDS
    }
