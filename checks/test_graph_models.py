"""Graph admission checks plus dependency-gated tensor/model smoke checks."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from packages.bundle import (BUNDLE_VERSION, ModelBundle, export_model_bundle,
    load_model_bundle, predict_bundle)
from packages.graph import (EDGE_FEATURE_NAMES, FEATURE_NAMES, GRAPH_VIEW_VERSION,
    RELATION_NAMES, SCHEMA_VERSION, batch_graph_samples, build_graph_sample,
    fit_scaler, get_graph_builder, graph_is_usable, validate_graph_sample)


def address(number: int) -> str:
    return "0x" + f"{number:040x}"


def target(**changes):
    result = {"sample_id": "sample-1", "task_id": "phishing", "target": address(1),
        "cutoff": 3_000_000, "chain_id": 1, "coverage": {"complete": True}}
    result.update(changes)
    return result


def event(number=1, **changes):
    result = {"event_id": f"event-{number}", "chain_id": 1, "timestamp": 2_990_000,
        "block_number": 100, "block_hash": "0xblock", "tx_hash": "0xtx",
        "src": address(2), "dst": address(1), "relation": "external_eth",
        "asset": "ETH", "raw_amount": "1000000000000000000", "decimals": 18,
        "success": True, "lineage": {"source": "fixture"}}
    result.update(changes)
    return result


def sample(**changes):
    return build_graph_sample(target(**changes), [event()])


def reorder_nodes(graph):
    graph = copy.deepcopy(graph)
    order = list(reversed(range(len(graph["node_features"]))))
    inverse = {old: new for new, old in enumerate(order)}
    graph["node_features"] = [graph["node_features"][old] for old in order]
    graph["node_refs"] = [graph["node_refs"][old] for old in order]
    graph["root_index"] = inverse[graph["root_index"]]
    graph["edge_index"] = [[inverse[node] for node in side] for side in graph["edge_index"]]
    return graph


def manifest(task="phishing"):
    return {"bundle_version": BUNDLE_VERSION, "task_id": task, "chain_id": 1,
        "schema_version": SCHEMA_VERSION, "graph_view_version": GRAPH_VIEW_VERSION,
        "feature_names": FEATURE_NAMES, "edge_feature_names": EDGE_FEATURE_NAMES,
        "relation_names": RELATION_NAMES, "add_reverse": True,
        "input_dim": len(FEATURE_NAMES), "edge_dim": len(EDGE_FEATURE_NAMES),
        "num_relations": 2 * len(RELATION_NAMES), "threshold": .5,
        "graph_recipe": {"builder": "address_flow", "sampling": {
            "seed": 20261008, "hops": 2, "fanouts": [32, 16], "max_nodes": 512,
            "max_edges": 4096, "window_days": 30}},
        "score_meaning": "uncalibrated_pattern_screening_score", "calibration_status": "uncalibrated"}


class GraphDataTests(unittest.TestCase):
    def test_token_transfer_and_old_pool_need_no_pair_created_in_window(self):
        pool = address(10)
        rows = [event(1, src=address(2), dst=address(3), relation="erc20_transfer", asset=address(1)),
                event(2, src=pool, dst=address(4), relation="external_eth"),
                event(3, src=pool, dst=address(5), pool=pool, relation="swap", raw_amount=None)]
        graph = build_graph_sample(target(task_id="rug_pull", pools=[pool]), rows)
        self.assertFalse(graph_is_usable(graph))  # Addresses alone are unverified context.
        self.assertEqual(graph["quality"]["observed_events"], 3)
        self.assertTrue({address(2), address(3), pool, address(4), address(5)}.issubset(graph["node_refs"]))
        self.assertIn("participates", {RELATION_NAMES[value] for value in graph["relation_ids"]})
        future = build_graph_sample(target(task_id="honeypot"), [dict(rows[0], timestamp=target()["cutoff"] + 1)])
        self.assertEqual(len(future["node_refs"]), 1)

    def test_collected_coverage_must_match_neighborhood_recipe(self):
        coverage = {"complete": True, "neighborhood_history_complete": True,
                    "hops": 2, "fanouts": [32, 16], "seed": 20261008, "max_nodes": 512}
        self.assertTrue(graph_is_usable(sample(coverage=coverage)))
        for key, value in (("hops", 1), ("fanouts", [1, 1]), ("seed", 7), ("max_nodes", 2)):
            graph = sample(coverage={**coverage, key: value})
            self.assertFalse(graph_is_usable(graph), key)
            self.assertEqual(graph["quality"]["status"], "data_incomplete")

    def test_deterministic_sampling_and_labels_never_features(self):
        rows = [event(number, src=address(number + 2)) for number in range(20)]
        first = build_graph_sample(target(source_label=1), rows, fanouts=(4, 2), max_nodes=8)
        second = build_graph_sample(target(source_label=0), list(reversed(rows)), fanouts=(4, 2), max_nodes=8)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first["node_refs"]), 8)
        self.assertTrue(first["quality"]["sampling_truncated"])
        self.assertNotIn("label", first)

    def test_cutoff_and_observation_boundaries(self):
        cutoff = target()["cutoff"]
        start = cutoff - 30 * 86400
        graph = build_graph_sample(target(), [event(1, timestamp=cutoff),
            event(2, timestamp=cutoff + 1, src=address(100)),
            event(3, timestamp=start, src=address(101))])
        self.assertEqual(graph["quality"]["observed_events"], 1)
        self.assertNotIn(address(100), graph["node_refs"])
        self.assertNotIn(address(101), graph["node_refs"])
        self.assertEqual(graph["quality"]["excluded_future_events"], 1)

    def test_missing_amount_and_real_zero_have_distinct_masks(self):
        missing = build_graph_sample(target(), [event(raw_amount=None)])
        zero = build_graph_sample(target(), [event(raw_amount="0")])
        position = EDGE_FEATURE_NAMES.index("amount_missing_fraction")
        self.assertEqual(missing["edge_attributes"][0][position], 1)
        self.assertEqual(zero["edge_attributes"][0][position], 0)
        self.assertEqual(zero["edge_attributes"][0][1], 0)

    def test_quality_failures_and_duplicate_conflicts(self):
        self.assertEqual(sample(coverage=None)["quality"]["status"], "data_incomplete")
        empty = build_graph_sample(target(), [])
        self.assertEqual(empty["quality"]["status"], "insufficient_history")
        duplicate = build_graph_sample(target(), [event(), event()])
        self.assertEqual(duplicate["quality"]["observed_events"], 1)
        self.assertEqual(duplicate["quality"]["duplicate_events"], 1)
        conflict = build_graph_sample(target(), [event(), event(raw_amount="1")])
        self.assertEqual(conflict["quality"]["status"], "data_incomplete")
        self.assertFalse(graph_is_usable(conflict))

    def test_asset_specific_aggregation(self):
        graph = build_graph_sample(target(), [event(1), event(2),
            event(3, relation="erc20_transfer", asset=address(9), decimals=6)])
        self.assertEqual(len(graph["edge_attributes"]), 2)
        groups = graph["lineage"]["edge_groups"]
        self.assertEqual(sorted(len(group["event_ids"]) for group in groups), [1, 2])

    def test_token_pool_context_and_multi_roles_are_one_node(self):
        pool = address(10)
        graph = build_graph_sample(target(task_id="rug_pull"), [
            event(1, relation="swap", src=address(2), dst=pool, pool=pool,
                token0=address(1), token1=address(9), asset=address(1), raw_amount=None),
            event(2, relation="lp_transfer", asset=pool, src=address(3), dst=address(2)),
        ])
        position = graph["node_refs"].index(pool)
        self.assertEqual(graph["node_features"][position][FEATURE_NAMES.index("role_pool")], 1)
        self.assertEqual(graph["node_features"][position][FEATURE_NAMES.index("role_lp")], 1)
        self.assertEqual(graph["node_refs"].count(pool), 1)
        self.assertIn(RELATION_NAMES.index("contains"), graph["relation_ids"])
        self.assertEqual(graph["lineage"]["graph_builder"], "token_v2")

    def test_strategy_rejects_wrong_task(self):
        with self.assertRaises(ValueError):
            get_graph_builder("address_flow").build(target(task_id="honeypot"), [event()])

    def test_nonzero_root_and_schema_rejection(self):
        graph = reorder_nodes(sample())
        self.assertNotEqual(graph["root_index"], 0)
        validate_graph_sample(graph)
        graph["feature_names"] = list(reversed(graph["feature_names"]))
        with self.assertRaises(ValueError):
            validate_graph_sample(graph)

    def test_scaler_fit_records_only_supplied_training_samples(self):
        training = sample()
        heldout = sample(sample_id="heldout")
        scaler = fit_scaler([training])
        self.assertEqual(scaler["fitted_sample_ids"], [training["sample_id"]])
        self.assertNotIn(heldout["sample_id"], scaler["fitted_sample_ids"])
        self.assertEqual(scaler["node_std"][FEATURE_NAMES.index("is_root")], 1)
        with self.assertRaises(ValueError):
            fit_scaler([sample(coverage=None)])

    def test_quality_abstention_needs_no_model_forward_or_labels(self):
        incomplete = sample(coverage=None)
        result = predict_bundle(ModelBundle(None, {}, manifest()), [incomplete])[0]
        self.assertEqual(result["status"], "data_incomplete")
        self.assertIsNone(result["score"])
        self.assertIsNone(result["predicted_label"])

    def test_missing_model_and_incomplete_neighborhood_abstain(self):
        graph = sample(coverage={"complete": True, "neighborhood_history_complete": False})
        self.assertEqual(graph["quality"]["status"], "data_incomplete")
        with tempfile.TemporaryDirectory() as temporary:
            result = predict_bundle(Path(temporary) / "not-present", [graph])[0]
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIsNone(result["score"])


@unittest.skipUnless(importlib.util.find_spec("torch") is not None, "PyTorch unavailable; numeric tests require the Scam environment")
class GraphModelTests(unittest.TestCase):
    def setUp(self):
        import torch
        from packages.models import create_model
        torch.manual_seed(42)
        self.torch = torch
        self.create_model = create_model
        self.graph = sample()
        self.scaler = fit_scaler([self.graph])

    def model(self, architecture="directed_edge_sage", **options):
        config = {"architecture_id": architecture, "hidden_dim": 8, "layers": 2, "dropout": 0.0, **options}
        return self.create_model(config, len(FEATURE_NAMES), len(EDGE_FEATURE_NAMES), 2 * len(RELATION_NAMES))

    def test_multibatch_offsets_explicit_nonzero_root_and_reverse_relations(self):
        second = reorder_nodes(sample(sample_id="second"))
        batch = batch_graph_samples([self.graph, second], self.scaler)
        self.assertEqual(batch.root_indices.tolist(), [0, len(self.graph["node_refs"]) + second["root_index"]])
        self.assertEqual(batch.graph_ids.tolist(), [0, 0, 1, 1])
        self.assertEqual(batch.edge_index.shape[1], 4)
        self.assertEqual(batch.relation_ids[1].item(), batch.relation_ids[0].item() + len(RELATION_NAMES))
        self.assertTrue(self.torch.equal(batch.graph_ids[batch.edge_index[0]], batch.graph_ids[batch.edge_index[1]]))

    def test_permutation_invariance_and_batch_consistency(self):
        for architecture in ("mean_sage", "directed_edge_sage"):
            model = self.model(architecture).eval()
            original = model(batch_graph_samples([self.graph], self.scaler))
            permutation = model(batch_graph_samples([reorder_nodes(self.graph)], self.scaler))
            batched = model(batch_graph_samples([self.graph, reorder_nodes(self.graph)], self.scaler))
            self.assertTrue(self.torch.allclose(original, permutation, atol=1e-6))
            self.assertTrue(self.torch.allclose(batched, original.repeat(2), atol=1e-6))

    def test_empty_edges_and_backward_are_finite(self):
        empty = build_graph_sample(target(sample_id="empty"), [])
        batch = batch_graph_samples([empty, self.graph], self.scaler)
        for architecture in ("mean_sage", "directed_edge_sage"):
            model = self.model(architecture)
            logits = model(batch)
            self.assertEqual(logits.shape, (2,))
            self.assertTrue(self.torch.isfinite(logits).all())
            logits.square().mean().backward()
            self.assertTrue(all(self.torch.isfinite(parameter.grad).all() for parameter in model.parameters() if parameter.grad is not None))

    def test_edge_attributes_affect_upgrade_but_not_mean_baseline(self):
        batch = batch_graph_samples([self.graph], self.scaler)
        changed = replace(batch, edge_attr=batch.edge_attr + .75)
        upgraded = self.model().eval()
        baseline = self.model("mean_sage").eval()
        self.assertFalse(self.torch.allclose(upgraded(batch), upgraded(changed), atol=1e-7))
        self.assertTrue(self.torch.equal(baseline(batch), baseline(changed)))
        ablated = self.model(ignore_edge_attr=True).eval()
        self.assertTrue(self.torch.equal(ablated(batch), ablated(changed)))
        self.assertNotIn("edge_attributes", ablated.consumed_inputs)

    def test_direction_and_relation_effects_and_ablations(self):
        batch = batch_graph_samples([self.graph], self.scaler)
        reversed_batch = replace(batch, edge_index=batch.edge_index.flip(0))
        directed = self.model().eval()
        self.assertFalse(self.torch.allclose(directed(batch), directed(reversed_batch), atol=1e-7))
        no_direction = self.model(ignore_direction=True).eval()
        self.assertTrue(self.torch.allclose(no_direction(batch), no_direction(reversed_batch), atol=1e-7))
        other_relation = replace(batch, relation_ids=batch.relation_ids + 1)
        self.assertFalse(self.torch.allclose(directed(batch), directed(other_relation), atol=1e-7))
        no_relations = self.model(ignore_relations=True).eval()
        self.assertTrue(self.torch.equal(no_relations(batch), no_relations(other_relation)))
        self.assertNotIn("relation_ids", no_relations.consumed_inputs)

    def test_bundle_roundtrip_task_schema_checksum_rejection(self):
        model = self.model().eval()
        config = {"architecture_id": "directed_edge_sage", "hidden_dim": 8, "layers": 2, "dropout": 0.0}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            export_model_bundle(path, model, config, self.scaler, "phishing", .5, {"test_only": True})
            loaded = load_model_bundle(path, expected_task="phishing")
            prediction = predict_bundle(loaded, [self.graph])[0]
            expected = self.torch.sigmoid(model(batch_graph_samples([self.graph], self.scaler))).item()
            self.assertAlmostEqual(prediction["score"], expected, places=6)
            with self.assertRaises(ValueError):
                load_model_bundle(path, expected_task="ponzi")
            with self.assertRaises(ValueError):
                predict_bundle(loaded, [sample(task_id="ponzi")])
            incompatible = build_graph_sample(target(), [event()], fanouts=(8, 4))
            with self.assertRaises(ValueError):
                predict_bundle(loaded, [incompatible])
            original_manifest = json.loads((path / "manifest.json").read_text())
            other = export_model_bundle(path / "other-threshold", model, config, self.scaler,
                                        "phishing", .75, {"test_only": True})
            self.assertEqual(other["weights_sha256"], original_manifest["weights_sha256"])
            self.assertNotEqual(other["model_version"], original_manifest["model_version"])
            (path / "manifest.json").write_text(json.dumps(dict(original_manifest, threshold=.75)))
            with self.assertRaisesRegex(ValueError, "identity"):
                load_model_bundle(path)
            altered = dict(original_manifest, feature_names=list(reversed(FEATURE_NAMES)))
            (path / "manifest.json").write_text(json.dumps(altered))
            with self.assertRaises(ValueError):
                load_model_bundle(path)
            (path / "manifest.json").write_text(json.dumps(original_manifest))
            with (path / "model.pt").open("ab") as handle:
                handle.write(b"checksum corruption")
            with self.assertRaises(ValueError):
                load_model_bundle(path)


    def test_proxy_score_semantics_and_token_schema_export_rejection(self):
        model = self.model()
        config = {"architecture_id": "directed_edge_sage", "hidden_dim": 8, "layers": 2, "dropout": 0.0}
        with tempfile.TemporaryDirectory() as temporary:
            exported = export_model_bundle(Path(temporary) / "proxy", model, config, self.scaler, "phishing", .5,
                {"config": {"experiment_mode": "known_positive_vs_unlabeled"}})
            self.assertEqual(exported["score_meaning"], "known_positive_vs_sampled_unlabeled")
            for task in ("honeypot", "rug_pull"):
                with self.assertRaises(ValueError):
                    export_model_bundle(Path(temporary) / task, model, config, self.scaler, task, .5, {})


if __name__ == "__main__":
    unittest.main()
