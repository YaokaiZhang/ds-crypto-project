"""Source-label quality, real metadata-verifier replay, and no-collection boundary."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.collection import CollectionError
from packages.io import load_json, read_records, sha256_file
from packages.token import UNISWAP_V2_FACTORY
from research.scam.rug_pull import BatchSnapshotClient, PAIR_TOPIC, WETH, ZERO, _call, prepare_rug_pull
from research.scam.pipeline import main as runner


def addr(n):
    return f"0x{n:040x}"


def word(value):
    return "0x" + (value[2:].rjust(64, "0") if isinstance(value, str) else f"{value:064x}")


class RugPullPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "snapshot"
        labels = self.root / "labels.csv"
        labels.write_text("tokens,t1-labels,t2-labels\n1,scam,rugpull\n11,scam,rugpull\n"
                          "2,truthworthy,truthworthy\n3,scam,honeypot\n4,scam,rugpull\n"
                          "14,truthworthy,truthworthy\n99,scam,rugpull\n5,scam,rugpull\n"
                          "6,scam,rugpull\n7,scam,rugpull\n")
        mapping = self.root / "mapping.json"
        mapping.write_text(json.dumps({"1": addr(1), "11": addr(1), "2": addr(2), "3": addr(3),
                                       "4": addr(4), "14": addr(4), "5": "bad", "6": addr(6), "7": addr(7)}))
        self.rpc_calls, self.chain_calls = [], []

        def rpc(source, query):
            self.rpc_calls.append(query)
            method = query["method"]
            if method == "eth_chainId":
                return {"result": "0x1"}
            if method == "eth_getBlockByNumber":
                return {"result": {"number": "0xc8", "timestamp": "0x3e8", "hash": "0x" + "1" * 64}}
            self.assertEqual(method, "eth_call")
            call, tag = query["params"]
            self.assertEqual(tag, {"blockHash": "0x" + "1" * 64, "requireCanonical": True})
            entity, data = call["to"], call["data"]
            if entity == UNISWAP_V2_FACTORY:
                a, b = "0x" + data[34:74], "0x" + data[98:138]
                token = b if a == WETH else a
                return {"result": word(ZERO if token == addr(6) else addr(1000 + int(token, 16)))}
            if data == "0x313ce567":
                return {"error": {"code": 3, "message": "execution reverted"}} if entity == addr(7) else {"result": word(18)}
            root = addr(int(entity, 16) - 1000)
            values = {"0x0dfe1681": root, "0xd21220a7": WETH, "0xc45a0155": UNISWAP_V2_FACTORY}
            return {"result": word(values[data])}

        def chain(query):
            self.chain_calls.append(query)
            self.assertEqual(query["action"], "getblocknobytime")
            return {"status": "1", "result": "200"}

        self.settings = {"source_files": {"labels": str(labels), "mapping": str(mapping)},
                         "selection": {"positive_count": None, "selection_stage": "before_pool"}, "pools": {"cutoff": 2000, "scope": "weth"},
                         "collection": {"transport": chain}, "rpc": {"transport": rpc}}

    def prepare(self, stage, **kwargs):
        return prepare_rug_pull(self.out, stage=stage, settings=self.settings, progress="off", **kwargs)

    def test_mapping_cleanup_conflicts_and_source_specific_negative(self):
        self.prepare("sources")
        self.prepare("audit")
        counts = load_json(self.out / "labels/quality_audit.json")
        self.assertEqual(counts["raw_rows"], 10)
        self.assertEqual(counts["unmapped_rows"], 2)
        self.assertEqual(counts["duplicate_rows"], 1)
        self.assertEqual(counts["conflicting_addresses"], 1)
        self.assertEqual(counts["other_label_rows_excluded"], 1)
        rows = read_records(self.out / "labels/cleaned_labels.jsonl")
        self.assertEqual({r["token_address"] for r in rows}, {addr(1), addr(2), addr(6), addr(7)})
        self.assertEqual(next(r["label"] for r in rows if r["token_address"] == addr(2)), 0)
        self.assertTrue(all(r["incident_tx"] is None and r["label_available_at"] is None for r in rows))
        self.settings["selection"]["positive_count"] = 1
        with self.assertRaisesRegex(ValueError, "inputs_changed"):
            self.prepare("audit")

    def test_complete_preparation_replays_shared_verifier_without_histories(self):
        result = self.prepare("all")
        self.assertEqual(result["status"], "labels_ready")
        report = load_json(self.out / "label_quality_summary.json")
        self.assertEqual(report["pools"]["matched_tokens"], 3)
        self.assertEqual(report["verification"]["verified_tokens"], 2)
        self.assertEqual(report["verification"]["rejected_tokens"], 1)
        self.assertEqual(report["verification"]["verified_label_counts"], {"1": 1, "0": 1})
        self.assertFalse(report["transaction_history_collected"])
        self.assertFalse(report["training_started"])
        targets = read_records(self.out / "pools/verified_targets.jsonl")
        self.assertTrue(all(t["token_metadata"]["decimals"] == 18 for t in targets))
        self.assertTrue(all(t["pool_metadata"][0]["factory"] == UNISWAP_V2_FACTORY for t in targets))
        calls = len(self.rpc_calls), len(self.chain_calls)
        self.prepare("all")
        self.assertEqual(calls, (len(self.rpc_calls), len(self.chain_calls)))
        self.assertFalse(list(self.out.rglob("events.jsonl")))
        self.assertFalse(list(self.out.rglob("graphs.jsonl")))

    def test_ambiguous_mapping_id_is_excluded(self):
        Path(self.settings["source_files"]["mapping"]).write_text(json.dumps({addr(1): 1, addr(9): 1, addr(2): 2}))
        self.prepare("sources")
        self.prepare("audit")
        counts = load_json(self.out / "labels/quality_audit.json")
        self.assertEqual(counts["mapping"]["ambiguous_ids"], 1)
        self.assertNotIn(addr(1), {r["token_address"] for r in read_records(self.out / "labels/cleaned_labels.jsonl")})

    def test_no_write_dry_run_and_training_requires_explicit_run(self):
        self.prepare("all", dry_run=True)
        self.assertFalse(self.out.exists())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(runner(["--task", "rug_pull", "--snapshot", "test", "--output", str(self.out),
                                     "--stage", "all", "--run", "dry", "--dry-run"]), 0)
            for stage in ("train",):
                self.assertEqual(runner(["--task", "rug_pull", "--snapshot", "test", "--output", str(self.out),
                                         "--stage", stage]), 2)
        self.assertFalse(self.out.exists())

    def test_source_changes_and_rpc_cache_corruption_are_rejected(self):
        self.prepare("all")
        raw = next((self.out / "pools/rpc/raw_requests").glob("*.json"))
        data = load_json(raw)
        data["response_sha256"] = "changed"
        raw.write_text(json.dumps(data))
        query = data["request"]
        with self.assertRaisesRegex(CollectionError, "invalid_snapshot_cache"):
            BatchSnapshotClient(self.out / "pools/rpc").prefetch([query])
        Path(self.settings["source_files"]["labels"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "source_file_changed"):
            self.prepare("sources")

    def test_provider_errors_never_become_bad_token_labels(self):
        settings = {"transport": lambda source, query: {"error": {"code": -32005, "message": "rate limit"}}}
        client = BatchSnapshotClient(self.root / "rpc", settings)
        with self.assertRaisesRegex(CollectionError, "provider_error"):
            client.prefetch([_call(addr(1), "0x313ce567", "0xc8")])
        self.assertFalse(list((self.root / "rpc/raw_requests").glob("*.json")))
        self.assertFalse(list((self.root / "rpc/batches").glob("*.json")))
        self.assertEqual(load_json(self.root / "rpc/provider_error.json")["code"], -32005)

    def test_selection_after_verification_refills_failed_positive_and_keeps_all_negatives(self):
        from research.scam.rug_pull import _digest
        label_path = Path(self.settings["source_files"]["labels"])
        label_path.write_text(label_path.read_text() + "8,scam,rugpull\n")
        mapping_path = Path(self.settings["source_files"]["mapping"])
        mapping = load_json(mapping_path)
        mapping["8"] = addr(8)
        mapping_path.write_text(json.dumps(mapping))
        seed = next(s for s in range(1000) if sorted([1, 7, 8], key=lambda n: _digest([s, addr(n)]))[0] == 7)
        self.settings["selection"] = {"positive_count": 2, "selection_stage": "after_pool_verification", "seed": seed}
        self.prepare("all")
        report = load_json(self.out / "label_quality_summary.json")
        self.assertEqual(report["verification"]["verified_label_counts"], {"1": 2, "0": 1})
        self.assertEqual(report["verification"]["rejected_tokens"], 1)
        self.assertEqual(report["verification"]["attempted_tokens"], 4)
        self.assertTrue((self.out / "pools/verification_rounds/round-0002/manifest.json").exists())
        calls = len(self.rpc_calls), len(self.chain_calls)
        self.prepare("all")
        self.assertEqual(calls, (len(self.rpc_calls), len(self.chain_calls)))

    def test_runner_sources_wraps_task_specific_evidence_without_training(self):
        commands = []

        def invoke(command, *args):
            commands.append(command)
            return 0, {"status": "complete"}, ""

        with patch("research.scam.pipeline.invoke", side_effect=invoke), redirect_stdout(io.StringIO()):
            result = runner(["--task", "rug_pull", "--snapshot", "test", "--output", str(self.out),
                             "--stage", "sources", "--positive-count", "10"])
        self.assertEqual(result, 0)
        self.assertEqual([c[c.index("--stage") + 1] for c in commands],
                         ["all"])
        self.assertTrue(all(c[0] == "prepare-rug-pull" for c in commands))
        self.assertFalse(self.out.exists())

    def test_all_quote_discovery_finds_a_non_weth_pool(self):
        original = self.settings["collection"]["transport"]
        original_rpc = self.settings["rpc"]["transport"]
        self.settings["pools"]["scope"] = "all_v2"
        self.settings["rpc"]["verification_mode"] = "factory_event_and_rpc"

        def chain(query):
            if query["action"] != "getLogs":
                return original(query)
            self.assertEqual(query["topic0"], PAIR_TOPIC)
            self.assertEqual(query["address"], UNISWAP_V2_FACTORY)
            rows = []
            for i, (token, quote) in enumerate(((addr(1), WETH), (addr(2), WETH), (addr(6), addr(9))), 1):
                rows.append({"address": UNISWAP_V2_FACTORY, "blockNumber": "0x64", "timeStamp": "0x320",
                             "transactionHash": "0x" + f"{i:064x}", "logIndex": hex(i),
                             "topics": [PAIR_TOPIC, word(token), word(quote)],
                             "data": "0x" + word(addr(1000 + int(token, 16)))[2:] + word(i)[2:]})
            return {"status": "1", "result": rows}

        self.settings["collection"]["transport"] = chain
        self.prepare("sources")
        self.prepare("audit")
        self.prepare("discover")
        targets = read_records(self.out / "pools/candidate_targets.jsonl")
        six = next(t for t in targets if t["target"] == addr(6))
        self.assertEqual(six["quote_token"], addr(9))
        self.assertEqual(six["pools"], [addr(1006)])
        manifest = load_json(self.out / "pools/discovery_manifest.json")
        self.assertEqual(manifest["all_source_matched_label_counts"], {"1": 2, "0": 1})
        self.assertFalse(any(q.get("method") == "eth_call" for q in self.rpc_calls))

        def rpc(source, query):
            if query["method"] == "eth_call":
                call = query["params"][0]
                if call["to"] == addr(1006) and call["data"] == "0xd21220a7":
                    return {"result": word(addr(9))}
                if call["to"] == UNISWAP_V2_FACTORY:
                    data = call["data"]
                    tokens = {"0x" + data[34:74], "0x" + data[98:138]}
                    if tokens == {addr(6), addr(9)}:
                        return {"result": word(addr(1006))}
            return original_rpc(source, query)

        self.settings["rpc"]["transport"] = rpc
        self.prepare("verify")
        self.prepare("prepare")
        final = read_records(self.out / "pools/verified_targets.jsonl")
        target = next(t for t in final if t["target"] == addr(6))
        self.assertEqual(target["pool_metadata"][0]["token1"], addr(9))
        self.assertEqual(load_json(self.out / "label_quality_summary.json")["verification"]["verified_tokens"], 3)


if __name__ == "__main__":
    unittest.main()
