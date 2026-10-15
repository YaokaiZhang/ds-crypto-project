"""Progress routing and synthetic scoring checks; no real dataset training."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.progress import progress_bar
from research.scam.cli import parser
from research.scam.splitting import split_records
from research.scam.training import _score, train, validate_config
from checks.test_training import supervision_records, synthetic_graph


class ProgressTests(unittest.TestCase):
    def test_visibility_and_stderr_routing(self):
        for mode, tty, visible in (("auto", False, False), ("auto", True, True),
                                   ("on", False, True), ("off", True, False)):
            with self.subTest(mode=mode, tty=tty):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr), patch.object(stderr, "isatty", return_value=tty):
                    with progress_bar(range(2), mode=mode, desc="Synthetic", mininterval=0) as bar:
                        self.assertEqual(list(bar), [0, 1])
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(bool(stderr.getvalue()), visible)
                if visible:
                    self.assertIn("100%", stderr.getvalue())
                    self.assertIn("2/2", stderr.getvalue())
        with self.assertRaisesRegex(ValueError, "progress"):
            progress_bar([], mode="invalid")
        with self.assertRaisesRegex(ValueError, "progress"):
            validate_config({"task_id": "ponzi", "progress": "invalid"})

    def test_cli_controls_and_dry_run_stays_quiet(self):
        for command in ("train", "evaluate"):
            for task in ("ponzi", "phishing", "honeypot", "rug_pull"):
                self.assertEqual(parser().parse_args([command, "--task", task, "--no-progress"]).progress, "off")
                self.assertEqual(parser().parse_args([command, "--task", task, "--progress", "on"]).progress, "on")
        from scripts.train_graphsage import parser as graph_parser
        from scripts.train_tabular_baseline import parser as tabular_parser
        self.assertEqual(graph_parser().parse_args(["--graphs", "unused", "--output", "unused", "--no-progress"]).progress, "off")
        self.assertEqual(tabular_parser().parse_args(["--targets", "unused", "--output", "unused", "--progress", "on"]).progress, "on")
        records = supervision_records()
        splits, _ = split_records(records)
        with patch("research.scam.training.progress_bar", side_effect=AssertionError("dry-run opened a bar")):
            result = train([synthetic_graph(row) for row in records], records, splits,
                           {"task_id": "ponzi", "progress": "on"}, "/unused", dry_run=True)
        self.assertEqual(result["status"], "validated")

    def test_progress_does_not_change_scores(self):
        from packages.graph import fit_scaler
        from packages.models import create_model
        records = supervision_records()[:3]
        graphs = [synthetic_graph(row) for row in records]
        rows = [{"graph": graph, "supervision": record} for graph, record in zip(graphs, records)]
        scaler = fit_scaler(graphs)
        for architecture in ("mean_sage", "directed_edge_sage"):
            config = {"architecture_id": architecture, "hidden_dim": 4, "layers": 2, "dropout": 0.0}
            model = create_model(config, len(graphs[0]["feature_names"]), len(graphs[0]["edge_feature_names"]),
                                 2 * len(graphs[0]["relation_names"]))
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                silent = _score(model, rows, scaler, "cpu", 2, progress="off")
                self.assertEqual(stderr.getvalue(), "")
                visible = _score(model, rows, scaler, "cpu", 2, progress="on")
            self.assertEqual(silent, visible)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("2/2", stderr.getvalue())

    def test_early_stop_counts_final_epoch_without_learning(self):
        records = supervision_records()
        graphs = [synthetic_graph(row) for row in records]
        splits, _ = split_records(records)

        def fixed_scores(model, rows, *args, **kwargs):
            labels = [row["supervision"]["observed_target"] for row in rows]
            return labels, [.8 if label else .2 for label in labels]

        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(stdout), redirect_stderr(stderr), \
                patch("torch.optim.AdamW.step"), patch("research.scam.training._score", side_effect=fixed_scores):
            result = train(graphs, records, splits,
                {"task_id": "ponzi", "epochs": 5, "patience": 1, "batch_size": 32,
                 "model": {"hidden_dim": 4, "dropout": 0}, "progress": "on", "fit_tabular_baselines": False},
                Path(directory) / "synthetic")
        self.assertEqual(len(result["history"]), 2)
        self.assertEqual(result["best_epoch"], 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("early stop", stderr.getvalue())
        self.assertIn("2/5", stderr.getvalue())
        self.assertIn("best_AP=1", stderr.getvalue())
        self.assertIn("patience=1/1", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
