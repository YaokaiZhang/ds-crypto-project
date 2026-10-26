"""90/10 allocation and validation-only reports across both training families."""
from collections import Counter
import copy
from pathlib import Path
import tempfile
import unittest

from checks.test_training import supervision_records, synthetic_graph
from packages.evaluation_protocol import PARTITIONS
from packages.io import load_json, read_records, write_records
from research.scam._commands import parser as scam_parser
from research.scam.splitting import split_records
from research.scam.training import metrics, train
from scripts.assign_model_split import assign_partitions, validate_assignments
from scripts import train_graphsage, train_tabular_baseline, calibrate_threshold


class ValidationProtocolTests(unittest.TestCase):
    def test_phishing_950_1108_class_proportions_and_no_test(self):
        rows = []
        for label, count in ((1, 950), (0, 1108)):
            for index in range(count):
                row = {"sample_id": f"{label}:{index}", "task_id": "phishing", "chain_id": 1,
                       "entity_id": f"0x{label * 10000 + index:040x}",
                       "label_status": "supported_positive" if label else "unlabeled",
                       "eligible": bool(label), "data_eligible": True,
                       "background_selected": not label, "cohort_id": "frozen-fixture"}
                rows.append(row)
        before = copy.deepcopy(rows)
        splits, manifest = split_records(rows, mode="known_positive_vs_unlabeled")
        self.assertEqual(rows, before)
        self.assertEqual(manifest['partition_class_counts'],
                         {'train': {'0': 997, '1': 855}, 'validation': {'0': 111, '1': 95}})
        self.assertEqual({r['partition'] for r in splits}, set(PARTITIONS))
        self.assertFalse(manifest['evaluation']['independent_test_set'])
        self.assertTrue(all(r['label_status'] == 'unlabeled' for r in splits if not r['observed_target']))

    def test_matrix_counts_and_accuracy_respond_to_class_mix(self):
        balanced = metrics([0, 0, 1, 1], [.1, .9, .2, .8])
        imbalanced = metrics([0, 0] + [1, 1] * 3, [.1, .9] + [.2, .8] * 3)
        self.assertEqual(balanced['confusion_matrix'], {'tn': 1, 'fp': 1, 'fn': 1, 'tp': 1})
        self.assertEqual(imbalanced['confusion_matrix'], {'tn': 1, 'fp': 1, 'fn': 3, 'tp': 3})
        self.assertEqual(balanced['confusion_matrix_normalized_by_true_label'], [[.5, .5], [.5, .5]])
        self.assertEqual(balanced['confusion_matrix_normalized_by_true_label'],
                         imbalanced['confusion_matrix_normalized_by_true_label'])
        all_background = metrics([0] * 111 + [1] * 95, [.1] * 206)
        self.assertAlmostEqual(all_background['accuracy'], 111 / 206)
        self.assertEqual(all_background['balanced_accuracy'], .5)

    def test_token_split_preserves_groups_and_rejects_legacy_ratios(self):
        rows = [{'token_address': f'0x{i:040x}', 'source_dataset': 'fixture',
                 'label': 'continued_activity' if i < 20 else 'low_volume_dead',
                 'launch_period': 'fixture', 'overlap_group': f'group:{i}'} for i in range(40)]
        rows[1]['overlap_group'] = rows[0]['overlap_group']
        assigned = assign_partitions(rows, {'train': .9, 'validation': .1}, 123)
        self.assertEqual(validate_assignments(assigned)['overlap_groups_crossing_partitions'], 0)
        counts = Counter(r['partition'] for r in assigned)
        self.assertEqual(sum(counts.values()), 40)
        self.assertEqual(set(counts), set(PARTITIONS))
        self.assertLessEqual(abs(counts['validation'] - 4), 2)  # Whole groups can shift integer targets.
        again = assign_partitions(list(reversed(rows)), {'train': .9, 'validation': .1}, 123)
        self.assertEqual(assigned, again)
        with self.assertRaisesRegex(ValueError, 'ratios'):
            assign_partitions(rows, {'train': .8, 'validation': .1, 'test': .1}, 123)

    def test_legacy_scam_partitions_not_silently_dropped(self):
        rows = supervision_records()
        splits, _ = split_records(rows)
        splits[0]['partition'] = 'test'
        with self.assertRaisesRegex(ValueError, 'legacy_test_partition'):
            train([synthetic_graph(row) for row in rows], rows, splits, {'task_id': 'ponzi'}, 'unused', dry_run=True)
        self.assertEqual(scam_parser().parse_args(['evaluate', '--task', 'ponzi']).partition, 'validation')

    def test_scam_one_epoch_baselines_and_bundle_report_validation(self):
        rows = supervision_records()
        splits, _ = split_records(rows)
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / 'run'
            report = train([synthetic_graph(row) for row in rows], rows, splits,
                           {'task_id': 'ponzi', 'epochs': 1, 'batch_size': 40, 'progress': 'off',
                            'model': {'hidden_dim': 4, 'dropout': 0}, 'fit_tabular_baselines': True}, out)
            self.assertEqual(set(report['metrics']), set(PARTITIONS))
            self.assertEqual(report['final_report']['accuracy'], report['metrics']['validation']['accuracy'])
            self.assertTrue(report['final_report']['validation_reused_for_model_selection'])
            self.assertNotIn('test_use', report)
            for baseline in report['tabular_baselines'].values():
                self.assertEqual(set(baseline['metrics']), set(PARTITIONS))
            self.assertEqual({r['partition'] for r in read_records(out / 'predictions.jsonl')}, set(PARTITIONS))
            exported = load_json(out / 'bundle/manifest.json')['training_manifest']
            self.assertFalse(exported['evaluation']['independent_test_set'])

    def test_original_token_trainers_and_threshold_calibration_without_test(self):
        rows = []
        for i in range(40):
            label = int(i < 20)
            row = {'token_address': f'0x{i:040x}', 'source_dataset': 'fixture', 'graph_role': 'development',
                   'partition': 'validation' if i % 10 == 0 else 'train',
                   'label': 'continued_activity' if label else 'low_volume_dead',
                   'node_features': [[float(label), 1.], [1., float(label)]],
                   'edge_index': [[0, 1], [1, 0]], 'feature_complete': True}
            row.update({name: float(label + (i % 3)) for name in train_tabular_baseline.FEATURE_NAMES})
            rows.append(row)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'targets.jsonl'
            write_records(path, rows)
            args = train_graphsage.parser().parse_args([
                '--graphs', str(path), '--output', str(root / 'sage'), '--epochs', '1',
                '--hidden-dim', '4', '--batch-size', '40', '--threads', '1', '--device', 'cpu', '--no-progress'])
            sage = train_graphsage.train(args)
            args = train_tabular_baseline.parser().parse_args([
                '--targets', str(path), '--output', str(root / 'tabular'), '--no-progress'])
            baseline = train_tabular_baseline.train(args)
            for result in (sage, baseline):
                self.assertEqual(set(result['metrics']), set(PARTITIONS))
                self.assertEqual(result['split_counts'], {'train': 36, 'validation': 4})
                self.assertEqual(result['final_report']['accuracy'], result['metrics']['validation']['accuracy'])
                self.assertFalse(result['evaluation']['independent_test_set'])
            calibration_args = calibrate_threshold.parser().parse_args([
                '--predictions', str(root / 'sage/predictions.jsonl'), '--output', str(root / 'calibration.json')])
            calibration = calibrate_threshold.calibrate(calibration_args)
            self.assertEqual(calibration['validation_rows'], 4)
            self.assertTrue(all('test' not in result for result in calibration['results']))
