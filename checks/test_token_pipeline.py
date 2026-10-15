"""Token data admission and frozen-model checks; no formal training or network."""
import copy
import io
import json
import math
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.collection import CollectionError, collect_dataset
from packages.graph import build_graph_sample, fit_scaler, graph_is_usable, graph_schema, batch_graph_samples
from packages.io import read_records, write_records
from packages.labeling import import_labels, reconcile_labels
from packages.token import TOKEN_VIEW_VERSION, UNISWAP_V2_FACTORY, token_scope
from packages.token_sources import SnapshotClient, verify_token_targets, collect_honeypot_evidence
from research.scam.cli import main
from research.scam.preparation import prepare_dataset
from research.scam.splitting import split_records, assert_partition_isolation
from research.scam.training import train, evaluate_bundle
from checks.token_fixtures import addr, token_target, token_events, token_label, attach_coverage


class TokenGraphTests(unittest.TestCase):
    def test_collected_emitter_scope_is_trainable_without_wallet_histories(self):
        from checks.test_data import log
        for task in ("honeypot", "rug_pull"):
            target = token_target(task)
            pool = target["pools"][0]
            row = log(address=target["target"], timeStamp=str(target["cutoff"] - 1),
                      topics=[log()["topics"][0], "0x" + addr(9)[2:].rjust(64, "0"), "0x" + pool[2:].rjust(64, "0")])
            def transport(query):
                return {"status": "1", "result": [row] if query["action"] == "getLogs" and query["address"] == target["target"] else []}
            with tempfile.TemporaryDirectory() as directory:
                report = collect_dataset([target], directory, {"transport": transport})
                self.assertTrue(report["complete"])
                self.assertFalse(report["coverage"][0]["neighborhood_history_complete"])
                collected_target = read_records(Path(directory) / "targets_with_coverage.jsonl")[0]
                graph = build_graph_sample(collected_target, read_records(Path(directory) / "events.jsonl"))
                self.assertTrue(graph_is_usable(graph))

    def test_mechanism_amounts_reserves_and_pair_order(self):
        target = token_target()
        events = token_events(target)
        graph = build_graph_sample(target, events)
        self.assertTrue(graph_is_usable(graph))
        self.assertEqual(graph["graph_view_version"], TOKEN_VIEW_VERSION)
        features = dict(zip(graph["feature_names"], graph["node_features"][0]))
        self.assertAlmostEqual(features["log_buy_target_amount"], math.log1p(2))
        self.assertAlmostEqual(features["log_sell_target_amount"], math.log1p(1))
        self.assertAlmostEqual(features["max_reserve_drop_fraction"], .4)
        self.assertEqual(features["dex_amount_missing_fraction"], 0)
        self.assertEqual(features["reserve_history_missing"], 0)
        swapped = copy.deepcopy(target)
        swapped["pool_metadata"][0].update(token0=addr(9), token1=target["target"])
        attach_coverage(swapped)
        changed = copy.deepcopy(events)
        for row in changed:
            for left, right in (("amount0_in", "amount1_in"), ("amount0_out", "amount1_out"),
                                ("amount0", "amount1"), ("reserve0", "reserve1")):
                if left in row:
                    row[left], row[right] = row[right], row[left]
        other = build_graph_sample(swapped, changed)
        self.assertEqual(graph["node_features"], other["node_features"])

    def test_scope_gaps_unknowns_and_pool_budget(self):
        target = token_target()
        for change in ("metadata", "source", "hash", "time"):
            broken = copy.deepcopy(target)
            if change == "metadata":
                broken["pool_metadata"][0]["verified_at_block"] += 1
            elif change == "source":
                broken["coverage"]["sources"].pop()
            elif change == "hash":
                broken["coverage"]["scope_sha256"] = "other"
            else:
                broken["coverage"]["end_timestamp"] += 1
            self.assertFalse(graph_is_usable(build_graph_sample(broken, token_events(target))))
        with self.assertRaisesRegex(ValueError, "retain_selected_pools"):
            build_graph_sample(target, token_events(target), max_nodes=1)
        graph = build_graph_sample(target, token_events(target), fanouts=(1, 1), max_nodes=3)
        self.assertIn(target["pools"][0], graph["node_refs"])
        self.assertIn("contains", [graph["relation_names"][i] for i in graph["relation_ids"]])
        missing = token_events(target)
        del missing[1]["amount0_in"]
        graph = build_graph_sample(target, missing)
        self.assertGreater(graph["node_features"][0][graph["feature_names"].index("dex_amount_missing_fraction")], 0)

    def test_future_block_and_tampered_scope_cannot_pass_quality(self):
        target = token_target()
        events = token_events(target)
        events[0]["block_number"] = target["cutoff_block"] + 1
        self.assertFalse(graph_is_usable(build_graph_sample(target, events)))
        graph = build_graph_sample(target, token_events(target))
        graph["lineage"]["token_scope"]["decimals"] = 6
        self.assertFalse(graph_is_usable(graph))

    def test_cutoff_foreign_events_and_label_independence(self):
        target = token_target()
        events = token_events(target)
        graph = build_graph_sample(target, events)
        future = dict(events[6], event_id="future", timestamp=target["cutoff"] + 1, reserve0="1")
        foreign = token_events(token_target(index=1))
        other = build_graph_sample(dict(target, label=1, api_risk=100), list(reversed(events)) + foreign + [future])
        self.assertEqual(graph["node_features"], other["node_features"])
        self.assertEqual(graph["edge_attributes"], other["edge_attributes"])
        duplicate = dict(events[1], amount0_in="1")
        self.assertFalse(graph_is_usable(build_graph_sample(target, events + [duplicate])))


class TokenSourceTests(unittest.TestCase):
    def snapshot(self, value=False, success=True):
        target = token_target()
        response = {"token": {"address": target["target"]}, "chain": {"id": 1},
                    "pair": {"pair": {"address": target["pools"][0], "type": "UniswapV2"}},
                    "simulationSuccess": success, "honeypotResult": {"isHoneypot": value}}
        return {"request": {"address": target["target"], "pair": target["pools"][0], "chainID": 1},
                "response": response, "checked_at": target["cutoff"], "evidence_ref": "synthetic://api",
                "response_sha256": SnapshotClient.checksum(response)}

    def test_api_polarity_review_unknowns_and_time(self):
        target = token_target()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.jsonl"
            snapshot = self.snapshot()
            write_records(path, [snapshot])
            records = import_labels("honeypot_is", path, "honeypot")
            self.assertFalse(reconcile_labels(records, [target])[0]["eligible"])
            snapshot["audit_decision"] = "reviewed"
            write_records(path, [snapshot])
            records = import_labels("honeypot_is", path, "honeypot")
            self.assertEqual(reconcile_labels(records, [target])[0]["observed_target"], 0)
            self.assertFalse(reconcile_labels(records, [dict(target, cutoff=target["cutoff"] - 1)])[0]["eligible"])
            for value, success in ((None, True), (False, False)):
                snapshot = self.snapshot(value, success)
                snapshot["audit_decision"] = "reviewed"
                write_records(path, [snapshot])
                self.assertIsNone(import_labels("honeypot_is", path, "honeypot")[0]["mapped_label"])
            snapshot = self.snapshot(True, False)
            snapshot["audit_decision"] = "reviewed"
            write_records(path, [snapshot])
            self.assertEqual(import_labels("honeypot_is", path, "honeypot")[0]["mapped_label"], 1)
            snapshot["response"]["token"]["address"] = addr(9999)
            write_records(path, [snapshot])
            with self.assertRaisesRegex(ValueError, "checksum"):
                import_labels("honeypot_is", path, "honeypot")

    def test_api_snapshots_cannot_backdate_validity(self):
        target = token_target()
        snapshot = self.snapshot(True)
        snapshot.update(audit_decision="reviewed", valid_from=target["cutoff"] - 1000,
                        valid_to=target["cutoff"] + 1000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.jsonl"
            write_records(path, [snapshot])
            record = import_labels("honeypot_is", path, "honeypot")[0]
            self.assertEqual(record["valid_from"], target["cutoff"])
            self.assertEqual(record["valid_to"], target["cutoff"])

    def test_changed_labels_conflict_only_in_same_time_and_pool_scope(self):
        first = token_target()
        second = dict(first, sample_id="later", cutoff=first["cutoff"] + 100)
        negative, positive = token_label(first, False), token_label(second, True)
        negative.update(valid_from=first["cutoff"], valid_to=first["cutoff"])
        positive.update(valid_from=second["cutoff"], valid_to=second["cutoff"])
        records = reconcile_labels([negative, positive], [first, second])
        self.assertEqual([row["observed_target"] for row in records], [0, 1])
        positive.update(valid_from=first["cutoff"], valid_to=second["cutoff"])
        self.assertEqual(reconcile_labels([negative, positive], [first])[0]["label_status"], "disputed")

    def test_rug_incident_scope_and_attribution(self):
        target = token_target("rug_pull")
        row = token_label(target)
        row.update(chain_id=1, mechanism="malicious_liquidity_withdrawal_v2")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incidents.jsonl"
            write_records(path, [row])
            records = import_labels("rug_incidents", path, "rug_pull")
            self.assertTrue(reconcile_labels(records, [target])[0]["eligible"])
            row["controller_evidence_ref"] = None
            write_records(path, [row])
            self.assertFalse(reconcile_labels(import_labels("rug_incidents", path, "rug_pull"), [target])[0]["eligible"])
            record = token_label(target)
            record["incident_onset"] = target["cutoff"] + 1
            self.assertFalse(reconcile_labels([record], [target])[0]["eligible"])
            record = token_label(target)
            record["pool_addresses"] = [addr(9999)]
            self.assertFalse(reconcile_labels([record], [target])[0]["eligible"])

    def test_rpc_verification_capture_cache_and_network_opt_in(self):
        target = token_target()
        pool = target["pools"][0]
        quote = target["pool_metadata"][0]["token1"]
        observed = []
        def transport(source, query):
            observed.append((source, query))
            if source == "honeypot_is":
                return self.snapshot()["response"]
            method = query["method"]
            if method == "eth_chainId":
                result = "0x1"
            elif method == "eth_getBlockByNumber":
                result = {"number": "0x64", "timestamp": hex(target["cutoff"]), "hash": "0x" + "a" * 64}
            else:
                self.assertEqual(query["params"][1], {"blockHash": "0x" + "a" * 64, "requireCanonical": True})
                selector = query["params"][0]["data"][:10]
                result = {"0x313ce567": hex(18), "0x0dfe1681": target["target"], "0xd21220a7": quote,
                          "0xc45a0155": UNISWAP_V2_FACTORY, "0xe6a43905": pool}[selector]
                result = "0x" + result[2:].rjust(64, "0")
            return {"result": result}
        with tempfile.TemporaryDirectory() as directory:
            report = verify_token_targets([target], directory, {"transport": transport})
            verified = read_records(report["output"])[0]
            self.assertEqual(token_scope(verified)["decimals"], 18)
            count = len(observed)
            verify_token_targets([target], directory, {"transport": transport})
            self.assertEqual(len(observed), count)
            with patch("packages.token_sources.time.time", return_value=target["cutoff"]):
                capture = collect_honeypot_evidence([target], directory, {"transport": transport})
            self.assertEqual(import_labels("honeypot_is", capture["output"], "honeypot")[0]["valid_from"], target["cutoff"])
            self.assertTrue(capture["requires_admission_review"])
            captured_target = read_records(capture["targets_output"])[0]
            self.assertEqual(captured_target["cutoff"], target["cutoff"])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(CollectionError, "network_disabled"):
                verify_token_targets([target], directory)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertFalse(verify_token_targets([target], directory, dry_run=True)["network_performed"])

    def test_wrong_factory_and_corrupted_capture_cache_fail(self):
        target = token_target()
        with tempfile.TemporaryDirectory() as directory:
            client = SnapshotClient(directory, {"fixtures": {"honeypot_is": self.snapshot()["response"]}})
            query = self.snapshot()["request"]
            bundle = client.request("honeypot_is", query)
            raw = Path(bundle["evidence_ref"])
            cached = json.loads(raw.read_text())
            cached["response"]["simulationSuccess"] = False
            raw.write_text(json.dumps(cached))
            with self.assertRaisesRegex(CollectionError, "invalid_snapshot_cache"):
                client.request("honeypot_is", query)
        target["pool_metadata"][0]["factory"] = addr(9999)
        with self.assertRaisesRegex(ValueError, "unverified"):
            token_scope(target)


class TokenTrainingContractTests(unittest.TestCase):
    def cohort(self, task):
        targets = [token_target(task, index) for index in range(40)]
        events = [event for target in targets for event in token_events(target)]
        labels = [token_label(target, index < 20) for index, target in enumerate(targets)]
        supervision = reconcile_labels(labels, targets)
        splits, _ = split_records(supervision)
        graphs = [build_graph_sample(target, events) for target in targets]
        return targets, events, labels, supervision, splits, graphs

    def test_preparation_train_dry_run_and_frozen_bundle_both_tasks(self):
        from packages.bundle import export_model_bundle, load_model_bundle, predict_bundle
        from packages.models import create_model
        for task in ("honeypot", "rug_pull"):
            targets, events, labels, supervision, splits, graphs = self.cohort(task)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = train(graphs, supervision, splits, {"task_id": task}, root / "no-training", dry_run=True)
                self.assertEqual(plan["status"], "validated")
                self.assertFalse((root / "no-training").exists())
                for name, records in (("events", events), ("targets", targets), ("labels", labels)):
                    write_records(root / f"{name}.jsonl", records)
                prepared = prepare_dataset(root / "events.jsonl", root / "targets.jsonl", root / "labels.jsonl",
                                           {"task_id": task}, root / "prepared")
                self.assertFalse(prepared["fitting_performed"])
                self.assertEqual(prepared["quality_counts"], {"ok": 40})
                with self.assertRaises(FileExistsError):
                    prepare_dataset(root / "events.jsonl", root / "targets.jsonl", root / "labels.jsonl",
                                    {"task_id": task}, root / "prepared")
                scaler = fit_scaler(graphs[:20])
                config = {"architecture_id": "directed_edge_sage", "hidden_dim": 4, "layers": 2, "dropout": 0.0}
                model = create_model(config, len(graphs[0]["feature_names"]), len(graphs[0]["edge_feature_names"]), 2 * len(graphs[0]["relation_names"]))
                export_model_bundle(root / "bundle", model, config, scaler, task, .5, {"synthetic_untrained_smoke_only": True})
                bundle = load_model_bundle(root / "bundle", expected_task=task)
                self.assertTrue(all(row["score"] is not None for row in predict_bundle(bundle, graphs[:2])))
                baseline_config = dict(config, architecture_id="mean_sage")
                baseline = create_model(baseline_config, len(graphs[0]["feature_names"]), len(graphs[0]["edge_feature_names"]), 2 * len(graphs[0]["relation_names"]))
                export_model_bundle(root / "baseline", baseline, baseline_config, scaler, task, .5, {"synthetic_untrained_smoke_only": True})
                self.assertIsNotNone(predict_bundle(root / "baseline", graphs[:1])[0]["score"])
                evaluation = evaluate_bundle(root / "bundle", graphs, supervision, splits)
                self.assertFalse(evaluation["fitting_performed"])
                self.assertFalse(evaluation["threshold_selection_performed"])
                self.assertEqual(evaluation["metrics"]["rows"], 4)
                mismatched = copy.deepcopy(supervision)
                mismatched[0]["pool_addresses"] = [addr(99999)]
                with self.assertRaisesRegex(ValueError, "pool scope"):
                    train(graphs, mismatched, splits, {"task_id": task}, root / "never", dry_run=True)
                # Separate task models cannot mix token and address schemas.
                with self.assertRaises(ValueError):
                    batch_graph_samples(graphs[:1], {**scaler, "feature_names": graph_schema("ponzi")[1]})

    def test_repeated_pools_are_grouped_and_leakage_rejected(self):
        _, _, _, rows, _, _ = self.cohort("honeypot")
        rows[1]["pool_addresses"] = rows[0]["pool_addresses"]
        splits, _ = split_records(rows)
        self.assertEqual(splits[0]["partition"], splits[1]["partition"])
        splits[1]["partition"] = next(part for part in ("train", "validation", "test") if part != splits[0]["partition"])
        with self.assertRaisesRegex(ValueError, "pool leakage"):
            assert_partition_isolation(splits)

    def test_cli_token_preparation_and_capture_plans(self):
        targets, events, labels, _, _, _ = self.cohort("honeypot")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, records in (("targets", targets), ("events", events), ("evidence", labels)):
                write_records(root / f"{name}.jsonl", records)
            for command in ("verify-token-targets", "capture-honeypot"):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main([command, "--task", "honeypot", "--targets", str(root / "targets.jsonl"), "--dry-run"])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output.getvalue())["status"], "planned")
            output, error = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                code = main(["prepare", "--task", "honeypot", "--targets", str(root / "targets.jsonl"),
                             "--events", str(root / "events.jsonl"), "--input", str(root / "evidence.jsonl"), "--dry-run"])
            self.assertEqual(code, 0, error.getvalue())
            self.assertEqual(json.loads(output.getvalue())["status"], "validated")
            self.assertEqual(len(list(root.iterdir())), 3)
