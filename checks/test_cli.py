"""CLI integration checks; preparation and dry-run only, never training."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.io import read_records, write_records
from research.scam._commands import main
from checks.generate_fixtures import generate


class CLITests(unittest.TestCase):
    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(args))
        self.assertEqual(code, 0, stderr.getvalue())
        return json.loads(stdout.getvalue())

    def test_unlabeled_prediction_resolves_auto_device(self):
        from packages.bundle import export_model_bundle
        from packages.graph import RELATION_NAMES, build_graph_sample, fit_scaler
        from packages.models import create_model
        target = {"sample_id": "auto-device", "task_id": "ponzi", "target": "0x" + "1" * 40,
                  "cutoff": 100, "chain_id": 1, "coverage": {"complete": True}}
        event = {"event_id": "synthetic-auto", "chain_id": 1, "timestamp": 90,
                 "src": target["target"], "dst": "0x" + "2" * 40, "relation": "external_eth",
                 "asset": "ETH", "raw_amount": "1000000000000000000", "decimals": 18, "success": True}
        graph = build_graph_sample(target, [event])
        config = {"architecture_id": "mean_sage", "hidden_dim": 4, "layers": 2, "dropout": 0.0}
        model = create_model(config, len(graph["feature_names"]), len(graph["edge_feature_names"]), 2 * len(RELATION_NAMES))
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            write_records(directory / "graphs.jsonl", [graph])
            export_model_bundle(directory / "bundle", model, config, fit_scaler([graph]), "ponzi", .5, {"synthetic_only": True})
            with patch("torch.cuda.is_available", return_value=False), patch("torch.backends.mps.is_available", return_value=False):
                result = self.invoke("predict", "--task", "ponzi", "--device", "auto",
                                     "--graphs", str(directory / "graphs.jsonl"), "--bundle", str(directory / "bundle"),
                                     "--output", str(directory / "predictions.jsonl"))
            self.assertIsNotNone(result["results"][0]["score"])
            self.assertNotIn("observed_target", result["results"][0])

    def test_preparation_dry_run_unavailable_prediction_and_resolution(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            fixture = directory / "fixtures"
            generate(fixture)
            events = str(directory / "events.jsonl")
            result = self.invoke("normalize", "--task", "phishing", "--input", str(fixture / "raw_events.jsonl"), "--output", events)
            self.assertTrue(result["audit"]["complete"])
            for task in ("phishing", "ponzi"):
                labels, supervision, graphs, splits = [str(directory / f"{task}-{name}.jsonl") for name in ("labels", "supervision", "graphs", "splits")]
                self.invoke("import-labels", "--task", task, "--source", "audited", "--input", str(fixture / "audited_labels.csv"), "--output", labels)
                self.invoke("label", "--task", task, "--input", labels, "--targets", str(fixture / "targets.jsonl"), "--output", supervision)
                result = self.invoke("build-graphs", "--task", task, "--events", events, "--targets", str(fixture / "targets.jsonl"), "--output", graphs)
                self.assertEqual(result["quality_status_counts"], {"ok": 20})
                self.invoke("split", "--task", task, "--supervision", supervision, "--output", splits)
                result = self.invoke("train", "--task", task, "--graphs", graphs, "--supervision", supervision, "--splits", splits, "--dry-run")
                self.assertEqual(result["status"], "validated")
                self.assertFalse((directory / "bundle").exists())
                predictions = str(directory / f"{task}-predictions.jsonl")
                self.invoke("predict", "--task", task, "--graphs", graphs, "--output", predictions)
                self.assertTrue(all(row["score"] is None and row["status"] == "model_unavailable" for row in read_records(predictions)))
                empty_bundle = directory / f"{task}-empty-bundle"
                empty_bundle.mkdir()
                result = self.invoke("predict", "--task", task, "--graphs", graphs,
                                     "--bundle", str(empty_bundle), "--output", predictions)
                self.assertTrue(all(row["status"] == "model_unavailable" for row in result["results"]))
            result = self.invoke("resolve-transaction", "--input", str(fixture / "transaction.json"))
            self.assertIsNone(result["score"])
            self.assertTrue(result["requires_entity_history"])
            result = self.invoke("collect", "--task", "ponzi", "--targets", str(fixture / "targets.jsonl"), "--dry-run")
            self.assertTrue(result["dry_run"])
            for task in ("honeypot", "rug_pull"):
                error = io.StringIO()
                with redirect_stderr(error):
                    self.assertEqual(main(["train", "--task", task, "--dry-run"]), 2)
                self.assertIn("--graphs is required", error.getvalue())
                graph_file = str(directory / f"{task}-graphs.jsonl")
                result = self.invoke("build-graphs", "--task", task, "--events", events, "--targets", str(fixture / "targets.jsonl"), "--output", graph_file)
                self.assertEqual(result["graphs"], 1)

    def test_mixed_parquet_preserves_late_fields_and_nested_lineage(self):
        rows = [{"event_id": "a", "raw_amount": "1000000000000000000000", "lineage": {"source": "normal"}},
                {"event_id": "b", "pool": "synthetic-pool", "lineage": {"source": "logs", "log_index": 2}}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.parquet"
            write_records(path, rows)
            self.assertEqual(read_records(path), rows)

    def test_command_task_config_mismatch_is_rejected(self):
        output = io.StringIO()
        with redirect_stderr(output):
            code = main(["train", "--task", "ponzi", "--config", str(Path(__file__).parent.parent / "research/scam/configs/phishing.json"), "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("does not match", output.getvalue())


if __name__ == "__main__":
    unittest.main()
