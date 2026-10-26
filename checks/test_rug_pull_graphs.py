"""Frozen Rug Pull targets through real collection, normalization and graphs."""
from contextlib import redirect_stdout, redirect_stderr
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.collection import CollectionError
from packages.graph import graph_is_usable
from packages.io import load_json, read_records, save_json, sha256_file, write_records
from packages.token import UNISWAP_V2_FACTORY
from packages.transactions import TRANSFER_TOPIC
from research.scam.rug_pull import _manifest, prepare_rug_pull
from research.scam.rug_pull_graphs import run_graphs
from research.scam.pipeline import main as runner


def addr(n):
    return f"0x{n:040x}"


class RugPullGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "snapshot"
        self.targets, labels = [], []
        for n in range(1, 4):
            target = {"sample_id": f"ts-{n}", "task_id": "rug_pull", "chain_id": 1,
                "target": addr(n), "pools": [addr(n + 1000)], "cutoff": 1677628799,
                "cutoff_block": 200, "end_block": 200, "cutoff_block_hash": "0x" + "1" * 64,
                "token_metadata": {"decimals": 18, "verified_at_block": 200, "evidence_ref": "synthetic://decimals"},
                "pool_metadata": [{"pool": addr(n + 1000), "token0": addr(n), "token1": addr(999),
                    "factory": UNISWAP_V2_FACTORY, "verified_at_block": 200, "evidence_ref": "synthetic://pair"}]}
            self.targets.append(target)
            labels.append({"sample_id": target["sample_id"], "token_address": target["target"],
                "pool_addresses": target["pools"], "cutoff": target["cutoff"], "pool_verified": True,
                "label": int(n < 3), "training_eligible": False, "incident_onset": None})
        paths = [self.out / "pools/verified_targets.jsonl", self.out / "labels/verified_labels.jsonl"]
        write_records(paths[0], self.targets)
        write_records(paths[1], labels)
        _manifest(self.out / "pools/verification_manifest.json", paths, verified_tokens=3)
        self.calls = []
        self.settings = {"observation_root": str(Path(self.tmp.name) / "observations"),
            "collection": {"transport": self.chain}}

    def chain(self, query):
        self.calls.append(query)
        self.assertNotEqual(query["action"], "getblocknobytime")
        if query["action"] != "getLogs" or query["address"] not in {t["target"] for t in self.targets}:
            return {"status": "1", "result": []}
        n = int(query["address"], 16)
        if not query["fromBlock"] <= 150 <= query["toBlock"]:
            return {"status": "1", "result": []}
        return {"status": "1", "result": [{"address": addr(n), "blockNumber": "0x96",
            "timeStamp": "1677628798", "transactionHash": "0x" + f"{n:064x}", "logIndex": "0x0",
            "topics": [TRANSFER_TOPIC, "0x" + addr(99)[2:].rjust(64, "0"),
                "0x" + addr(n + 1000)[2:].rjust(64, "0")], "data": "0x" + f"{10**18:064x}"}]}

    def run_graphs(self, stage, **options):
        return run_graphs(self.out, stage=stage, settings=self.settings, progress="off", **options)

    def test_plan_is_offline_label_free_and_reuses_verified_metadata(self):
        self.assertEqual(self.run_graphs("plan", dry_run=True)["target_count"], 3)
        self.assertFalse((self.out / "graph_runs").exists())
        self.run_graphs("plan")
        root = self.out / "graph_runs/recent-v1"
        self.assertEqual(read_records(root / "targets.jsonl"), self.targets)
        self.assertEqual(load_json(root / "plan.json")["label_counts"], {"1": 2, "0": 1})
        self.assertTrue(all(load_json(root / "samples" / t["sample_id"] / "verify.json")["status"] == "verified" for t in self.targets))
        self.assertEqual(self.calls, [])
        with self.assertRaisesRegex(ValueError, "inputs_changed"):
            self.run_graphs("plan", limit=1)
        self.assertEqual(self.run_graphs("plan", graph_run="pilot", limit=1)["target_count"], 1)

    def test_real_collector_to_graph_and_cache_only_resume(self):
        secondary = Path(self.tmp.name) / "secondary.sqlite3"
        with patch.dict(os.environ, {"ETHERSCAN_QUOTA_FILE": str(secondary), "ETHEREUM_RPC_URL": ""}), patch(
                "research.scam.honeypot_graphs.verify_token_targets", side_effect=AssertionError("must not reverify")):
            collected = self.run_graphs("collect")
            self.assertEqual(collected["status_counts"], {"collected": 3})
            root = self.out / "graph_runs/recent-v1"
            self.assertFalse((root / "graphs.jsonl").exists())
            self.assertEqual(load_json(root / "progress.json")["quota_file"], str(secondary.resolve()))
            report = self.run_graphs("build-graphs")
            self.assertEqual(report["graph_count"], 3)
            for graph in read_records(root / "graphs.jsonl"):
                self.assertEqual(graph["task_id"], "rug_pull")
                self.assertTrue(graph_is_usable(graph))
                self.assertNotIn("label", graph)
            self.assertEqual(load_json(root / "graph_manifest.json")["version"], "rug_pull-graphs-1")
            digest, calls = sha256_file(root / "graphs.jsonl"), len(self.calls)
            self.run_graphs("graphs")
            self.assertEqual((digest, calls), (sha256_file(root / "graphs.jsonl"), len(self.calls)))
            self.assertFalse(report["training_started"])

    def test_modified_source_is_rejected(self):
        self.run_graphs("plan")
        write_records(self.out / "labels/verified_labels.jsonl", [])
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.run_graphs("collect")
        self.assertEqual(self.calls, [])

    def test_fatal_provider_failure_stops_without_changing_cohort(self):
        self.settings["collection"]["transport"] = lambda q: (_ for _ in ()).throw(CollectionError("Invalid API Key"))
        with self.assertRaisesRegex(CollectionError, "API Key"):
            self.run_graphs("collect")
        root = self.out / "graph_runs/recent-v1"
        self.assertFalse(list(root.glob("samples/*/collect.json")))
        self.settings["collection"]["transport"] = self.chain
        self.assertEqual(self.run_graphs("collect")["target_count"], 3)

    def test_runner_dry_run_then_cli_plan_and_graph_dispatch(self):
        args = ["--task", "rug_pull", "--snapshot", "test", "--output", str(self.out)]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(runner(args + ["--stage", "collect", "--dry-run"]), 0)
            self.assertFalse((self.out / "graph_runs").exists())
            self.assertEqual(runner(args + ["--stage", "plan"]), 2)
            self.assertEqual(runner(args + ["--stage", "collect", "--positive-count", "1", "--dry-run"]), 2)
        commands = []
        with patch("research.scam.pipeline.invoke", side_effect=lambda c, *a: (commands.append(c) or (0, {}, ""))), redirect_stdout(io.StringIO()):
            self.assertEqual(runner(args + ["--stage", "collect", "--graph-run", "formal", "--strict-collection"]), 0)
        self.assertIn("formal", commands[0])
        self.assertIn("--strict-collection", commands[0])
        self.assertEqual(commands[0][commands[0].index("--stage") + 1], "graphs")

    def test_changed_cutoff_or_selection_is_forbidden_during_collection(self):
        with self.assertRaisesRegex(ValueError, "frozen_verified"):
            prepare_rug_pull(self.out, stage="collect", historical_cutoff=1, dry_run=True)
