"""Source-defined admission, frozen preparation and trainer validation only."""
import copy
from contextlib import redirect_stdout, redirect_stderr
import io
import unittest
from unittest.mock import patch

from checks import test_rug_pull_graphs as fixtures
from checks.test_rug_pull_graphs import addr
from packages.io import load_json, read_records, write_records
from packages.labeling import reconcile_labels, TOKENSCOUT_RETROSPECTIVE_POLICY
from research.scam.rug_pull import _manifest
from research.scam.rug_pull_training import prepare_training
from research.scam.pipeline import main as runner


class RugPullTrainingTests(unittest.TestCase):
    chain = fixtures.RugPullGraphTests.chain
    run_graphs = fixtures.RugPullGraphTests.run_graphs

    def setUp(self):
        fixtures.RugPullGraphTests.setUp(self)
        template = self.targets[0]
        self.targets, labels = [], []
        for n in range(1, 25):
            target = copy.deepcopy(template)
            target.update(sample_id=f"ts-{n}", target=addr(n), pools=[addr(n + 1000)])
            target["pool_metadata"][0].update(pool=addr(n + 1000), token0=addr(n))
            self.targets.append(target)
            labels.append({"sample_id": target["sample_id"], "token_address": target["target"],
                "pool_addresses": target["pools"], "cutoff": target["cutoff"], "pool_verified": True,
                "label": int(n <= 12), "source": "tokenscout", "source_label": "rugpull" if n <= 12 else "truthworthy",
                "label_policy": "tokenscout-source-defined-retrospective-1", "training_eligible": False})
        # Two target tokens share a real selected-pool identity: no split leakage.
        for n in (1, 13):
            self.targets[n-1]["pools"] = [addr(1001)]
            self.targets[n-1]["pool_metadata"][0].update(pool=addr(1001), token0=addr(1), token1=addr(13))
            labels[n-1]["pool_addresses"] = [addr(1001)]
        paths = [self.out / "pools/verified_targets.jsonl", self.out / "labels/verified_labels.jsonl"]
        write_records(paths[0], self.targets)
        write_records(paths[1], labels)
        manifest = self.out / "pools/verification_manifest.json"
        manifest.unlink()
        _manifest(manifest, paths, verified_tokens=24)

    def test_preparation_preserves_source_limits_and_frozen_split_and_resumes(self):
        def chain(query):
            if query["address"] == addr(2):
                raise ValueError("synthetic_invalid_event")
            return self.chain(query)
        self.settings["collection"]["transport"] = chain
        self.run_graphs("graphs")
        root = self.out / "graph_runs/recent-v1"
        report = prepare_training(root, dry_run=True)
        self.assertEqual(report["targets"], 23)
        self.assertFalse((root / "prepared").exists())
        with patch("packages.collection.urlopen", side_effect=AssertionError("network")):
            report = prepare_training(root)
        self.assertFalse(report["fitting_performed"])
        self.assertEqual(report["selection"]["source_class_counts"], {"1": 11, "0": 12})
        self.assertEqual(len(report["selection"]["excluded"]), 1)
        rows = read_records(root / "prepared/supervision.jsonl")
        self.assertTrue(all(r["eligible"] and r["independent_mechanism_validation"] is False for r in rows))
        self.assertTrue(all(r["label_available_at"] is None and r["valid_from"] is None and r["incident_tx"] is None for r in rows))
        splits = read_records(root / "prepared/splits.jsonl")
        self.assertEqual({r["partition"] for r in splits}, {"train", "validation"})
        self.assertEqual(len({r["partition"] for r in splits if addr(1001) in r["pool_addresses"]}), 1)
        config = load_json(root / "prepared/training_config.json")
        self.assertEqual(config["graph"], load_json(root / "plan.json")["recipe"]["graph"])
        self.assertIsNone(config["training_as_of"])
        self.assertEqual(prepare_training(root)["inputs"], report["inputs"])
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(runner(["--task", "rug_pull", "--snapshot", "test", "--output", str(self.out),
                "--stage", "prepare", "--dry-run"]), 0)
            self.assertEqual(runner(["--task", "rug_pull", "--snapshot", "test", "--output", str(self.out),
                "--stage", "train", "--run", "dry", "--dry-run"]), 0)
        graph_path = root / "prepared/graphs.jsonl"
        graph_path.write_text(graph_path.read_text() + "{}\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            prepare_training(root)

    def test_unfinished_collection_cannot_become_implicit_exclusion(self):
        self.run_graphs("graphs")
        root = self.out / "graph_runs/recent-v1"
        (root / "samples/ts-1/collect.json").unlink()
        with self.assertRaisesRegex(ValueError, "unfinished"):
            prepare_training(root)
        self.assertFalse((root / "prepared").exists())

    def test_generic_incident_policy_remains_strict_and_source_exception_is_scoped(self):
        target = {**self.targets[0], "role": "token_contract"}
        record = {"task_id": "rug_pull", "entity_id": target["target"], "role": "token_contract",
            "mapped_label": 1, "label_status": "supported_positive", "audit_decision": "admitted",
            "pool_addresses": target["pools"], "source_id": "tokenscout", "source_label": "rugpull",
            "source_sha256": "a" * 64, "evidence_ref": "synthetic://source",
            "label_version": TOKENSCOUT_RETROSPECTIVE_POLICY,
            "audit_basis": "user_adopted_source_defined_retrospective_experiment", "independent_mechanism_validation": False}
        self.assertFalse(reconcile_labels([record], [target])[0]["eligible"])
        self.assertTrue(reconcile_labels([record], [target], source_label_policy=TOKENSCOUT_RETROSPECTIVE_POLICY)[0]["eligible"])
        altered = {**record, "source_id": "rug_incidents"}
        self.assertFalse(reconcile_labels([altered], [target], source_label_policy=TOKENSCOUT_RETROSPECTIVE_POLICY)[0]["eligible"])
        with self.assertRaisesRegex(ValueError, "no_label_availability"):
            reconcile_labels([record], [target], 1, source_label_policy=TOKENSCOUT_RETROSPECTIVE_POLICY)

    def test_training_dispatch_uses_frozen_inputs_and_stops_on_failed_verification(self):
        args = ["--task", "rug_pull", "--snapshot", "test", "--output", str(self.out),
            "--stage", "train", "--graph-run", "recent-v1", "--run", "dry", "--dry-run",
            "--epochs", "10", "--patience", "3", "--min-delta", "0.002"]
        with patch("research.scam.pipeline.invoke", return_value=(0, {}, "")) as verify, patch(
                "research.scam.pipeline.scam_main", return_value=0) as train, redirect_stdout(io.StringIO()):
            self.assertEqual(runner(args), 0)
        check = verify.call_args.args[0]
        self.assertEqual(check[0], "prepare-rug-pull")
        self.assertIn("--dry-run", check)
        command = train.call_args.args[0]
        self.assertEqual(command[:3], ["train", "--task", "rug_pull"])
        self.assertEqual(command[command.index("--config") + 1], str(self.out.resolve() / "graph_runs/recent-v1/prepared/training_config.json"))
        self.assertEqual(command[command.index("--patience") + 1], "3")
        self.assertEqual(command[command.index("--epochs") + 1], "10")
        self.assertEqual(command[command.index("--min-delta") + 1], "0.002")
        with patch("research.scam.pipeline.invoke", return_value=(2, {}, "checksum mismatch")), patch(
                "research.scam.pipeline.scam_main") as train, redirect_stdout(io.StringIO()):
            self.assertEqual(runner(args), 2)
        train.assert_not_called()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(runner(args + ["--graph-limit", "1"]), 2)
            self.assertEqual(runner(["--task", "rug_pull", "--snapshot", "test", "--stage", "prepare", "--epochs", "1"]), 2)
