"""Automation, failure recovery and cross-task storage regression checks."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from checks import test_phishing_preparation as fixtures
from packages.collection import CollectionError, EtherscanClient
from packages.io import load_json, write_records
from packages.provider_access import SerialRequestBudget
from research.scam.execution import run_stage, snapshot_lock
from research.scam.phishing import prepare_phishing
from research.scam.pipeline import main, retryable


class UnattendedTests(unittest.TestCase):
    setUp = fixtures.PhishingPreparationTests.setUp

    def run_pipeline(self, *args):
        settings = self.root / "settings.json"
        settings.write_text(json.dumps(self.settings))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            base = ["--snapshot", "automated", "--output", str(self.root / "pipeline"),
                    "--settings", str(settings), "--profile", "full-history", "--progress", "off", "--retry-delay", "0"]
            if "--stage" in args:
                return main([*base, *args])
            if "--dry-run" in args:
                return main([*base, *args, "--run", "dry"])
            for stage in ("sources", "collect", "prepare"):
                code = main([*base, *args, "--stage", stage])
                if code:
                    return code
            return 0

    def test_unattended_budget_resume_through_preparation(self):
        self.settings["collection"]["max_requests"] = 30
        self.assertEqual(self.run_pipeline("--per-class", "20", "--source-as-of", str(self.cutoff)), 0)
        out = self.root / "pipeline"
        self.assertTrue((out / "prepared/graphs.jsonl").exists())
        self.assertEqual(load_json(out / "status.json")["status"], "prepared")
        runs = [load_json(path) for path in (out / "runs").glob("*.json")]
        self.assertTrue(any(row["status"] == "collection_incomplete" for row in runs))
        self.assertTrue(any(row["status"] == "collected" for row in runs))
        # No repetition of per-class/config/cutoff is needed on a later process.
        self.assertEqual(self.run_pipeline("--stage", "prepare"), 0)
        self.assertFalse((out / "bundle").exists())

    def test_failed_preparation_can_be_retried(self):
        out = self.root / "atomic"
        prepare_phishing(out, self.config, settings=self.settings, stage="cohort", per_class=20, source_as_of=self.cutoff)
        prepare_phishing(out, self.config, settings=self.settings, stage="collect", per_class=20, source_as_of=self.cutoff)
        writes = 0
        def fail_once(path, rows):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("simulated disk interruption")
            write_records(path, rows)
        with patch("research.scam.preparation.write_records", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "interruption"):
                prepare_phishing(out, self.config, settings=self.settings, stage="prepare", per_class=20)
        self.assertFalse((out / "prepared").exists())
        self.assertEqual(prepare_phishing(out, self.config, settings=self.settings, stage="prepare", per_class=20)["status"], "prepared")

    def test_retry_policy_never_retries_integrity_or_row_budget_failures(self):
        for reason in ("nodename nor servname provided, or not known", "Network is unreachable",
                       "Remote end closed connection without response", "provider_request_cancelled"):
            self.assertTrue(retryable(2, {}, reason))
        for reason in ("HTTP Error 403", "HTTP Error 429", "invalid API key", "quota_exceeded"):
            self.assertFalse(retryable(2, {}, reason))
        self.assertFalse(retryable(3, {"resume": "row budget reached; use a new snapshot"}, ""))
        self.assertFalse(retryable(2, {}, "checksum_mismatch"))
        self.assertFalse(retryable(2, {}, "set_ETHERSCAN_API_KEY_in_environment"))
        self.assertTrue(retryable(3, {"resume": "repeat same snapshot"}, ""))
        self.assertTrue(retryable(2, {}, "historical_rpc_request_failed"))
        permanent = {'failure': 'recent_normalization_failed:invalid_amount'}
        transient = {'failure': 'temporarily unavailable'}
        self.assertFalse(retryable(3, {'collection': {'coverage': [permanent]}}, ''))
        self.assertTrue(retryable(3, {'collection': {'coverage': [
            {'failure': 'recent_receipt_verification_budget_pending'}]}}, ''))
        self.assertTrue(retryable(3, {'collection': {'coverage': [permanent, transient]}}, ''))
        self.assertFalse(retryable(3, {'collection': {'coverage': [
            {'failure': 'Invalid API Key'}, transient]}}, ''))

    def test_dry_run_has_no_writes_or_network(self):
        with patch("packages.collection.urlopen", side_effect=AssertionError("network")), patch("packages.sources.phishing.urlopen", side_effect=AssertionError("network")):
            self.assertEqual(self.run_pipeline("--dry-run"), 0)
        self.assertFalse((self.root / "pipeline").exists())

    def test_lock_and_interruption_status(self):
        out = self.root / "locked"
        with snapshot_lock(out):
            with self.assertRaisesRegex(ValueError, "another_process"):
                run_stage(out, "collect", lambda: {})
        with redirect_stderr(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            run_stage(out, "collect", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.assertEqual(load_json(out / "status.json")["status"], "interrupted")
        self.assertNotIn("result", load_json(out / "status.json"))

    def test_shared_requests_reused_without_network_and_fixtures_isolated(self):
        settings = {"shared_cache_dir": str(self.root / "shared"), "allow_network": True, "api_key": "fixture-secret"}
        payload = {"status": "1", "message": "OK", "result": []}
        first = EtherscanClient(self.root / "task1", settings)
        first.budget = SerialRequestBudget(self.root / "quota.sqlite3")
        with patch("packages.collection.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as network:
            a = first.request("account", "txlist", address=fixtures.address(1), startblock=1, endblock=100)
        self.assertEqual(network.call_count, 1)
        second = EtherscanClient(self.root / "task2", {"shared_cache_dir": settings["shared_cache_dir"]})
        with patch("packages.collection.urlopen", side_effect=AssertionError("network")):
            b = second.request("account", "txlist", address=fixtures.address(1), startblock=1, endblock=100)
        self.assertEqual(a, b)
        self.assertEqual(second.request_count, 0)
        self.assertNotIn("fixture-secret", Path(a["raw_path"]).read_text())
        isolated = EtherscanClient(self.root / "synthetic", {**settings, "fixtures": {"txlist": []}})
        c = isolated.request("account", "txlist", address=fixtures.address(1), startblock=1, endblock=100)
        self.assertNotEqual(c["raw_path"], a["raw_path"])
        Path(b["raw_path"]).write_text(json.dumps({**load_json(b["raw_path"]), "response_sha256": "broken"}))
        with self.assertRaisesRegex(CollectionError, "checksum"):
            second.request("account", "txlist", address=fixtures.address(1), startblock=1, endblock=100)


if __name__ == "__main__":
    unittest.main()
