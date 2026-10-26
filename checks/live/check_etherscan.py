#!/usr/bin/env python3
"""Verify the local key and all Phishing API actions with at most three calls."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from packages.collection import EtherscanClient, CollectionError
from packages.io import load_json, read_records, save_json
from packages.provider_access import REQUESTS_PER_24H
from research.scam.storage import dataset_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default="forta-2022-v2")
    args = parser.parse_args(argv)
    out = dataset_path("phishing", args.snapshot)
    try:
        contract = load_json(out / "cohort/manifest.json")
        target = next(row for row in read_records(out / "cohort/targets.jsonl") if not row["background_selected"])
        # New cache per invocation ensures this checks the current credential.
        probe = PROJECT_ROOT / ".runtime/etherscan/probes" / uuid.uuid4().hex
        client = EtherscanClient(probe, {"allow_network": True, "max_requests": 3, "retries": 0})
        end_block = client.block_by_time(contract["cohort"]["cutoff"])
        actions = {}
        for action in ("txlist", "txlistinternal"):
            bundle = client.request("account", action, address=target["target"], startblock=0,
                                    endblock=end_block, page=1, offset=1, sort="asc")
            actions[action] = {"status": "ok", "records": len(bundle["response"].get("result") or [])}
        report = {"status": "connection_verified", "checked_at": datetime.now(timezone.utc).isoformat(),
                  "snapshot": args.snapshot, "chain_id": 1, "cutoff_block": end_block,
                  "actions": actions, "network_attempts": client.request_count,
                  "rate_limit_rps": client.rate, "rolling_24h_limit": REQUESTS_PER_24H,
                  "dataset_collection_started": False}
        save_json(out / "etherscan_check.json", report)
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError, KeyError, StopIteration, CollectionError) as error:
        print(json.dumps({"status": "connection_failed", "reason": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
