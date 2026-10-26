"""Source-separated historical Ponzi cohorts, collection and training admission."""
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from packages.collection import EtherscanClient
from packages.collection_recent import RecentHistoryCollector
from packages.io import load_json, read_records, save_json, sha256_file
from packages.labeling import reconcile_labels
from research.scam.ponzi import build_ponzi_cohort, parse_cutoff, prepare_ponzi
from research.scam.pipeline import main as run_pipeline


def address(number):
    return f"0x{number:040x}"


class PonziPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["Contract", "Ponzi"])
        writer.writerows([(address(i), 1) for i in range(1, 13)])
        writer.writerows([(address(i), 0) for i in range(31, 61)])
        writer.writerow([address(99), "error"])
        data = stream.getvalue().encode()
        (self.source / "Ponzi_label.csv").write_bytes(data)
        (self.source / "README.txt").write_text("Synthetic source fixture; no real labels.\n")
        with zipfile.ZipFile(self.source / "xblock-v1.zip", "w") as z:
            for name in ("Ponzi_label.csv", "README.txt"):
                z.write(self.source / name, "Smart Ponzi Scheme Labels/" + name)
        save_json(self.source / "kaggle_metadata.json", {"currentVersionNumber": 1})
        save_json(self.source / "xblock_metadata.json", {"synthetic": True})
        save_json(self.source / "cross_reference/unica_commit.json", {"sha": "a" * 40})
        unica = self.source / "cross_reference/unica_ponzi-addresses.csv"
        unica.write_text("\n".join(f"{address(i)},Synthetic {i}" for i in [1, 2, 3, *range(13, 22), 41, 13]) + "\n")
        files = {}
        for path in self.source.rglob("*"):
            if path.is_file():
                name = str(path.relative_to(self.source))
                files[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
                if name in {"Ponzi_label.csv", "README.txt"}:
                    files[name].update(archive="xblock-v1.zip", member="Smart Ponzi Scheme Labels/" + name)
        save_json(self.source / "manifest.json", {"snapshot": "synthetic", "kaggle_dataset_version": 1,
                  "unica_commit": "a" * 40, "files": files})
        self.config = load_json(Path(__file__).resolve().parents[1] / "research/scam/configs/ponzi_recent.json")
        self.cutoffs = {name: parse_cutoff(value) for name, value in self.config["source_cutoffs"].items()}
        self.targets, _, _ = build_ponzi_cohort(self.source, negative_count=20, seed=self.config["seed"], cutoffs=self.cutoffs)
        transactions = []
        for target in self.targets:
            block = 90 if target["cutoff_source"] == "unica" else 190
            transactions.append({"hash": "0x" + target["target"][2:].zfill(64), "from": target["target"],
                "to": address(999), "value": "1000000000000000000", "timeStamp": str(target["cutoff"] - 100),
                "blockNumber": str(block), "isError": "0", "input": "0x"})
        payloads = {}
        for cutoff, block in ((self.cutoffs["unica"], 100), (self.cutoffs["xblock_ponzi"], 200)):
            query = {"chainid": 1, "module": "block", "action": "getblocknobytime", "timestamp": cutoff, "closest": "before"}
            payloads[EtherscanClient.request_id(query)] = {"result": str(block)}
            for entity in [t["target"] for t in self.targets] + [address(999)]:
                for action in ("txlist", "txlistinternal"):
                    query = {"chainid": 1, "module": "account", "action": action, "address": entity,
                             "startblock": 0, "endblock": block, "page": 1, "offset": 100, "sort": "desc"}
                    rows = [r for r in transactions if entity in (r["from"], r["to"]) and int(r["blockNumber"]) <= block]
                    rows.sort(key=lambda row: int(row["blockNumber"]), reverse=True)
                    payloads[EtherscanClient.request_id(query)] = {"status": "1", "result": rows if action == "txlist" else []}
        self.settings = {"collection": {"fixtures": payloads}, "observation_root": str(self.root / "observations")}
        self.out = self.root / "dataset"

    def prepare(self, **options):
        return prepare_ponzi(self.out, self.config, settings=self.settings, source_snapshot=self.source,
                             negative_count=20, progress="off", **options)

    def runner(self, *args):
        settings_path = self.root / "settings.json"
        save_json(settings_path, self.settings)
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            code = run_pipeline(["--task", "ponzi", "--snapshot", "synthetic", "--output", str(self.out),
                                 "--settings", str(settings_path), "--source-snapshot", str(self.source),
                                 "--progress", "off", "--retry-delay", "0", *args])
        return code, stdout.getvalue()

    def test_conflicts_removed_before_negative_sampling_and_source_cutoffs(self):
        targets, evidence, report = build_ponzi_cohort(self.source, negative_count=20, seed=self.config["seed"], cutoffs=self.cutoffs)
        self.assertEqual((report["positive_union_before_conflict_exclusion"], report["positive_count"], report["negative_count"]), (22, 21, 20))
        self.assertEqual(report["excluded_conflicting_addresses"], [address(41)])
        self.assertNotIn(address(99), {t["target"] for t in targets})
        self.assertNotIn(address(41), {t["target"] for t in targets})
        self.assertEqual(report["positive_cutoff_source_counts"], {"xblock_ponzi": 12, "unica": 9})
        self.assertEqual(next(t for t in targets if t["target"] == address(1))["cutoff"], self.cutoffs["xblock_ponzi"])
        self.assertEqual(len({t["target"] for t in targets}), 41)
        self.assertTrue(all(r["valid_from"] is None and r["label_available_at"] is None for r in evidence))
        labels = reconcile_labels(evidence, targets)
        self.assertEqual(Counter(r["label_status"] for r in labels), {"supported_positive": 21, "supported_negative": 20})
        again, _, _ = build_ponzi_cohort(self.source, negative_count=20, seed=self.config["seed"], cutoffs=self.cutoffs)
        self.assertEqual(targets, again)
        different, _, _ = build_ponzi_cohort(self.source, negative_count=20, seed=self.config["seed"] + 1, cutoffs=self.cutoffs)
        self.assertNotEqual({t["target"] for t in targets}, {t["target"] for t in different})

    def test_runner_dry_run_writes_nothing_and_rejects_wrong_task_flags(self):
        with patch("packages.collection.urlopen", side_effect=AssertionError("network")):
            code, _ = self.runner("--negative-count", "20", "--dry-run", "--run", "dry")
        self.assertEqual(code, 0)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.runner("--per-class", "20", "--dry-run")[0], 2)

    def test_end_to_end_distinct_cutoff_blocks_and_no_http_on_resume(self):
        seen = []
        collect = RecentHistoryCollector.collect
        def observe(collector, target, graph, end_block, work):
            seen.append((target["cutoff_source"], target["cutoff"], end_block))
            return collect(collector, target, graph, end_block, work)
        with patch("packages.collection.urlopen", side_effect=AssertionError("network")), patch.object(RecentHistoryCollector, "collect", new=observe):
            self.assertEqual(self.prepare()["status"], "prepared")
        self.assertEqual({(source, block) for source, _, block in seen}, {("unica", 100), ("xblock_ponzi", 200)})
        for source, cutoff, block in seen:
            self.assertEqual(cutoff, self.cutoffs[source])
        report = load_json(self.out / "prepared/dataset_manifest.json")
        self.assertEqual(report["training_admission"]["eligible_samples"], 41)
        self.assertEqual(set(report["split"]["partition_class_counts"]), {"train", "validation"})
        with patch.object(EtherscanClient, "request", side_effect=AssertionError("HTTP")):
            self.assertEqual(self.prepare()["status"], "prepared")
        with patch("research.scam.pipeline.model_path", return_value=self.root / "model"):
            code, output = self.runner("--stage", "train", "--run", "dry", "--dry-run")
            self.assertEqual(code, 0)
            self.assertNotIn("early_stopping_metric", json.loads(output)["config"])
        self.assertFalse((self.root / "model").exists())

    def test_unattended_all_and_parameterless_frozen_resume(self):
        with patch("research.scam.pipeline.model_path", return_value=self.root / "all-model"):
            self.assertEqual(self.runner("--negative-count", "20", "--run", "all", "--epochs", "1")[0], 0)
        self.assertEqual(load_json(self.root / "all-model/training_summary.json")["status"], "trained")
        self.assertTrue((self.root / "all-model/run_manifest.json").exists())
        self.assertEqual(self.runner("--stage", "prepare")[0], 0)
        self.assertEqual(self.runner("--stage", "sources", "--unica-cutoff", "2017-05-08T23:59:59Z")[0], 2)

    def test_training_overrides_preserve_dataset_and_are_recorded_in_run(self):
        self.prepare()
        config = self.out / "prepared/training_config.json"
        before = sha256_file(config)
        with patch("research.scam.pipeline.model_path", return_value=self.root / "model"):
            code, _ = self.runner("--stage", "train", "--run", "override", "--epochs", "1",
                "--patience", "2", "--min-delta", "0.00001")
        self.assertEqual(code, 0)
        self.assertEqual(sha256_file(config), before)
        manifest = load_json(self.root / "model/run_manifest.json")
        self.assertEqual(manifest["training_overrides"], {"epochs": 1, "patience": 2, "min_delta": .00001})
        self.assertEqual(manifest["training_summary_sha256"], sha256_file(self.root / "model/training_summary.json"))
        report = load_json(self.root / "model/training_summary.json")
        self.assertEqual(report["best_epoch"], 1)
        self.assertNotIn("checkpoint_candidates", report)
        self.assertNotIn("validation_loss", report["history"][0])
        self.assertFalse((self.root / "model/checkpoints").exists())

    def test_source_and_prepared_tampering_fail_closed(self):
        self.prepare()
        path = self.out / "prepared/graphs.jsonl"
        path.write_text("tampered\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.prepare(stage="prepare", dry_run=True)
        (self.source / "Ponzi_label.csv").write_text("tampered\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.prepare(stage="cohort")

    def test_changed_count_config_and_insufficient_negatives_are_rejected(self):
        self.prepare(stage="cohort")
        with self.assertRaisesRegex(ValueError, "changed"):
            prepare_ponzi(self.out, self.config, settings=self.settings, source_snapshot=self.source, negative_count=21, stage="cohort")
        with self.assertRaisesRegex(ValueError, "insufficient"):
            build_ponzi_cohort(self.source, negative_count=1000, seed=1, cutoffs=self.cutoffs)
        changed = copy.deepcopy(self.config)
        changed["graph"]["rows_per_action"] = 99
        with self.assertRaisesRegex(ValueError, "recipe"):
            prepare_ponzi(self.out, changed, source_snapshot=self.source, negative_count=20, stage="cohort")

    def test_failed_old_source_root_resumes_with_its_own_cutoff(self):
        from packages.collection import CollectionError
        failed = next(t for t in self.targets if t["cutoff_source"] == "unica")
        collect = RecentHistoryCollector.collect
        def fail_once(collector, target, *args):
            if target["sample_id"] == failed["sample_id"]:
                raise CollectionError("temporarily_unavailable")
            return collect(collector, target, *args)
        with patch.object(RecentHistoryCollector, "collect", new=fail_once), redirect_stderr(io.StringIO()):
            self.assertEqual(self.prepare()["status"], "collection_incomplete")
        seen = []
        def observe(collector, target, graph, end_block, work):
            seen.append((target["sample_id"], end_block))
            return collect(collector, target, graph, end_block, work)
        with patch.object(RecentHistoryCollector, "collect", new=observe):
            self.assertEqual(self.prepare()["status"], "prepared")
        self.assertEqual(seen, [(failed["sample_id"], 100)])

    def test_drop_failed_keeps_cohort_and_never_replaces_or_retries_root(self):
        from packages.collection import CollectionError
        self.prepare(stage="cohort")
        failed = self.targets[0]
        collect = RecentHistoryCollector.collect
        def failure(collector, target, *args):
            if target["sample_id"] == failed["sample_id"]:
                raise CollectionError("recent_normalization_failed:synthetic_bad_amount")
            return collect(collector, target, *args)
        with patch.object(RecentHistoryCollector, "collect", new=failure), redirect_stderr(io.StringIO()):
            self.assertEqual(self.prepare(stage="collect")["status"], "collection_incomplete")
        self.assertEqual(self.prepare(stage="prepare", drop_failed=True, dry_run=True)["status"], "planned")
        self.assertFalse((self.out / "collection/failure_exclusions.json").exists())
        self.assertEqual(self.prepare(stage="prepare", drop_failed=True)["status"], "prepared")
        self.assertEqual(len(read_records(self.out / "cohort/targets.jsonl")), 41)
        self.assertEqual(len(read_records(self.out / "prepared/graphs.jsonl")), 40)
        with patch.object(EtherscanClient, "request", side_effect=AssertionError("HTTP")):
            self.assertEqual(self.prepare()["status"], "prepared")


if __name__ == "__main__":
    unittest.main()
