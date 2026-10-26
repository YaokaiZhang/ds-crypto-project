"""Lossless cursor paging and reuse on large, overlapping address histories."""
from pathlib import Path
import tempfile
import unittest

from packages.collection import EtherscanClient, collect_dataset
from packages.io import load_json, read_records
from checks.test_data import A, tx


class CollectionPerformanceTests(unittest.TestCase):
    def test_dense_early_history_does_not_redownload_complete_prefixes(self):
        # Three events/block makes the 100-row window end inside a block.
        rows = [tx(hash=f"0x{i:064x}", blockNumber=str(i // 3 + 1)) for i in range(2000)]
        calls = []
        def transport(query):
            calls.append(query)
            selected = [row for row in rows if query["startblock"] <= int(row["blockNumber"]) <= query["endblock"]]
            start = (query["page"] - 1) * query["offset"]
            return {"status": "1", "result": selected[start:start + query["offset"]]}
        with tempfile.TemporaryDirectory() as directory:
            client = EtherscanClient(directory, {"page_size": 50, "max_pages": 2}, transport)
            actual, coverage = client.history("txlist", A, 0, 1000000)
        self.assertTrue(coverage["complete"])
        self.assertEqual([row["hash"] for row in actual], [row["hash"] for row in rows])
        self.assertLess(len(calls), 45)
        # Only the first window queries the original lower bound. The partial
        # boundary block is reread, with no missing or duplicated final records.
        self.assertEqual(sum(query["startblock"] == 0 for query in calls), 2)

    def test_long_cursor_walk_is_iterative_and_does_not_hit_recursion_limit(self):
        rows = [tx(hash=f"0x{i:064x}", blockNumber=str(i + 1)) for i in range(1100)]
        def transport(query):
            start = query["startblock"] - 1
            return {"status": "1", "result": rows[start:start + 2]}
        with tempfile.TemporaryDirectory() as directory:
            client = EtherscanClient(directory, {"page_size": 2, "max_pages": 1}, transport)
            actual, coverage = client.history("txlistinternal", A, 1, 1101)
        self.assertTrue(coverage["complete"])
        self.assertEqual(len(actual), len(rows))

    def test_repeated_history_does_not_exhaust_raw_row_budget(self):
        targets = [{"sample_id": f"root-{i}", "task_id": "phishing", "target": A,
                    "cutoff": 100, "start_block": 1, "end_block": 2} for i in range(2)]
        settings = {"fixtures": {"txlist": [tx()], "txlistinternal": []},
                    "hops": 1, "fanouts": [1], "max_raw_rows": 1, "progress": "off"}
        with tempfile.TemporaryDirectory() as directory:
            result = collect_dataset(targets, directory, settings)
            self.assertTrue(result["complete"])
            self.assertEqual(len(read_records(Path(directory) / "events.jsonl")), 1)
            report = load_json(Path(directory) / "progress.json")
            self.assertEqual(report["raw_rows_retained"], 1)
            self.assertEqual(report["roots_completed"], 2)
            self.assertEqual(report["phase"], "complete")
