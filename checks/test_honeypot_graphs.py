"""Source-specific cutoff plans and real offline collector-to-graph checks."""
from contextlib import redirect_stdout, redirect_stderr
import copy
import io
import json
from pathlib import Path
import unittest
import threading
import os
from unittest.mock import patch

from checks import test_honeypot_pipeline as evidence_fixtures
from checks.test_honeypot_pipeline import addr
from packages.collection import CollectionError, EtherscanClient
from packages.graph import build_graph_sample, graph_is_usable, graph_recipe
from packages.io import read_records, write_records, load_json, sha256_file
from packages.io import save_json
from packages.token import UNISWAP_V2_FACTORY, TOKEN_RECENT_VIEW_VERSION
from packages.token_recent import latest_logs
from packages.transactions import TRANSFER_TOPIC
from research.scam.honeypot_graphs import run_graphs
from research.scam.honeypot import _digest
from research.scam.honeypot_training import prepare_training
from packages.observations import ObservationStore
from research.scam.pipeline import main as runner


class HoneypotGraphTests(unittest.TestCase):
    setUp = evidence_fixtures.HoneypotPipelineTests.setUp
    prepare = evidence_fixtures.HoneypotPipelineTests.prepare
    discover = evidence_fixtures.HoneypotPipelineTests.discover

    def ready(self):
        self.discover(6)
        self.prepare("label")

    def verify(self, targets, out, settings):
        verified = []
        for original in targets:
            target = copy.deepcopy(original)
            target.update(end_block=target["cutoff_block"],
                          token_metadata={"decimals": 18, "verified_at_block": target["cutoff_block"], "evidence_ref": "synthetic://decimals"},
                          pool_metadata=[{"pool": p, "token0": target["target"],
                                          "token1": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                                          "factory": UNISWAP_V2_FACTORY, "verified_at_block": target["cutoff_block"],
                                          "evidence_ref": "synthetic://pair"} for p in target["pools"]])
            verified.append(target)
        write_records(Path(out) / "verified_targets.jsonl", verified)
        return {"status": "verified"}

    def chain(self, query):
        if query["action"] == "getblocknobytime":
            return {"status": "1", "result": "200"}
        if query["action"] != "getLogs":
            return {"status": "1", "result": []}
        selected = read_records(self.out / "discovery/targets.jsonl")
        token = next((r for r in selected if r["target"] == query["address"]), None)
        if token is None:
            return {"status": "1", "result": []}
        checked = next(r for r in read_records(self.out / "contemporary/labels.jsonl") if r["sample_id"] == token["sample_id"])
        if not query["fromBlock"] <= 150 <= query["toBlock"]:
            return {"status": "1", "result": []}
        return {"status": "1", "result": [{"address": token["target"], "blockNumber": "0x96",
                "timeStamp": str(checked["cutoff"] - 1), "transactionHash": "0x" + "1" * 64, "logIndex": "0x0",
                "topics": [TRANSFER_TOPIC, "0x" + addr(99)[2:].rjust(64, "0"), "0x" + token["pools"][0][2:].rjust(64, "0")],
                "data": "0x" + f"{10**18:064x}"}]}

    def graphs(self, **kwargs):
        return run_graphs(self.out, stage="graphs", settings={"collection": {"transport": self.chain}}, progress="off", **kwargs)

    def test_plan_uses_each_frozen_capture_and_does_not_admit_labels(self):
        self.discover(6)
        with patch("packages.token_sources.time.time", side_effect=range(1792490000, 1792490006)):
            self.prepare("label")
        result = run_graphs(self.out, stage="plan", dry_run=True)
        self.assertEqual(result["target_count"], 6)
        self.assertFalse((self.out / "graph_runs").exists())
        run_graphs(self.out, stage="plan")
        targets = read_records(self.out / "graph_runs/recent-v1/targets.jsonl")
        captures = {r["sample_id"]: r for r in read_records(self.out / "contemporary/labels.jsonl")}
        self.assertEqual(len({t["cutoff"] for t in targets}), 6)
        self.assertTrue(all(t["cutoff"] == captures[t["sample_id"]]["checked_at"] for t in targets))
        self.assertTrue(all("candidate_label" not in t for t in targets))
        with self.assertRaisesRegex(ValueError, "inputs_changed"):
            run_graphs(self.out, stage="plan", limit=2)

    def test_historical_anchor_explicit_and_does_not_rewrite_validity(self):
        self.ready()
        with self.assertRaisesRegex(ValueError, "historical-cutoff"):
            run_graphs(self.out, stage="plan", cohort="historical", dry_run=True)
        run_graphs(self.out, stage="plan", graph_run="both", cohort="both", historical_cutoff="2023-01-31T23:59:59Z")
        rows = read_records(self.out / "graph_runs/both/targets.jsonl")
        historical = [r for r in rows if r["source_cohort"] == "historical"]
        self.assertEqual(len(historical), 4)
        self.assertTrue(all(r["cutoff"] == 1675209599 for r in historical))
        labels = read_records(self.out / "graph_runs/both/candidate_labels.jsonl")
        self.assertTrue(all(r["valid_from"] is None for r in labels if r["source"] == "trapdoor"))
        with self.assertRaisesRegex(ValueError, "timezone"):
            run_graphs(self.out, stage="plan", graph_run="invalid", cohort="historical", historical_cutoff="2023-01-31")

    def test_complete_offline_pipeline_and_replay_without_providers(self):
        self.ready()
        with patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=self.verify):
            report = self.graphs()
        self.assertEqual(report["graph_count"], 6)
        root = self.out / "graph_runs/recent-v1"
        graphs = read_records(root / "graphs.jsonl")
        for graph in graphs:
            self.assertTrue(graph_is_usable(graph))
            self.assertEqual(graph["graph_view_version"], TOKEN_RECENT_VIEW_VERSION)
            self.assertFalse(graph["quality"]["full_history_complete"])
            self.assertEqual(graph_recipe(graph)["sampling"]["pages_per_action"], 3)
        digest = sha256_file(root / "graphs.jsonl")
        with patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=AssertionError("reverify")), patch("packages.collection.urlopen", side_effect=AssertionError("requery")):
            self.graphs()
        self.assertEqual(digest, sha256_file(root / "graphs.jsonl"))
        modified = copy.deepcopy(graphs[0])
        modified["quality"]["collection_coverage"]["full_history_complete"] = True
        self.assertFalse(graph_is_usable(modified))

    def test_local_failures_drop_and_fatal_auth_stops(self):
        self.ready()
        first = read_records(self.out / "discovery/targets.jsonl")[0]["sample_id"]
        def failure(targets, out, settings):
            if targets[0]["sample_id"] == first:
                raise ValueError("invalid_decimals_abi")
            return self.verify(targets, out, settings)
        with patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=failure):
            result = self.graphs()
        self.assertEqual(result["graph_count"], 5)
        self.assertEqual(result["status_counts"]["excluded_sample_failure"], 1)
        with patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=CollectionError("Invalid API Key")):
            with self.assertRaisesRegex(CollectionError, "API Key"):
                self.graphs(graph_run="fatal")

    def test_strict_failure_can_resume_and_graphs_require_prior_stage(self):
        self.ready()
        settings = {"collection": {"transport": self.chain}}
        with patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=ValueError("bad_decimals")):
            result = run_graphs(self.out, stage="graphs", settings=settings, drop_failed=False, progress="off")
        self.assertEqual(result["status"], "collection_incomplete")
        with patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=self.verify):
            self.assertEqual(self.graphs()["graph_count"], 6)
        run_graphs(self.out, stage="plan", graph_run="unverified")
        with self.assertRaisesRegex(ValueError, "run_verify_stage"):
            run_graphs(self.out, stage="collect", settings=settings, graph_run="unverified", progress="off")

    def test_runner_graph_plan_and_dry_run_no_network(self):
        self.ready()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            args = ["--task", "honeypot", "--snapshot", "test", "--output", str(self.out), "--stage", "collect"]
            self.assertEqual(runner(args + ["--dry-run"]), 0)
            self.assertFalse((self.out / "graph_runs").exists())
            self.assertEqual(runner([*args[:-1], "plan"]), 2)

    def test_parallel_samples_share_rpc_client_and_etherscan_budget(self):
        self.ready()
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        clients, budgets, active, peak = set(), set(), [0], [0]
        def verify(targets, out, settings):
            with lock:
                clients.add(id(settings["_client"]))
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            barrier.wait(timeout=5)
            result = self.verify(targets, out, settings)
            with lock:
                active[0] -= 1
            return result
        original = EtherscanClient.__init__
        def initialize(client, out, settings=None, transport=None):
            original(client, out, settings, transport)
            with lock:
                budgets.add(id(client.budget))
        with patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=verify), \
             patch.object(EtherscanClient, "__init__", initialize):
            run_graphs(self.out, stage="verify", settings={"collection": {"transport": self.chain}}, progress="off")
        self.assertGreaterEqual(peak[0], 2)
        self.assertEqual(len(clients), 1)
        self.assertEqual(len(budgets), 1)

    def test_network_outage_stops_batch_without_excluding_cancelled_samples(self):
        self.ready()
        settings = {"collection": {"transport": self.chain}}
        with patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=self.verify):
            run_graphs(self.out, stage="verify", settings=settings, progress="off")
        with patch("research.scam.honeypot_graphs.collect_token_recent", side_effect=CollectionError(
                "<urlopen error [Errno 8] nodename nor servname provided, or not known>")):
            with self.assertRaisesRegex(CollectionError, "transient_provider_network_failure"):
                run_graphs(self.out, stage="collect", settings=settings, progress="off")
        root = self.out / "graph_runs/recent-v1"
        self.assertFalse(list((root / "samples").glob("*/collect.json")))
        state = load_json(root / "progress.json")
        self.assertEqual(state["active_samples"], {})
        self.assertEqual(state["stage_status"], "error")
        self.assertEqual(state["processed"], 0)
        self.assertEqual(run_graphs(self.out, stage="collect", settings=settings, progress="off")["status_counts"], {"collected": 6})

    def test_resume_archives_legacy_transport_exclusions_but_keeps_data_exclusions(self):
        self.ready()
        settings = {"collection": {"transport": self.chain}}
        with patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=self.verify):
            run_graphs(self.out, stage="verify", settings=settings, progress="off")
        root = self.out / "graph_runs/recent-v1"
        targets = read_records(root / "targets.jsonl")
        for target, reason in zip(targets[:2], ["provider_request_cancelled", "token_recent_normalization_failed_see_audit"]):
            result = {"sample_id": target["sample_id"], "input_sha256": _digest(target), "phase": "collect",
                "status": "excluded_sample_failure", "failure": reason}
            result["outcome_sha256"] = _digest(result)
            save_json(root / "samples" / target["sample_id"] / "collect.json", result)
        original = sha256_file(root / "samples" / targets[0]["sample_id"] / "collect.json")
        result = run_graphs(self.out, stage="collect", settings=settings, progress="off")
        self.assertEqual(result["status_counts"], {"collected": 5, "excluded_sample_failure": 1})
        archived = list((root / "samples" / targets[0]["sample_id"] / "attempts").glob("*transport-recovery*"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(sha256_file(archived[0]), original)
        self.assertEqual(load_json(root / "progress.json")["processed"], 6)
        self.assertTrue(list((root / "recovery").glob("transport-*.json")))

    def test_real_nested_renderer_is_used_and_animations_do_not_enter_logs(self):
        from research.scam.pipeline import Tee
        from packages.progress import NestedSampleProgress
        self.ready()
        console, logs = io.StringIO(), io.StringIO()
        with redirect_stderr(Tee(console, logs)), patch.object(console, "isatty", return_value=True), \
             patch.dict(os.environ, {"TERM": "xterm"}), patch.object(NestedSampleProgress, "_width", return_value=72), \
             patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=self.verify):
            result = run_graphs(self.out, stage="graphs", settings={"collection": {"transport": self.chain}}, progress="on")
        self.assertEqual(result["graph_count"], 6)
        self.assertIn("Samples", console.getvalue())
        self.assertIn("6/6", console.getvalue())
        self.assertIn("\x1b", console.getvalue())
        self.assertEqual(logs.getvalue(), "")

    def test_shared_replay_cleanup_and_second_run_reuses_observations(self):
        self.ready()
        class SyntheticStore(ObservationStore):
            def __init__(self, *args):
                super().__init__(*args)
                self.enabled = True
                self.origin = "synthetic-test-provider"
        settings = {"collection": {"transport": self.chain}, "observation_root": str(self.root / "observations")}
        with patch("research.scam.honeypot_graphs.ObservationStore", SyntheticStore), \
             patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=self.verify):
            result = run_graphs(self.out, stage="graphs", settings=settings, progress="off")
            self.assertEqual(result["graph_count"], 6)
            root = self.out / "graph_runs/recent-v1"
            samples = list((root / "samples").iterdir())
            self.assertTrue(all((s / "collection/observation_ref.json").exists() for s in samples))
            self.assertFalse(any((s / "collection/events.jsonl.gz").exists() for s in samples))
            self.assertFalse(any((s / "collection/raw_requests").exists() for s in samples))
            with patch("research.scam.honeypot_graphs.collect_token_recent", side_effect=AssertionError("unexpected download")):
                result = run_graphs(self.out, stage="graphs", graph_run="reuse", settings=settings, progress="off")
                self.assertEqual(result["graph_count"], 6)
            reference = load_json(samples[0] / "collection/observation_ref.json")
            (Path(reference["path"]) / "events.jsonl.gz").write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "checksum"):
                run_graphs(self.out, stage="collect", settings=settings, progress="off")

    def test_mixed_source_training_preparation_and_entity_grouping(self):
        from checks.test_honeypot_pipeline import pair_log, response
        positive = Path(self.settings["source_files"]["positive"])
        negative = Path(self.settings["source_files"]["negative"])
        positive.write_text("token_address,pool_address,type\n" + "".join(
            f"{addr(n)},{addr(n+1000)},conditional_asserting\n" for n in range(1, 13)) +
            f"{addr(1)},{addr(2001)},fee_manipulation\n")
        negative.write_text("token_address,pool_address\n" + "".join(
            f"{addr(n)},{addr(n+1000)}\n" for n in range(13, 25)))
        def discovery(query):
            if query["action"] == "getblocknobytime":
                return {"status": "1", "result": "100" if query["closest"] == "after" else "200"}
            return {"status": "1", "result": [] if "topic1" in query or query["page"] > 1 else [pair_log(n) for n in range(30, 36)]}
        self.settings["collection"].update(transport=discovery, page_size=1000)
        self.settings["honeypot"]["transport"] = lambda source, query: response(query, int(query["address"], 16) % 2 == 0)
        self.ready()
        settings = {"collection": {"transport": self.chain}, "graph_selection": {
            "cohort": "both", "historical_cutoff": "2023-01-31T23:59:59Z"}}
        run_graphs(self.out, stage="plan", settings=settings)
        root = self.out / "graph_runs/recent-v1"
        frozen = read_records(root / "targets.jsonl")
        def chain(query):
            if query["action"] == "getblocknobytime":
                return {"status": "1", "result": "200"}
            token = next((r for r in frozen if r["target"] == query.get("address")), None)
            if query["action"] != "getLogs" or not token or query["fromBlock"] > 150:
                return {"status": "1", "result": []}
            return {"status": "1", "result": [{"address": token["target"], "blockNumber": 150,
                "timeStamp": token["cutoff"]-1, "transactionHash": "0x" + "1" * 64, "logIndex": 0,
                "topics": [TRANSFER_TOPIC, "0x" + addr(999)[2:].rjust(64, "0"), "0x" + token["pools"][0][2:].rjust(64, "0")],
                "data": "0x" + f"{10**18:064x}"}]}
        settings["collection"]["transport"] = chain
        with patch("research.scam.honeypot_graphs.verify_token_targets", side_effect=self.verify):
            run_graphs(self.out, stage="graphs", settings=settings, progress="off")
        report = prepare_training(root)
        self.assertEqual(report["targets"], 31)
        self.assertEqual(report["selection"]["source_class_counts"], {"historical:1": 13, "historical:0": 12, "contemporary:0": 3, "contemporary:1": 3})
        supervision = read_records(root / "prepared/supervision.jsonl")
        self.assertTrue(all(r["eligible"] for r in supervision))
        self.assertTrue(all(r["valid_from"] is None for r in supervision if r["source_cohort"] == "historical"))
        splits = read_records(root / "prepared/splits.jsonl")
        self.assertEqual(len({r["partition"] for r in splits if r["entity_id"] == addr(1)}), 1)
        self.assertEqual(prepare_training(root)["inputs"], report["inputs"])
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(runner(["--task", "honeypot", "--snapshot", "test", "--output", str(self.out),
                "--graph-run", "recent-v1", "--stage", "train", "--run", "dry", "--dry-run"]), 0)
        graph = root / "prepared/graphs.jsonl"
        graph.write_text(graph.read_text()+"{}\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            prepare_training(root)


class LatestLogsTests(unittest.TestCase):
    def test_single_block_overflow_is_paged_before_newest_selection(self):
        def transport(query):
            indices = list(range(1200))[(query["page"] - 1) * 1000:query["page"] * 1000]
            return {"status": "1", "result": [{"address": addr(1), "blockNumber": 0,
                    "timeStamp": 1, "transactionHash": "0x" + f"{i:064x}", "logIndex": hex(i)} for i in indices]}
        import tempfile
        with tempfile.TemporaryDirectory() as out:
            client = EtherscanClient(out, {"transport": transport})
            rows, _ = latest_logs(client, addr(1), 0, 100, 100, initial_span=1)
        self.assertEqual([int(r["logIndex"], 16) for r in rows], list(range(1199, 1099, -1)))

    def test_newest_ranges_not_first_ascending_page(self):
        queries = []
        def transport(query):
            queries.append(query)
            blocks = list(range(max(1, query["fromBlock"]), min(2100, query["toBlock"]) + 1))
            blocks = blocks[(query["page"] - 1) * query["offset"]:query["page"] * query["offset"]]
            return {"status": "1", "result": [{"address": addr(1), "blockNumber": b,
                    "timeStamp": b, "transactionHash": "0x" + f"{b:064x}", "logIndex": "0x0"} for b in blocks]}
        import tempfile
        with tempfile.TemporaryDirectory() as out:
            client = EtherscanClient(out, {"transport": transport})
            rows, _ = latest_logs(client, addr(1), 2100, 100000, 100, initial_span=5000)
        self.assertEqual([r["blockNumber"] for r in rows], list(range(2100, 2000, -1)))
        self.assertTrue(any(q["fromBlock"] > 0 for q in queries))


if __name__ == "__main__":
    unittest.main()
