#!/usr/bin/env python3
"""Verify and compact existing bounded-recent replay inputs without API calls."""
import argparse
import json
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.scam.compaction import compact_snapshot
from research.scam.storage import dataset_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="phishing")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--dry-run", action="store_true", help="verify and report without migrating")
    parser.add_argument("--progress", choices=("on", "off"), default="on")
    args = parser.parse_args()
    last = 0.0

    def progress(phase, done, total):
        nonlocal last
        now = time.monotonic()
        if now - last >= 5 or done == total:
            print(f"[storage] {phase}: {done}/{total}", file=sys.stderr, flush=True)
            last = now
    try:
        result = compact_snapshot(dataset_path(args.task, args.snapshot), dry_run=args.dry_run,
                                  progress=progress if args.progress == "on" else None)
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "resume": "repeat the same command"}), file=sys.stderr)
        return 130
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "error", "reason": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
