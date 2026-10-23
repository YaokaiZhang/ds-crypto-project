"""Canonical offline artifact locations; paths never imply label validity."""
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_ETHERSCAN_CACHE = PROJECT_ROOT / "data/shared/etherscan/ethereum"
SHARED_ADDRESS_POOLS = PROJECT_ROOT / "data/shared/address_pools/ethereum"
SHARED_OBSERVATIONS = PROJECT_ROOT / "data/shared/observations/ethereum"
PONZI_SOURCE_SNAPSHOT = PROJECT_ROOT / "data/scam/ponzi/xblock-unica-recent-v1/sources"


def checked_name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("snapshot/run must be a short name without path separators")
    return value


def dataset_path(task, snapshot):
    from packages.tasks import canonical_task
    return PROJECT_ROOT / "data/scam" / canonical_task(task) / checked_name(snapshot)


def model_path(task, snapshot, run):
    from packages.tasks import canonical_task
    return PROJECT_ROOT / "artifacts/scam" / canonical_task(task) / checked_name(snapshot) / checked_name(run)


def background_path(cutoff, seed, blocks):
    return PROJECT_ROOT / "data/shared/address_pools/ethereum" / f"historical-v1-{cutoff}-{seed}-{blocks}"
