"""Serial pacing, persistent rolling quota and project-local secret loading."""
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from packages.provider_access import SerialRequestBudget, etherscan_key, ethereum_rpc_url, QUOTA_FILE


class ProviderAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "usage.sqlite3"
        self.now = 1000.0
        self.sleeps = []
        self.notices = []

    def sleep(self, duration):
        self.sleeps.append(duration)
        self.now += duration

    def budget(self, **options):
        options.setdefault("rate", 2.5)
        return SerialRequestBudget(self.path, clock=lambda: self.now, sleep=self.sleep,
                                   notify=self.notices.append, **options)

    def count(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT SUM(calls) FROM buckets").fetchone()[0]

    def test_rate_and_retry_reservations_survive_recreation(self):
        with self.budget().request_slot():
            first = self.now
            self.now += 0.2
        with self.assertRaises(RuntimeError), self.budget().request_slot():
            second = self.now
            raise RuntimeError("request failed")
        with self.budget().request_slot():
            third = self.now
        self.assertAlmostEqual(second - first, 0.4)
        self.assertGreaterEqual(third - second, 0.4 - 1e-9)
        self.assertEqual(self.count(), 3)

    def test_slow_http_does_not_add_an_extra_interval(self):
        with self.budget().request_slot():
            self.now += 1.5
        ended = self.now
        with self.budget().request_slot():
            self.assertEqual(self.now, ended)
        self.assertEqual(self.sleeps, [])

    def test_rolling_quota_waits_automatically_after_restart(self):
        for _ in range(2):
            with self.budget(limit=2).request_slot():
                pass
        with self.budget(limit=2).request_slot():
            self.assertGreaterEqual(self.now, 1000 + 86400)
        self.assertTrue(self.notices)
        self.assertLessEqual(max(self.sleeps), 60)
        self.assertEqual(self.count(), 1)

    def test_slow_response_retains_quota_until_after_completion(self):
        with self.budget(limit=1).request_slot():
            self.now += 120
        end = self.now
        with self.budget(limit=1).request_slot():
            self.assertGreaterEqual(self.now, end + 86400)

    def test_initialization_has_no_side_effects(self):
        self.budget()
        self.assertFalse(self.path.exists())

    def test_runtime_quota_override_is_independent_and_explicit_path_wins(self):
        secondary = Path(self.tmp.name) / "secondary.sqlite3"
        original = self.budget()
        with original.request_slot():
            pass
        with patch.dict(os.environ, {"ETHERSCAN_QUOTA_FILE": str(secondary)}):
            budget = SerialRequestBudget(clock=lambda: self.now, sleep=self.sleep)
            self.assertEqual(budget.path, secondary)
            self.assertEqual(self.budget().path, self.path)
            with budget.request_slot():
                pass
            self.assertEqual(self.count(), 1)
        self.assertEqual(original.path, self.path)
        with sqlite3.connect(secondary) as db:
            self.assertEqual(db.execute("SELECT SUM(calls) FROM buckets").fetchone()[0], 1)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(SerialRequestBudget().path, QUOTA_FILE)

    def test_default_budget_enforces_global_ceiling(self):
        self.assertEqual(SerialRequestBudget(self.path).rate, 2.5)
        with self.assertRaisesRegex(ValueError, 'invalid_etherscan_request_budget'):
            SerialRequestBudget(self.path, rate=3)

    def test_local_secret_is_literal_only_and_environment_can_override(self):
        path = Path(self.tmp.name) / "local_secrets.py"
        path.write_text('raise RuntimeError("must never execute")\nETHERSCAN_API_KEY = "test-credential"\n')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(etherscan_key(path=path), "test-credential")
        with patch.dict(os.environ, {"ETHERSCAN_API_KEY": ""}):
            self.assertEqual(etherscan_key(path=path), "")
        path.write_text('ETHERSCAN_API_KEY = str("do-not-expose")\n')
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "literal") as error:
            etherscan_key(path=path)
        self.assertNotIn("do-not-expose", str(error.exception))

    def test_rpc_local_literal_and_environment_override_without_execution(self):
        path = Path(self.tmp.name) / "local_secrets.py"
        path.write_text('raise RuntimeError("never execute")\nETHEREUM_RPC_URL = "https://rpc.example/private"\n')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ethereum_rpc_url(path=path), "https://rpc.example/private")
        with patch.dict(os.environ, {"ETHEREUM_RPC_URL": ""}):
            self.assertEqual(ethereum_rpc_url(path=path), "")
        path.write_text('ETHEREUM_RPC_URL = str("hidden")\n')
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError) as error:
            ethereum_rpc_url(path=path)
        self.assertNotIn("hidden", str(error.exception))
