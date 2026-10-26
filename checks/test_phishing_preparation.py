"""Source snapshots and synthetic Phishing preparation without network/training."""
from contextlib import redirect_stderr, redirect_stdout
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.collection import EtherscanClient, collect_dataset
from packages.io import read_records
from packages.labeling import reconcile_labels
from packages.sources.phishing import fetch_phishing_labels
from research.scam.cohorts import build_phishing_cohort
from packages.sources.historical import discover_background, load_background_records
from research.scam._commands import main
from research.scam.phishing import prepare_phishing
from checks.token_fixtures import token_target, token_label


def address(number):
    return f"0x{number:040x}"


class PhishingPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cutoff = 1665080868
        self.config = json.loads((Path(__file__).resolve().parents[1] / "research/scam/configs/phishing.json").read_text())
        background = self.root / "background.txt"
        background.write_text("\n".join(address(i) for i in range(21, 41)) + "\n" + address(1) + "\n")
        forta = self.root / "forta.csv"
        with forta.open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["address", "etherscan_tag", "etherscan_labels", "is_contract"])
            writer.writerows([[address(i), f"Fake_Phishing{i}", "phish-hack", "False"] for i in range(1, 21)])
            writer.writerow([address(50), "Affected legitimate contract", "phish-hack", "True"])
        transactions = [{"hash": f"0x{i:064x}", "from": address(i), "to": address(999), "value": "1000000000000000000",
                         "timeStamp": str(self.cutoff - 100), "blockNumber": "100", "isError": "0", "input": "0x"} for i in range(1, 41)]
        transactions.append({**transactions[0], "hash": "0x" + "f" * 64, "timeStamp": str(self.cutoff + 1)})
        self.settings = {"label_files": {"poison_hunter_background": str(background), "forta": str(forta)},
                         "collection": {"fixtures": {"txlist": transactions, "txlistinternal": [], "getblocknobytime": {"result": "100"}}}}

    def sources(self, folder="sources"):
        return fetch_phishing_labels(self.root / folder, local_files=self.settings["label_files"], source_as_of=self.cutoff)

    def test_source_deduplication_overlap_and_unknown_dates(self):
        self.sources()
        targets, evidence, report = build_phishing_cohort(self.root / "sources", per_class=20)
        self.assertEqual(len(targets), 40)
        self.assertEqual(report["excluded_background_positive_overlap"], [address(1)])
        self.assertNotIn(address(50), [row["target"] for row in targets])
        self.assertTrue(all(row["valid_from"] is None and row["valid_to"] is None for row in evidence))
        labels = reconcile_labels(evidence, targets)
        self.assertEqual(sum(row["eligible"] for row in labels), 20)
        self.assertTrue(all(row["label_status"] == "unlabeled" for row in labels if row["background_selected"]))
        again, _, _ = build_phishing_cohort(self.root / "sources", per_class=20)
        self.assertEqual(targets, again)
        Path(self.settings["label_files"]["forta"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.sources()

    def test_remote_download_pins_commit_and_source_cutoff(self):
        fixtures = self.settings["label_files"]
        def download(url):
            if "/commits?" in url:
                return json.dumps([{"sha": "a" * 40, "commit": {"committer": {"date": "2022-10-06T18:27:48Z"}}}]).encode()
            self.assertIn("/" + "a" * 40 + "/", url)
            if url.endswith("phishing_scams.csv"):
                return Path(fixtures["forta"]).read_bytes()
            return Path(fixtures["poison_hunter_background"]).read_bytes()
        with patch("packages.sources.phishing._download", side_effect=download):
            manifest = fetch_phishing_labels(self.root / "remote", allow_network=True)
        self.assertEqual(manifest["source_as_of"], self.cutoff)
        self.assertTrue(all(item["commit"] == "a" * 40 for item in manifest["files"]))
        self.assertEqual(manifest["source_names"], ["forta", "poison_hunter_background"])

    def test_full_offline_pipeline_and_resume(self):
        output = self.root / "snapshot"
        with patch("research.scam.training.train", side_effect=AssertionError("formal fitting started")):
            # Preparation's imported trainer is only called with dry_run=True.
            result = prepare_phishing(output, self.config, settings=self.settings, per_class=20, source_as_of=self.cutoff)
        self.assertEqual(result["status"], "prepared")
        self.assertFalse(result["fitting_performed"])
        prepared = output / "prepared"
        self.assertEqual(len((output / "cohort/scam_addresses.txt").read_text().splitlines()), 20)
        self.assertEqual(len((output / "cohort/background_addresses.txt").read_text().splitlines()), 20)
        for name in ("graphs", "supervision", "splits", "targets"):
            self.assertTrue((prepared / f"{name}.jsonl").is_file())
        config = json.loads((prepared / "training_config.json").read_text())
        self.assertGreater(config["graph"]["window_days"], 2000)
        self.assertEqual(config["model"]["hidden_dim"], 256)
        self.assertEqual(config["model"]["layers"], 2)
        graphs = read_records(prepared / "graphs.jsonl")
        self.assertTrue(all(graph["cutoff"] == self.cutoff for graph in graphs))
        self.assertTrue(all(len(graph["node_refs"]) <= 512 and len(graph["relation_ids"]) <= 4096 for graph in graphs))
        self.assertTrue(all(event["timestamp"] <= self.cutoff for event in read_records(output / "collection/events.jsonl")))
        from research.scam.training import train
        with self.assertRaisesRegex(ValueError, "frozen training_config"):
            train(graphs, read_records(prepared / "supervision.jsonl"), read_records(prepared / "splits.jsonl"), self.config,
                  self.root / "never-trained", dry_run=True)
        again = prepare_phishing(output, self.config, settings=self.settings, per_class=20, source_as_of=self.cutoff)
        self.assertEqual(again["status"], "prepared")
        self.assertGreater(json.loads((output / "collection/manifest.json").read_text())["cached_request_count"], 0)
        with self.assertRaisesRegex(ValueError, "changed"):
            prepare_phishing(output, self.config, settings=self.settings, per_class=10, source_as_of=self.cutoff)

    def test_historical_background_freeze_cutoff_and_cache(self):
        def transport(method, params):
            if method == "eth_chainId":
                return "0x1"
            if method == "eth_blockNumber":
                return hex(200)
            number = int(params[0], 16)
            block_hash = f"0x{number:064x}"
            return {"number": hex(number), "hash": block_hash,
                    "timestamp": hex(self.cutoff - 100 + number),
                    "transactions": [{"hash": f"0x{number + 1000:064x}", "blockHash": block_hash,
                                      "blockNumber": hex(number), "from": address(number + 100),
                                      "to": address(number + 10000)}] if params[1] else []}
        out = self.root / "historical"
        report = discover_background(out, cutoff=self.cutoff, block_count=10, transport=transport, progress="off")
        self.assertEqual(report["end_block"], 100)
        rows, _ = load_background_records(out, self.cutoff)
        self.assertTrue(all(row["mapped_label"] is None for row in rows))
        self.assertTrue(all("task_id" not in row for row in rows))
        self.assertTrue(all(row["raw_record"]["timestamp"] <= self.cutoff for row in rows))
        with patch("packages.sources.historical.urlopen", side_effect=AssertionError("network")):
            self.assertEqual(discover_background(out, cutoff=self.cutoff, block_count=10, progress="off"), report)
        with self.assertRaisesRegex(ValueError, "changed"):
            discover_background(out, cutoff=self.cutoff, block_count=11)
        Path(self.settings["label_files"]["poison_hunter_background"]).write_text("\n".join(address(i) for i in range(21, 31)) + "\n")
        self.sources()
        targets, _, cohort = build_phishing_cohort(self.root / "sources", per_class=20, background_directory=out)
        self.assertEqual(cohort["background_source_counts"]["poison_hunter_background"], 10)
        self.assertEqual(cohort["background_source_counts"]["historical_rpc"], 10)
        self.assertEqual(len(targets), 40)
        settings = {**self.settings, "background_snapshot": str(out)}
        snapshot = self.root / "shared-consumer"
        result = prepare_phishing(snapshot, self.config, settings=settings, stage="cohort",
                                  per_class=20, source_as_of=self.cutoff)
        self.assertEqual(result["paths"]["background"], str(out.resolve()))
        self.assertFalse((snapshot / "background").exists())
        reference = json.loads((snapshot / "background_ref.json").read_text())
        self.assertEqual(reference["path"], str(out.resolve()))
        # A later process resolves the frozen reference without repeating its path.
        self.assertEqual(prepare_phishing(snapshot, self.config, settings=self.settings, stage="cohort",
                                         per_class=20)["status"], "cohort_ready")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            load_background_records(out, self.cutoff + 1)

    def test_background_shortage_does_not_discard_positives(self):
        Path(self.settings["label_files"]["poison_hunter_background"]).write_text("\n".join(address(i) for i in range(21, 31)) + "\n")
        self.sources()
        with self.assertRaisesRegex(ValueError, "insufficient_background"):
            build_phishing_cohort(self.root / "sources", per_class=20)
        with self.assertRaisesRegex(ValueError, "only_accept"):
            fetch_phishing_labels(self.root / "unused", local_files={"poison_hunter_positive": "unused"})

    def test_reuse_pinned_sources_and_list_integrity(self):
        self.sources()
        output = self.root / "reused"
        settings = {"source_snapshot": str(self.root / "sources")}
        with patch("packages.sources.phishing.urlopen", side_effect=AssertionError("network")):
            report = prepare_phishing(output, self.config, settings=settings, stage="cohort", per_class=20)
        self.assertEqual(report["status"], "cohort_ready")
        self.assertEqual(json.loads((output / "sources/manifest.json").read_text())["source_as_of"], self.cutoff)
        self.assertFalse((output / "collection").exists())
        plan = prepare_phishing(output, self.config, stage="collect", per_class=20, dry_run=True)
        self.assertEqual(plan["cohort"]["per_class_selected"], 20)
        self.assertFalse(plan["network_performed"])
        (output / "cohort/background_addresses.txt").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "address_list_changed"):
            prepare_phishing(output, self.config, stage="collect", per_class=20)

    def test_dry_run_creates_nothing_and_rejects_settings_secrets(self):
        output = self.root / "not-created"
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), patch("packages.sources.phishing.urlopen", side_effect=AssertionError("network")):
            code = main(["prepare-phishing", "--task", "phishing", "--snapshot", "test", "--output", str(output), "--dry-run"])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertFalse(output.exists())
        self.assertFalse(json.loads(stdout.getvalue())["network_performed"])
        with self.assertRaisesRegex(ValueError, "environment"):
            prepare_phishing(output, self.config, settings={"collection": {"api_key": "do-not-persist"}})
        with self.assertRaisesRegex(ValueError, "credentials"):
            prepare_phishing(output, self.config, settings={"collection": {"endpoint": "https://api.etherscan.io/v2/api?apikey=secret"}})

    def test_missing_etherscan_key_fails_before_collection(self):
        settings = {"label_files": self.settings["label_files"]}
        with patch.dict("os.environ", {"ETHERSCAN_API_KEY": ""}), patch("research.scam.phishing.collect_dataset") as collect:
            with self.assertRaisesRegex(ValueError, "ETHERSCAN_API_KEY"):
                prepare_phishing(self.root / "no-key", self.config, settings=settings, per_class=20,
                                 source_as_of=self.cutoff, allow_network=True)
        collect.assert_not_called()

    def test_no_incident_date_required_across_tasks(self):
        for task in ("phishing", "ponzi", "honeypot", "rug_pull"):
            target = token_target(task) if task in {"honeypot", "rug_pull"} else {"sample_id": task, "task_id": task, "target": address(1), "cutoff": self.cutoff}
            label = token_label(target) if task in {"honeypot", "rug_pull"} else {"task_id": task, "entity_id": address(1), "mapped_label": 1, "label_status": "supported_positive", "role": "phishing_address" if task == "phishing" else "target_contract", "audit_decision": "accepted"}
            for field in ("valid_from", "valid_to", "label_available_at"):
                label.pop(field, None)
            record = reconcile_labels([label], [target])[0]
            self.assertTrue(record["eligible"], (task, record))
            self.assertNotIn("incident_onset", record)

    def test_history_and_raw_record_budgets_mark_incomplete(self):
        client = EtherscanClient(self.root / "budget", {"fixtures": self.settings["collection"]["fixtures"], "max_history_rows": 1})
        _, coverage = client.history("txlist", address(1), 1, 100)
        self.assertFalse(coverage["complete"])
        self.assertIn("history_row_budget_exhausted", coverage["gaps"][0]["reason"])
        target = {"sample_id": "limited", "task_id": "phishing", "target": address(1), "cutoff": self.cutoff, "start_block": 1, "end_block": 100}
        settings = {**self.settings["collection"], "max_raw_rows": 1}
        report = collect_dataset([target], self.root / "raw-budget", settings)
        self.assertFalse(report["complete"])
        self.assertEqual(report["coverage"][0]["failure"], "raw_row_budget_exhausted")


if __name__ == "__main__":
    unittest.main()
