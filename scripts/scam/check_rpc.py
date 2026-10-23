"""Check local Ethereum RPC credentials and historical EIP-1898 reads."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.collection import CollectionError
from packages.provider_access import ethereum_rpc_url
from packages.token_sources import SnapshotClient


def main():
    if not ethereum_rpc_url():
        raise ValueError("set_ETHEREUM_RPC_URL_in_local_secrets.py")
    client = SnapshotClient(".runtime/ethereum-rpc/probe", {"allow_network": True, "retries": 1})
    def rpc(method, params):
        return client.request("ethereum_rpc", {"method": method, "params": params})["response"]["result"]
    if int(rpc("eth_chainId", []), 16) != 1:
        raise CollectionError("ethereum_mainnet_only")
    # A block from January 2023, near the historical Trapdoor anchor.
    header = rpc("eth_getBlockByNumber", [hex(16500000), False])
    result = rpc("eth_call", [{"to": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "data": "0x313ce567"},
        {"blockHash": header["hash"], "requireCanonical": True}])
    if int(result, 16) != 18:
        raise CollectionError("unexpected_historical_WETH_decimals")
    print(json.dumps({"status": "passed", "chain_id": 1, "historical_block": int(header["number"], 16),
        "historical_timestamp": int(header["timestamp"], 16), "historical_eth_call": True,
        "EIP_1898_blockHash_requireCanonical": True}))


if __name__ == "__main__":
    try:
        main()
    except (CollectionError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
