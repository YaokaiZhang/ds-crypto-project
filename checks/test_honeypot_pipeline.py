"""Honeypot source quality, deterministic discovery and failure-tolerant replay."""
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.collection import CollectionError
from packages.io import load_json, read_records, save_json
from packages.token import UNISWAP_V2_FACTORY
from packages.token_sources import SnapshotClient
from research.scam.honeypot import PAIR_TOPIC, WETH, prepare_honeypot
from research.scam.pipeline import main as run_pipeline


def addr(n):
    return f"0x{n:040x}"


def pair_log(n):
    return {"address": UNISWAP_V2_FACTORY, "blockNumber": "0x96", "timeStamp": "0x3e8",
            "transactionHash": "0x" + f"{n:064x}", "logIndex": hex(n),
            "topics": [PAIR_TOPIC, "0x" + addr(n)[2:].rjust(64, "0"), "0x" + WETH[2:].rjust(64, "0")],
            "data": "0x" + addr(n + 1000)[2:].rjust(64, "0") + f"{n:064x}"}


def response(query, value=False, success=True):
    return {"token": {"address": query["address"]}, "chain": {"id": "1"},
            "pair": {"pair": {"address": query["pair"], "type": "UniswapV2"}},
            "honeypotResult": {"isHoneypot": value}, "simulationSuccess": success}


class HoneypotPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "snapshot"
        positive, negative = self.root / "positive.csv", self.root / "negative.csv"
        positive.write_text("\ufefftoken_address,pool_address,type\n" +
                            f"{addr(1)},{addr(1001)},conditional_asserting\n" +
                            f"{addr(1)},{addr(1002)},fee_manipulation\n" +
                            f"{addr(2)},{addr(1003)},conditional_asserting\n" +
                            f"{addr(2)},{addr(1003)},conditional_asserting\n" +
                            "bad,bad,conditional_asserting\n")
        negative.write_text("token_address,pool_address\n" + f"{addr(3)},{addr(1004)}\n")
        self.calls = []

        def chain(query):
            self.calls.append(dict(query))
            if query["action"] == "getblocknobytime":
                value = "100" if query["closest"] == "after" else "200"
            else:
                rows = [] if "topic1" in query else [pair_log(n) for n in range(1, 14)]
                offset, page = query["offset"], query["page"]
                value = rows[(page - 1) * offset:page * offset]
            return {"status": "1", "message": "OK", "result": value}

        self.settings = {"source_files": {"positive": str(positive), "negative": str(negative)},
                         "discovery": {"as_of": 20000000, "lookback_days": 10, "seed": 12},
                         "collection": {"transport": chain, "page_size": 5, "max_requests": 30},
                         "honeypot": {"transport": lambda source, query: response(query)}}

    def prepare(self, stage, **kw):
        return prepare_honeypot(self.out, stage=stage, settings=self.settings, progress="off", **kw)

    def discover(self, count=6):
        self.prepare("sources")
        self.prepare("audit")
        self.prepare("discover", candidate_count=count)

    def test_sources_audit_dedup_and_unknown_temporal_evidence(self):
        self.prepare("sources")
        self.prepare("audit")
        audit = load_json(self.out / "historical/quality_audit.json")
        self.assertEqual(audit["counts"]["unique_positive_tokens"], 2)
        self.assertEqual(audit["counts"]["unique_negative_tokens"], 1)
        self.assertEqual(audit["counts"]["exact_duplicates"], 1)
        self.assertEqual(audit["counts"]["invalid_rows"], 1)
        labels = read_records(self.out / "historical/labels.jsonl")
        self.assertEqual(len(labels), 4)
        self.assertTrue(all(r["cutoff"] is None and not r["training_eligible"] for r in labels))
        self.prepare("audit")
        source = Path(self.settings["source_files"]["positive"])
        source.write_text(source.read_text() + "changed")
        with self.assertRaisesRegex(ValueError, "source_file_changed"):
            self.prepare("sources")

    def test_cross_source_conflicts_excluded_and_all_addresses_blocked(self):
        negative = Path(self.settings["source_files"]["negative"])
        negative.write_text(negative.read_text() + f"{addr(1)},{addr(1001)}\n")
        self.prepare("sources")
        self.prepare("audit")
        rows = read_records(self.out / "historical/labels.jsonl")
        self.assertTrue(all(r["candidate_label"] is None for r in rows if r["token_address"] == addr(1)))
        self.assertIn(addr(1), {r["token_address"] for r in read_records(self.out / "historical/tokens.jsonl")})

    def test_discovery_is_paged_unique_label_blind_and_excludes_historical(self):
        self.discover()
        selected = read_records(self.out / "discovery/targets.jsonl")
        self.assertEqual(len(selected), 6)
        self.assertEqual(len({r["target"] for r in selected}), 6)
        self.assertFalse({addr(1), addr(2), addr(3)} & {r["target"] for r in selected})
        self.assertTrue(any(q.get("page") == 3 for q in self.calls))
        calls = len(self.calls)
        self.prepare("discover")
        self.assertEqual(len(self.calls), calls)
        with self.assertRaisesRegex(ValueError, "inputs_changed"):
            self.prepare("discover", candidate_count=7)
        self.settings["discovery"]["seed"] = 99
        with self.assertRaisesRegex(ValueError, "inputs_changed"):
            self.prepare("discover")

    def test_unknowns_failures_and_positive_survive_without_replacement_or_requery(self):
        self.discover()
        targets = read_records(self.out / "discovery/targets.jsonl")
        queried = []

        def api(source, query):
            queried.append(query["address"])
            position = next(i for i, t in enumerate(targets) if t["target"] == query["address"])
            if position == 0:
                raise CollectionError("upstream_not_available")
            if position == 1:
                return response(query, False, False)
            if position == 2:
                return response(query, True, False)
            if position == 3:
                return response({**query, "pair": addr(9999)})
            return response(query)

        self.settings["honeypot"]["transport"] = api
        self.prepare("label")
        labels = read_records(self.out / "contemporary/labels.jsonl")
        self.assertEqual(len(labels), 6)
        self.assertEqual(labels[0]["label_status"], "excluded_query_failure")
        self.assertIsNone(labels[1]["candidate_label"])
        self.assertEqual(labels[2]["candidate_label"], 1)
        self.assertEqual(labels[3]["label_status"], "invalid")
        self.assertTrue(all(not r["training_eligible"] for r in labels))
        self.assertEqual(len(read_records(self.out / "contemporary/detection_targets.jsonl")), 3)
        with (self.out / "contemporary/labels.csv").open() as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 6)
        self.prepare("label")
        self.assertEqual(len(queried), 6)
        self.prepare("prepare")
        self.assertFalse(load_json(self.out / "readiness.json")["historical_collection_ready"])

    def test_interrupted_capture_reuses_completed_samples(self):
        self.discover()
        queried = []

        def interrupted(source, query):
            queried.append(query["address"])
            if len(queried) == 3:
                raise KeyboardInterrupt
            return response(query)

        self.settings["honeypot"]["transport"] = interrupted
        with self.assertRaises(KeyboardInterrupt):
            self.prepare("label")
        self.assertEqual(len(list((self.out / "contemporary/results").glob("*.json"))), 2)
        remaining = []
        self.settings["honeypot"]["transport"] = lambda source, q: (remaining.append(q["address"]) or response(q))
        self.prepare("label")
        self.assertEqual(len(remaining), 4)
        self.assertFalse(set(queried[:2]) & set(remaining))

    def test_authentication_failure_is_not_silently_dropped(self):
        self.discover()
        self.settings["honeypot"]["transport"] = lambda *args: (_ for _ in ()).throw(CollectionError("HTTP Error 403"))
        with self.assertRaisesRegex(CollectionError, "403"):
            self.prepare("label")
        self.assertFalse((self.out / "contemporary/manifest.json").exists())

    def test_concurrent_capture_keeps_order_and_replays_without_requests(self):
        self.discover()
        self.settings["honeypot"]["workers"] = 4
        self.prepare("label")
        expected = [r["sample_id"] for r in read_records(self.out / "discovery/targets.jsonl")]
        actual = [r["sample_id"] for r in read_records(self.out / "contemporary/labels.jsonl")]
        self.assertEqual(actual, expected)
        self.settings["honeypot"]["transport"] = lambda *args: (_ for _ in ()).throw(AssertionError("requery"))
        self.prepare("label")

    def test_concurrent_snapshot_requests_share_rate_and_attempt_budget(self):
        client = SnapshotClient(self.root / "requests", {"allow_network": True, "rate_limit_rps": 3, "max_requests": 3})
        clock, starts = [100.0], []
        def sleep(seconds):
            clock[0] += seconds
        def network(*args, **kwargs):
            starts.append(clock[0])
            return io.BytesIO(b"{}")
        def request(n):
            try:
                return client.request("honeypot_is", {"address": addr(n)})
            except CollectionError as error:
                return str(error)
        with patch("packages.token_sources.time.monotonic", side_effect=lambda: clock[0]), patch("packages.token_sources.time.sleep", side_effect=sleep), patch("packages.token_sources.urlopen", side_effect=network):
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(request, range(8)))
        self.assertEqual(client.requests, 3)
        self.assertEqual(len(starts), 3)
        self.assertTrue(all(b - a >= 1 / 3 - 1e-8 for a, b in zip(starts, starts[1:])))
        self.assertEqual(outcomes.count("request_budget_exhausted"), 5)

    def test_insufficient_cohort_and_checksum_fail_closed(self):
        self.prepare("sources")
        self.prepare("audit")
        with self.assertRaisesRegex(ValueError, "insufficient_candidates"):
            self.prepare("discover", candidate_count=50)
        self.assertFalse((self.out / "discovery/targets.jsonl").exists())
        (self.out / "historical/tokens.jsonl").write_text("[]")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.prepare("audit")

    def test_runner_dry_run_and_stage_validation(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch("packages.collection.urlopen", side_effect=AssertionError("network")):
            args = ["--task", "honeypot", "--snapshot", "test", "--output", str(self.out)]
            self.assertEqual(run_pipeline(args + ["--dry-run", "--run", "dry"]), 0)
            self.assertFalse(self.out.exists())
            self.assertEqual(run_pipeline(args + ["--stage", "train", "--run", "bad"]), 2)
            self.assertEqual(run_pipeline(args + ["--stage", "collect"]), 2)
            self.assertEqual(run_pipeline(["--task", "phishing", "--snapshot", "test", "--stage", "label"]), 2)
            local = self.root / "settings.json"
            save_json(local, {"source_files": self.settings["source_files"]})
            self.assertEqual(run_pipeline(args + ["--settings", str(local), "--stage", "sources", "--dry-run"]), 0)
            self.assertEqual(run_pipeline(args + ["--stage", "audit"]), 2)


if __name__ == "__main__":
    unittest.main()
