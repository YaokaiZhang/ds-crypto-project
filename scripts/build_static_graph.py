#!/usr/bin/env python3
"""Build cutoff-bounded ego graphs for a frozen model target manifest.

Each target token is represented by one small heterogeneous-shaped graph:
the center token connects to pool nodes, and each pool connects to its other
token.  The graph is stored as a homogeneous node feature matrix with node
type indicators.  Pool membership is bounded by the target token's cutoff;
pool event aggregates are bounded to the target token's observation window.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


NODE_FEATURE_NAMES = [
    "node_type_center",
    "node_type_counterparty",
    "node_type_pool",
    "log1p_event_count",
    "log1p_swap_count",
    "log1p_mint_count",
    "log1p_burn_count",
    "log1p_volume_usd",
    "active_day_fraction",
    "log1p_degree",
    "protocol_v2",
    "protocol_v3",
    "pool_age_years",
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
    return str(value or "").lower()


def positive_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed > 0 else 0.0


def nonnegative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def log1p(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return math.log1p(max(parsed, 0.0))


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


def _normalise_target(row: dict[str, Any], role: str | None, source: Path) -> dict[str, Any]:
    copied = dict(row)
    copied["token_address"] = lower(copied.get("token_address"))
    copied["source_dataset"] = str(copied.get("source_dataset") or "")
    if role is None:
        partition = str(copied.get("partition") or "")
        if partition not in {"train", "validation", "test"}:
            raise ValueError(f"{source}: target row has invalid partition: {partition!r}")
        role = "test_holdout" if partition == "test" else "development"
    copied["graph_role"] = role
    if not copied["token_address"] or not copied["source_dataset"]:
        raise ValueError(f"target row has no canonical key: {row}")
    if parse_time(copied.get("t0")) is None or parse_time(copied.get("cutoff")) is None:
        raise ValueError(f"target row has incomplete time bounds: {row}")
    return copied


def load_targets(
    cohort: Path | None = None,
    holdout: Path | None = None,
    split_targets: Path | None = None,
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    if split_targets is not None:
        for row in read_jsonl(split_targets):
            targets.append(_normalise_target(row, None, split_targets))
    elif cohort is not None and holdout is not None:
        paths = (("development", cohort), ("test_holdout", holdout))
        for role, path in paths:
            for row in read_jsonl(path):
                targets.append(_normalise_target(row, role, path))
    else:
        raise ValueError("provide either --targets or both --cohort and --holdout")
    keys = [(row["token_address"], row["source_dataset"]) for row in targets]
    if len(keys) != len(set(keys)):
        raise ValueError("target manifest contains duplicate token/source keys")
    return targets


def protocol_flags(protocols: Iterable[str]) -> tuple[float, float]:
    values = {str(value or "").lower() for value in protocols}
    return float("uniswap_v2" in values), float("uniswap_v3" in values)


def graph_for_target(
    target: dict[str, Any],
    pool_rows: Iterable[dict[str, Any]],
    event_stats: dict[tuple[str, str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Create one deterministic center-token ego graph."""
    token = lower(target["token_address"])
    source = str(target["source_dataset"])
    cutoff = parse_time(target.get("cutoff"))
    if cutoff is None:
        raise ValueError(f"missing cutoff for {token}")

    pools: dict[tuple[str, str], dict[str, Any]] = {}
    skipped_post_cutoff = 0
    skipped_invalid = 0
    for raw in pool_rows:
        pool_address = lower(raw.get("pool_address"))
        protocol = lower(raw.get("protocol"))
        token0 = lower(raw.get("token0"))
        token1 = lower(raw.get("token1"))
        creation = parse_time(raw.get("creation_timestamp"))
        if creation is not None and creation > cutoff:
            skipped_post_cutoff += 1
            continue
        if not pool_address or not protocol or not token0 or not token1 or creation is None:
            skipped_invalid += 1
            continue
        if token not in {token0, token1} or token0 == token1:
            skipped_invalid += 1
            continue
        counterparty = token1 if token0 == token else token0
        key = (protocol, pool_address)
        candidate = {
            "pool_address": pool_address,
            "protocol": protocol,
            "token0": token0,
            "token1": token1,
            "counterparty": counterparty,
            "creation_timestamp": creation.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        existing = pools.get(key)
        if existing is None:
            pools[key] = candidate
        elif (existing["token0"], existing["token1"]) != (token0, token1):
            raise ValueError(f"conflicting pool pair for {token}/{source}/{protocol}/{pool_address}")

    sorted_pools = [pools[key] for key in sorted(pools)]
    counterparties = sorted({row["counterparty"] for row in sorted_pools})
    nodes: list[dict[str, Any]] = [
        {"kind": "center", "id": token, "protocol": None},
    ]
    counterparty_index: dict[str, int] = {}
    for address in counterparties:
        counterparty_index[address] = len(nodes)
        nodes.append({"kind": "counterparty", "id": address, "protocol": None})

    pool_index: dict[tuple[str, str], int] = {}
    for pool in sorted_pools:
        key = (pool["protocol"], pool["pool_address"])
        pool_index[key] = len(nodes)
        nodes.append({"kind": "pool", "id": pool["pool_address"], "protocol": pool["protocol"]})

    center_features = [0.0] * len(NODE_FEATURE_NAMES)
    center_features[0] = 1.0
    center_features[3] = log1p(target.get("event_count"))
    center_features[4] = log1p(target.get("swap_count"))
    center_features[5] = log1p(target.get("mint_count"))
    center_features[6] = log1p(target.get("burn_count"))
    center_features[7] = log1p(positive_float(target.get("pre_cutoff_volume_usd")))
    center_features[8] = min(nonnegative_int(target.get("active_day_count")) / 7.0, 1.0)
    center_features[9] = log1p(len(sorted_pools))
    v2, v3 = protocol_flags(pool["protocol"] for pool in sorted_pools)
    center_features[10] = v2
    center_features[11] = v3
    feature_rows: list[list[float]] = [center_features]

    counterparty_pools: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pool in sorted_pools:
        counterparty_pools[pool["counterparty"]].append(pool)
    for address in counterparties:
        related = counterparty_pools[address]
        features = [0.0] * len(NODE_FEATURE_NAMES)
        features[1] = 1.0
        features[9] = log1p(len(related))
        features[10], features[11] = protocol_flags(pool["protocol"] for pool in related)
        feature_rows.append(features)

    pool_event_count = 0
    for pool in sorted_pools:
        key = (token, source, pool["pool_address"], pool["protocol"])
        stats = event_stats.get(key, {})
        event_count = nonnegative_int(stats.get("event_count"))
        pool_event_count += event_count
        features = [0.0] * len(NODE_FEATURE_NAMES)
        features[2] = 1.0
        features[3] = log1p(event_count)
        features[4] = log1p(stats.get("swap_count"))
        features[5] = log1p(stats.get("mint_count"))
        features[6] = log1p(stats.get("burn_count"))
        features[7] = log1p(positive_float(stats.get("volume_usd")))
        features[8] = min(nonnegative_int(stats.get("active_day_count")) / 7.0, 1.0)
        features[9] = log1p(2)
        features[10], features[11] = protocol_flags([pool["protocol"]])
        creation = parse_time(pool["creation_timestamp"])
        features[12] = min(max((cutoff - creation).total_seconds(), 0.0) / (365.25 * 86400), 20.0)
        feature_rows.append(features)

    sources: list[int] = []
    destinations: list[int] = []
    for pool in sorted_pools:
        pidx = pool_index[(pool["protocol"], pool["pool_address"])]
        cidx = counterparty_index[pool["counterparty"]]
        sources.extend((0, pidx, cidx, pidx))
        destinations.extend((pidx, 0, pidx, cidx))

    graph = {
        "token_address": token,
        "source_dataset": source,
        "graph_role": target["graph_role"],
        "partition": target.get("partition"),
        "label": target.get("label"),
        "t0": target.get("t0"),
        "cutoff": target.get("cutoff"),
        "node_features": feature_rows,
        "node_refs": nodes,
        "edge_index": [sources, destinations],
        "stats": {
            "pool_count": len(sorted_pools),
            "counterparty_count": len(counterparties),
            "node_count": len(nodes),
            "edge_count": len(sources),
            "window_event_count": pool_event_count,
            "post_cutoff_pools_excluded": skipped_post_cutoff,
            "invalid_pools_skipped": skipped_invalid,
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
    node_count = len(features)
    if any(index < 0 or index >= node_count for row in edge_index for index in row):
        raise ValueError("edge index points outside node feature matrix")
    if not features or refs[0]["kind"] != "center":
        raise ValueError("node zero must be the target center")
    if any(not math.isfinite(float(value)) for row in features for value in row):
        raise ValueError("non-finite graph feature")


def _target_table(connection: Any, targets: list[dict[str, Any]]) -> None:
    connection.execute("DROP TABLE IF EXISTS graph_targets")
    connection.execute(
        "CREATE TEMP TABLE graph_targets(token_address VARCHAR, source_dataset VARCHAR, t0 TIMESTAMPTZ, cutoff TIMESTAMPTZ)"
    )
    values = [
        (row["token_address"], row["source_dataset"], parse_time(row["t0"]), parse_time(row["cutoff"]))
        for row in targets
    ]
    connection.executemany("INSERT INTO graph_targets VALUES (?, ?, ?, ?)", values)


def _rows(connection: Any, query: str) -> list[dict[str, Any]]:
    result = connection.execute(query)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def build(args: argparse.Namespace) -> dict[str, Any]:
    import duckdb

    database = Path(args.database).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    targets = load_targets(
        cohort=Path(args.cohort) if args.cohort else None,
        holdout=Path(args.holdout) if args.holdout else None,
        split_targets=Path(args.targets) if args.targets else None,
    )
    connection = duckdb.connect(str(database), read_only=True)
    _target_table(connection, targets)

    pool_rows = _rows(
        connection,
        """
        SELECT p.token_address, p.source_dataset, p.pool_address, p.protocol,
               p.token0, p.token1, p.creation_timestamp
        FROM pool_entities p
        JOIN graph_targets t USING (token_address, source_dataset)
        WHERE p.pool_scope_complete
          AND p.creation_timestamp IS NOT NULL
          AND TRY_CAST(p.creation_timestamp AS TIMESTAMPTZ) <= t.cutoff
        ORDER BY p.token_address, p.source_dataset, p.protocol, p.pool_address
        """,
    )
    event_rows = _rows(
        connection,
        """
        SELECT e.token_address, e.source_dataset, e.pool_address, e.protocol,
               COUNT(*) AS event_count,
               COUNT(*) FILTER (WHERE e.event_type = 'swap') AS swap_count,
               COUNT(*) FILTER (WHERE e.event_type = 'mint') AS mint_count,
               COUNT(*) FILTER (WHERE e.event_type = 'burn') AS burn_count,
               COALESCE(SUM(CASE WHEN e.event_type = 'swap'
                                  THEN TRY_CAST(e.amount_usd AS DOUBLE) ELSE 0 END), 0) AS volume_usd,
               COUNT(DISTINCT CAST(DATE_TRUNC('day', TRY_CAST(e.block_timestamp AS TIMESTAMPTZ)) AS DATE)) AS active_day_count
        FROM normalized_events e
        JOIN graph_targets t USING (token_address, source_dataset)
        WHERE e.block_timestamp IS NOT NULL
          AND TRY_CAST(e.block_timestamp AS TIMESTAMPTZ) >= t.t0
          AND TRY_CAST(e.block_timestamp AS TIMESTAMPTZ) <= t.cutoff
        GROUP BY e.token_address, e.source_dataset, e.pool_address, e.protocol
        ORDER BY e.token_address, e.source_dataset, e.protocol, e.pool_address
        """,
    )
    quality = _rows(
        connection,
        """
        SELECT
          COUNT(*) AS pool_rows_total,
          COUNT(*) FILTER (WHERE p.creation_timestamp IS NULL) AS pool_rows_missing_creation,
          COUNT(*) FILTER (WHERE p.creation_timestamp IS NOT NULL AND TRY_CAST(p.creation_timestamp AS TIMESTAMPTZ) > t.cutoff) AS pool_rows_post_cutoff,
          COUNT(*) FILTER (WHERE p.creation_timestamp IS NOT NULL AND TRY_CAST(p.creation_timestamp AS TIMESTAMPTZ) <= t.cutoff) AS pool_rows_pre_cutoff
        FROM pool_entities p
        JOIN graph_targets t USING (token_address, source_dataset)
        """,
    )[0]
    event_quality = _rows(
        connection,
        """
        SELECT
          COUNT(*) AS event_rows_total,
          COUNT(*) FILTER (WHERE e.block_timestamp IS NULL) AS event_rows_missing_timestamp,
          COUNT(*) FILTER (WHERE e.block_timestamp IS NOT NULL AND TRY_CAST(e.block_timestamp AS TIMESTAMPTZ) < t.t0) AS event_rows_pre_t0,
          COUNT(*) FILTER (WHERE e.block_timestamp IS NOT NULL AND TRY_CAST(e.block_timestamp AS TIMESTAMPTZ) > t.cutoff) AS event_rows_post_cutoff,
          COUNT(*) FILTER (WHERE e.block_timestamp IS NOT NULL AND TRY_CAST(e.block_timestamp AS TIMESTAMPTZ) >= t.t0 AND TRY_CAST(e.block_timestamp AS TIMESTAMPTZ) <= t.cutoff) AS event_rows_in_window
        FROM normalized_events e
        JOIN graph_targets t USING (token_address, source_dataset)
        """,
    )[0]
    connection.close()

    pools_by_target: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in pool_rows:
        key = (lower(row["token_address"]), str(row["source_dataset"]))
        pools_by_target[key].append(row)
    event_stats: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in event_rows:
        key = (
            lower(row["token_address"]),
            str(row["source_dataset"]),
            lower(row["pool_address"]),
            lower(row["protocol"]),
        )
        event_stats[key] = row

    graph_path = output / "graphs.jsonl"
    counts = Counter()
    total_nodes = 0
    total_edges = 0
    total_pool_events = 0
    with graph_path.open("w", encoding="utf-8") as handle:
        for target in targets:
            key = (target["token_address"], target["source_dataset"])
            graph = graph_for_target(target, pools_by_target.get(key, []), event_stats)
            handle.write(json.dumps(graph, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")
            counts[target["graph_role"]] += 1
            counts[f"partition:{target.get('partition')}"] += 1
            counts[f"label:{target.get('label')}"] += 1
            if graph["stats"]["pool_count"] == 0:
                counts["empty_graphs"] += 1
            total_nodes += graph["stats"]["node_count"]
            total_edges += graph["stats"]["edge_count"]
            total_pool_events += graph["stats"]["window_event_count"]

    manifest = {
        "manifest_version": "static-ego-graph-0.1",
        "database": str(database),
        "targets": str(Path(args.targets).resolve()) if args.targets else None,
        "cohort": str(Path(args.cohort).resolve()) if args.cohort else None,
        "holdout": str(Path(args.holdout).resolve()) if args.holdout else None,
        "output": str(graph_path),
        "target_rows": len(targets),
        "graph_rows": sum(counts[key] for key in ("development", "test_holdout")),
        "role_counts": {key: counts[key] for key in ("development", "test_holdout")},
        "partition_counts": {
            key.removeprefix("partition:"): value
            for key, value in counts.items()
            if key.startswith("partition:")
        },
        "label_counts": {
            key.removeprefix("label:"): value
            for key, value in counts.items()
            if key.startswith("label:")
        },
        "empty_graphs": counts["empty_graphs"],
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "total_window_pool_events": total_pool_events,
        "node_feature_names": NODE_FEATURE_NAMES,
        "temporal_contract": {
            "pool_creation": "creation_timestamp <= target.cutoff",
            "event_window": "target.t0 <= block_timestamp <= target.cutoff",
            "post_cutoff_pool_rows_excluded": int(quality["pool_rows_post_cutoff"]),
            "post_cutoff_event_rows_not_used": int(event_quality["event_rows_post_cutoff"]),
            "missing_event_timestamps_not_used": int(event_quality["event_rows_missing_timestamp"]),
        },
        "source_quality": {
            "pool_rows_total_for_targets": int(quality["pool_rows_total"]),
            "pool_rows_missing_creation": int(quality["pool_rows_missing_creation"]),
            "pool_rows_pre_cutoff": int(quality["pool_rows_pre_cutoff"]),
            "event_rows_total_for_targets": int(event_quality["event_rows_total"]),
            "event_rows_in_window": int(event_quality["event_rows_in_window"]),
            "event_rows_pre_t0": int(event_quality["event_rows_pre_t0"]),
        },
    }
    (output / "feature_schema.json").write_text(
        json.dumps({"node_feature_names": NODE_FEATURE_NAMES}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "graph_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--database", required=True)
    target_group = result.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--targets")
    target_group.add_argument("--cohort")
    result.add_argument("--holdout")
    result.add_argument("--output", required=True)
    return result


if __name__ == "__main__":
    print(json.dumps(build(parser().parse_args()), indent=2, sort_keys=True))
