"""Public stage semantics, full-flow dispatch and side-effect boundaries."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.scam import pipeline


class UnifiedPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "dataset"

    def call(self, task, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = pipeline.main(["--task", task, "--snapshot", "fixture", "--output", str(self.out),
                                  "--progress", "off", "--retry-delay", "0", *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_all_four_tasks_dispatch_every_stage_and_then_train(self):
        for task in ("phishing", "ponzi", "honeypot", "rug_pull"):
            with self.subTest(task=task):
                calls = []

                def operation(command, out, stage, *args):
                    calls.append((stage, command[command.index("--stage") + 1], command))
                    return 0, {"status": "complete"}, ""

                def fit(args, out, *, verify):
                    self.assertFalse(verify)  # prepare just validated the same frozen inputs.
                    self.assertEqual(args.run, "new-model")
                    calls.append(("train", None, None))
                    return 0

                with patch.object(pipeline, "invoke", side_effect=operation), patch.object(pipeline, "train", side_effect=fit):
                    code, _, error = self.call(task, "--stage", "all", "--run", "new-model")
                self.assertEqual(code, 0, error)
                self.assertEqual([c[0] for c in calls], list(pipeline.STAGES))
                expected = ["all", "graphs", "prepare-training"] if task in pipeline.TOKEN_TASKS else ["cohort", "collect", "prepare"]
                self.assertEqual([c[1] for c in calls[:-1]], expected)

    def test_missing_run_and_old_stage_names_fail_before_any_work(self):
        for task in ("phishing", "ponzi", "honeypot", "rug_pull"):
            with self.subTest(task=task), patch.object(pipeline, "invoke") as work:
                for stage in ("all", "train", "audit", "evidence", "graphs", "prepare-training", "addresses"):
                    code, _, _ = self.call(task, "--stage", stage)
                    self.assertEqual(code, 2)
                work.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_new_snapshot_dry_run_plans_training_without_network_or_writes(self):
        for task in ("phishing", "ponzi", "honeypot", "rug_pull"):
            with self.subTest(task=task), patch.object(pipeline, "invoke", side_effect=AssertionError("work")), patch.object(
                    pipeline, "train", side_effect=AssertionError("fit")), patch(
                    "urllib.request.urlopen", side_effect=AssertionError("network")):
                code, output, error = self.call(task, "--stage", "all", "--run", "dry", "--dry-run")
            self.assertEqual(code, 0, error)
            report = json.loads(output)
            self.assertEqual(report["stages"], list(pipeline.STAGES))
            self.assertEqual(report["training_validation"], "deferred_until_prepared_inputs_exist")
            self.assertFalse(report["training_started"])
        self.assertFalse(self.out.exists())

    def test_failed_data_stage_stops_all_before_training(self):
        for fail in ("sources", "collect", "prepare"):
            calls = []

            def operation(command, out, stage, *args):
                calls.append(stage)
                return (2, {}, "checksum_mismatch") if stage == fail else (0, {}, "")

            with self.subTest(stage=fail), patch.object(pipeline, "invoke", side_effect=operation), patch.object(pipeline, "train") as fit:
                self.assertEqual(self.call("phishing", "--stage", "all", "--run", "new")[0], 2)
                fit.assert_not_called()
            self.assertEqual(calls, list(pipeline.STAGES[:pipeline.STAGES.index(fail) + 1]))

    def test_existing_model_run_is_rejected_before_collection(self):
        destination = self.root / "model"
        destination.mkdir()
        (destination / "training_summary.json").write_text("{}")
        with patch.object(pipeline, "model_path", return_value=destination), patch.object(pipeline, "invoke") as work:
            code, _, error = self.call("ponzi", "--stage", "all", "--run", "existing")
        self.assertEqual(code, 2)
        self.assertIn("model_run_exists", error)
        work.assert_not_called()

    def test_token_source_overrides_do_not_leak_to_graph_or_training_preparation(self):
        calls = []
        with patch.object(pipeline, "invoke", side_effect=lambda c, *args: (calls.append(c) or (0, {}, ""))), patch.object(
                pipeline, "train", return_value=0):
            code, _, error = self.call("rug_pull", "--stage", "all", "--run", "new", "--positive-count", "1500",
                                      "--negative-count", "1600", "--historical-cutoff", "2023-02-28T23:59:59Z")
        self.assertEqual(code, 0, error)
        self.assertIn("--positive-count", calls[0])
        self.assertTrue(all("--positive-count" not in c and "--historical-cutoff" not in c for c in calls[1:]))

    def test_data_stages_never_start_training(self):
        for stage in pipeline.STAGES[:-1]:
            with self.subTest(stage=stage), patch.object(pipeline, "invoke", return_value=(0, {}, "")), patch.object(pipeline, "train") as fit:
                self.assertEqual(self.call("phishing", "--stage", stage)[0], 0)
                fit.assert_not_called()

    def test_public_module_and_legacy_launcher_import_use_same_main(self):
        from research.scam.cli import main as legacy
        from scripts.scam.run_pipeline import main as file_main
        self.assertIs(legacy, pipeline.main)
        self.assertIs(file_main, pipeline.main)


if __name__ == "__main__":
    unittest.main()
