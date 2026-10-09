"""Synthetic contract/loss checks; no dataset collection or training run."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from chainrisk.graph import build_graph_sample
from research.task_b.splitting import assert_partition_isolation, experiment_record, split_records
from research.task_b.training import binary_loss, evaluate_bundle, export_run, metrics, select_threshold, tabular_features, train, validate_config


HAS_TORCH = importlib.util.find_spec("torch") is not None
HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None


def supervision_records() -> list[dict]:
    return [{
        "sample_id": f"sample:{index}", "task_id": "ponzi", "chain_id": 1,
        "entity_id": f"0x{index + 1:040x}", "cutoff": 10_000_000,
        "label_status": "supported_positive" if index < 20 else "supported_negative",
        "observed_target": int(index < 20), "eligible": True,
        "group_id": None, "label_available_at": 9_000_000,
    } for index in range(40)]


def synthetic_graph(record: dict) -> dict:
    target = {
        "sample_id": record["sample_id"], "task_id": record["task_id"],
        "target": record["entity_id"], "chain_id": 1, "cutoff": record["cutoff"],
        "coverage": {"complete": True},
    }
    event = {"event_id": record["sample_id"] + ":event", "timestamp": record["cutoff"] - 100,
             "src": record["entity_id"], "dst": "0x" + "f" * 40,
             "relation": "external_eth", "asset": "ETH", "raw_amount": "1000000000000000000",
             "decimals": 18, "success": True, "chain_id": 1}
    return build_graph_sample(target, [event])


class SplitTests(unittest.TestCase):
    def test_deterministic_class_stratification(self):
        rows = supervision_records()
        split, manifest = split_records(rows)
        reversed_split, reversed_manifest = split_records(list(reversed(rows)))
        self.assertEqual({row["sample_id"]: row["partition"] for row in split},
                         {row["sample_id"]: row["partition"] for row in reversed_split})
        self.assertEqual(manifest, reversed_manifest)
        self.assertEqual(manifest["partition_class_counts"], {
            "train": {"0": 16, "1": 16}, "validation": {"0": 2, "1": 2}, "test": {"0": 2, "1": 2},
        })
        self.assertTrue(all("partition" not in row for row in rows))

    def test_entity_and_connected_verified_groups_stay_together(self):
        rows = supervision_records()
        rows[1]["entity_id"] = rows[0]["entity_id"]
        rows[1]["group_id"] = "campaign:a"
        rows[2]["group_id"] = "campaign:a"
        rows[1].update(group_verified=True, group_ref="independent campaign evidence")
        rows[2].update(group_verified=True, group_ref="independent campaign evidence")
        split, _ = split_records(rows)
        partitions = {row["partition"] for row in split[:3]}
        self.assertEqual(len(partitions), 1)
        split[0]["partition"] = next(part for part in ("train", "validation", "test") if part not in partitions)
        with self.assertRaisesRegex(ValueError, "leakage"):
            assert_partition_isolation(split)

    def test_pu_does_not_rewrite_canonical_unknown(self):
        rows = supervision_records()
        for row in rows:
            row["task_id"] = "phishing"
            if row["observed_target"] == 0:
                row.update(label_status="unlabeled", eligible=False, observed_target=None,
                           data_eligible=True, background_selected=True, cohort_id="frozen:one")
        before = copy.deepcopy(rows)
        split, manifest = split_records(rows, mode="known_positive_vs_unlabeled")
        self.assertEqual(rows, before)
        unknown = split[-1]
        self.assertEqual(unknown["label_status"], "unlabeled")
        self.assertFalse(unknown["eligible"])
        self.assertTrue(unknown["experiment_eligible"])
        self.assertEqual(unknown["observed_target"], 0)
        self.assertIn("not verified benign", manifest["negative_meaning"])

    def test_pu_rejects_unfrozen_or_temporally_unresolved(self):
        row = {"sample_id": "x", "task_id": "phishing", "label_status": "unlabeled",
               "eligible": False, "data_eligible": True}
        self.assertFalse(experiment_record(row, "known_positive_vs_unlabeled")["experiment_eligible"])
        row.update(background_selected=True, cohort_id="cohort", label_status="temporally_unresolved")
        self.assertFalse(experiment_record(row, "known_positive_vs_unlabeled")["experiment_eligible"])

    def test_insufficient_support_and_duplicate_fail(self):
        with self.assertRaisesRegex(ValueError, "support"):
            split_records(supervision_records()[:8])
        rows = supervision_records()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            split_records(rows + [rows[0]])

    def test_training_as_of_guard(self):
        with self.assertRaisesRegex(ValueError, "training_as_of"):
            split_records(supervision_records(), training_as_of=8_000_000)

    def test_campaign_requires_explicit_verification_and_reference(self):
        rows = supervision_records()
        rows[0]["group_id"] = rows[1]["group_id"] = "unverified-campaign"
        _, manifest = split_records(rows)
        self.assertEqual(manifest["independent_groups"], 40)
        rows[0]["group_verified"] = True
        with self.assertRaisesRegex(ValueError, "evidence reference"):
            split_records(rows)


class ConfigurationAndMergeTests(unittest.TestCase):
    def test_checked_in_configs_validate(self):
        directory = Path(__file__).resolve().parents[1] / "research/task_b/configs"
        for task in ("phishing", "ponzi", "honeypot", "rug_pull"):
            config = json.loads((directory / f"{task}.json").read_text())
            self.assertEqual(validate_config(config)["task_id"], task)

    def test_nnpu_is_explicitly_deferred(self):
        config = {"task_id": "phishing", "experiment_mode": "nnpu", "loss": {"name": "nnpu"}}
        with self.assertRaisesRegex(NotImplementedError, "not implemented"):
            validate_config(config)

    def test_data_only_branches_do_not_enter_training(self):
        for task in ("honeypot", "rug_pull"):
            result = train([], [], [], {"task_id": task}, "/unused")
            self.assertEqual(result["status"], "data_only")

    def test_dry_run_and_quality_gate_without_fitting(self):
        rows = supervision_records()
        split, _ = split_records(rows)
        graphs = [synthetic_graph(row) for row in rows]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created"
            report = train(graphs, rows, split, {"task_id": "ponzi"}, output, dry_run=True)
            self.assertEqual(report["status"], "validated")
            self.assertFalse(output.exists())
            graphs[0]["quality"]["coverage_complete"] = False
            with self.assertRaisesRegex(ValueError, "quality"):
                train(graphs, rows, split, {"task_id": "ponzi"}, output, dry_run=True)


@unittest.skipUnless(HAS_SKLEARN, "scikit-learn is not installed")
class MetricsTests(unittest.TestCase):
    def test_average_precision_groups_tied_scores(self):
        self.assertEqual(metrics([0, 1], [0.5, 0.5])["average_precision"], 0.5)
        self.assertEqual(metrics([1, 0], [0.5, 0.5])["average_precision"], 0.5)

    def test_validation_threshold_and_graph_summary_features(self):
        threshold = select_threshold([0, 0, 1, 1], [0.1, 0.2, 0.6, 0.8])
        self.assertEqual(metrics([0, 0, 1, 1], [0.1, 0.2, 0.6, 0.8], threshold)["macro_f1"], 1)
        graph = synthetic_graph(supervision_records()[0])
        self.assertEqual(tabular_features(graph), graph["node_features"][graph["root_index"]])
        self.assertGreater(len(tabular_features(graph, True)), len(tabular_features(graph)))


@unittest.skipUnless(HAS_TORCH, "PyTorch is not installed")
class NumericalTests(unittest.TestCase):
    def test_focal_gamma_zero_equals_bce_value_and_gradient(self):
        import torch
        targets = torch.tensor([0.0, 1.0, 1.0, 0.0])
        left = torch.tensor([-50.0, 1.5, -2.0, 50.0], requires_grad=True)
        right = left.detach().clone().requires_grad_()
        expected = torch.nn.functional.binary_cross_entropy_with_logits(left, targets, pos_weight=torch.tensor(3.0))
        actual = binary_loss(right, targets, {"name": "focal", "gamma": 0.0}, 3.0)
        self.assertTrue(torch.allclose(expected, actual))
        expected.backward()
        actual.backward()
        self.assertTrue(torch.allclose(left.grad, right.grad))

    def test_unknown_mask_has_no_gradient(self):
        import torch
        logits = torch.tensor([0.3, 10.0, -0.2], requires_grad=True)
        targets = torch.tensor([1.0, float("nan"), 0.0])
        loss = binary_loss(logits, targets, {"name": "weighted_bce"}, 1.0, torch.tensor([True, False, True]))
        loss.backward()
        self.assertEqual(logits.grad[1].item(), 0.0)

    def test_nnpu_loss_is_explicitly_deferred(self):
        import torch
        with self.assertRaisesRegex(NotImplementedError, "not implemented"):
            binary_loss(torch.tensor([0.0, 0.0]), torch.tensor([1.0, 0.0]), {"name": "nnpu"}, 1.0)

    def test_single_batch_each_backbone_and_export(self):
        import torch
        from chainrisk.graph import RELATION_NAMES, batch_graph_samples, fit_scaler
        from chainrisk.models import create_model
        from chainrisk.bundle import export_model_bundle, predict_bundle
        rows = supervision_records()
        graphs = [synthetic_graph(rows[0]), synthetic_graph(rows[-1])]
        scaler = fit_scaler(graphs)
        batch = batch_graph_samples(graphs, scaler)
        for architecture in ("mean_sage", "directed_edge_sage"):
            config = {"architecture_id": architecture, "hidden_dim": 8, "layers": 2, "dropout": 0.0}
            model = create_model(config, len(graphs[0]["feature_names"]), len(graphs[0]["edge_feature_names"]), 2 * len(RELATION_NAMES))
            optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)
            logits = model(batch)
            self.assertEqual(logits.shape, torch.Size([2]))
            loss = binary_loss(logits, torch.tensor([1.0, 0.0]), {"name": "weighted_bce"}, 1.0)
            loss.backward()
            optimizer.step()
            self.assertTrue(torch.isfinite(model(batch)).all())
            with tempfile.TemporaryDirectory() as directory:
                export_model_bundle(Path(directory), model, config, scaler, "ponzi", 0.5, {"synthetic_smoke_only": True})
                predictions = predict_bundle(Path(directory), graphs)
                self.assertEqual(len(predictions), 2)
                self.assertTrue(all(record["score"] is not None for record in predictions))
                self.assertEqual(export_run(directory)["status"], "exported")
                if architecture == "directed_edge_sage":
                    split, _ = split_records(rows)
                    all_graphs = [synthetic_graph(row) for row in rows]
                    validated = evaluate_bundle(directory, all_graphs, rows, split, dry_run=True)
                    self.assertFalse(validated["prediction_performed"])
                    changed = [build_graph_sample({"sample_id": row["sample_id"], "task_id": "ponzi",
                        "target": row["entity_id"], "cutoff": row["cutoff"], "coverage": {"complete": True}},
                        [{"event_id": row["sample_id"], "timestamp": row["cutoff"] - 100, "src": row["entity_id"],
                          "dst": "0x" + "f" * 40, "relation": "external_eth", "asset": "ETH",
                          "raw_amount": "1", "decimals": 18, "success": True}], fanouts=(8, 4)) for row in rows]
                    with self.assertRaisesRegex(ValueError, "graph recipe"):
                        evaluate_bundle(directory, changed, rows, split, dry_run=True)
                    evaluated = evaluate_bundle(directory, all_graphs, rows, split)
                    self.assertFalse(evaluated["fitting_performed"])
                    self.assertFalse(evaluated["threshold_selection_performed"])
                    self.assertEqual(evaluated["metrics"]["rows"], 4)


if __name__ == "__main__":
    unittest.main()
