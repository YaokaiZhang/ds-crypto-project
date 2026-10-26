"""Failed roots can be explicitly dropped without hiding incomplete downloads."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from checks import test_recent_pipeline as fixtures
from packages.collection import CollectionError
from packages.collection_recent import RecentHistoryCollector
from packages.io import load_json, save_json, sha256_file, read_records
from research.scam.recent import _sample_key
from research.scam.pipeline import main as runner


class FailureExclusionTests(unittest.TestCase):
    setUp = fixtures.RecentPipelineTests.setUp
    recent_settings = fixtures.RecentPipelineTests.recent_settings
    recent_config = fixtures.RecentPipelineTests.recent_config
    prepare = fixtures.RecentPipelineTests.prepare

    def failed_snapshot(self, reason='recent_normalization_failed:invalid_amount'):
        out = self.root / 'failed-roots'
        self.prepare(out, stage='cohort')
        targets = read_records(out / 'cohort/targets.jsonl')
        failed = {t['sample_id'] for t in targets[:2]}
        original = RecentHistoryCollector.collect

        def collect(collector, target, *args):
            if target['sample_id'] in failed:
                raise CollectionError(reason)
            return original(collector, target, *args)
        with patch.object(RecentHistoryCollector, 'collect', new=collect), redirect_stderr(io.StringIO()):
            self.assertEqual(self.prepare(out, stage='collect')['status'], 'collection_incomplete')
        for target in targets[:2]:
            save_json(out / 'collection/.work' / _sample_key(target) / 'raw_requests/failure.json', {'fixture': True})
        return out

    def test_drop_prepare_and_resume_preserve_graphs_evidence_and_failure_scratch(self):
        out = self.failed_snapshot()
        frozen = {p: sha256_file(p) for p in out.glob('cohort/*') if p.is_file()}
        graphs = {p: sha256_file(p) for p in out.glob('collection/samples/*/graph.json')}
        original = sha256_file(out / 'collection/manifest.json')
        with patch('packages.collection.EtherscanClient.request', side_effect=AssertionError('HTTP called')):
            result = self.prepare(out, stage='prepare', drop_failed=True)
            self.assertEqual(result['status'], 'prepared')
            self.assertFalse(result['fitting_performed'])
            report = load_json(out / 'collection/manifest.json')
            self.assertTrue(report['complete'])
            self.assertFalse(report['download_complete'])
            self.assertEqual((report['sample_count'], report['failure_excluded_count'], report['remaining_count']), (38, 2, 0))
            self.assertEqual(sha256_file(out / 'collection/pre_exclusion_manifest.json'), original)
            before = sha256_file(out / 'prepared/dataset_manifest.json')
            self.assertEqual(self.prepare(out, stage='prepare')['status'], 'prepared')
            self.assertEqual(self.prepare(out, stage='collect')['status'], 'collected')
            self.assertEqual(sha256_file(out / 'prepared/dataset_manifest.json'), before)
            self.assertEqual(load_json(out / 'collection/manifest.json'), report)
        self.assertEqual(frozen, {p: sha256_file(p) for p in frozen})
        self.assertEqual(graphs, {p: sha256_file(p) for p in graphs})
        self.assertEqual(len(list(out.glob('collection/failures/*.json'))), 2)
        self.assertEqual(len(list(out.glob('collection/.work/*/raw_requests/failure.json'))), 2)
        dropped = {r['sample_id'] for r in load_json(out / 'collection/failure_exclusions.json')['excluded']}
        self.assertFalse(dropped & {r['sample_id'] for r in read_records(out / 'prepared/graphs.jsonl')})
        self.assertEqual(result['dataset']['split']['eligible_samples'], 38)
        self.assertEqual(set(result['dataset']['split']['ratios']), {'train', 'validation'})

    def test_interrupted_ledger_publication_resumes_without_drop_flag(self):
        out = self.failed_snapshot()
        def interrupted(path, value):
            if Path(path) == out / 'collection/manifest.json':
                raise KeyboardInterrupt
            save_json(path, value)
        with patch('research.scam.recent.save_json', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.prepare(out, stage='prepare', drop_failed=True)
        self.assertTrue((out / 'collection/failure_exclusions.json').exists())
        self.assertFalse(load_json(out / 'collection/manifest.json')['complete'])
        self.assertEqual(self.prepare(out, stage='prepare')['status'], 'prepared')

    def test_dry_run_does_not_publish_exclusions_or_change_collection(self):
        out = self.failed_snapshot()
        before = sha256_file(out / 'collection/manifest.json')
        plan = self.prepare(out, stage='prepare', drop_failed=True, dry_run=True)
        self.assertEqual(len(plan['planned_failure_exclusions']), 2)
        self.assertFalse((out / 'collection/failure_exclusions.json').exists())
        self.assertFalse((out / 'prepared').exists())
        self.assertEqual(sha256_file(out / 'collection/manifest.json'), before)

    def test_unattempted_targets_cannot_be_dropped(self):
        out = self.failed_snapshot()
        manifest = load_json(out / 'collection/manifest.json')
        manifest['coverage'] = []
        save_json(out / 'collection/manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, 'unattempted_or_unrecorded'):
            self.prepare(out, stage='prepare', drop_failed=True)
        self.assertFalse((out / 'collection/failure_exclusions.json').exists())

    def test_authentication_and_integrity_failures_cannot_be_dropped(self):
        out = self.failed_snapshot()
        manifest = load_json(out / 'collection/manifest.json')
        for reason in ('Invalid API Key', 'cached_response_checksum_mismatch'):
            for row in manifest['coverage']:
                row['failure'] = reason
                save_json(out / 'collection/failures' / f'{_sample_key(row)}.json', row)
            save_json(out / 'collection/manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'provider_or_integrity'):
                self.prepare(out, stage='prepare', drop_failed=True)
        self.assertFalse((out / 'collection/failure_exclusions.json').exists())

    def test_unified_runner_drops_after_retry_budget_and_prepares(self):
        out = self.root / 'unattended-drop'
        self.prepare(out, stage='cohort')
        target = read_records(out / 'cohort/targets.jsonl')[0]
        settings = self.root / 'drop-settings.json'
        save_json(settings, self.recent_settings())
        original = RecentHistoryCollector.collect
        attempts = []

        def collect(collector, current, *args):
            if current['sample_id'] == target['sample_id']:
                attempts.append(current['sample_id'])
                raise CollectionError('temporarily unavailable')
            return original(collector, current, *args)
        with patch.object(RecentHistoryCollector, 'collect', new=collect), patch(
                'research.scam.pipeline.model_path', return_value=self.root / 'all-model'), redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            code = runner(['--snapshot', 'unattended-drop', '--output', str(out), '--settings', str(settings),
                           '--stage', 'all', '--run', 'one-epoch', '--epochs', '1', '--drop-failed', '--max-attempts', '2', '--retry-delay', '0', '--progress', 'off'])
        self.assertEqual(code, 0)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(load_json(out / 'collection/manifest.json')['failure_excluded_count'], 1)
        self.assertTrue((out / 'prepared/dataset_manifest.json').exists())

    def test_corrupt_published_graph_is_not_dropped(self):
        out = self.failed_snapshot()
        graph = next(out.glob('collection/samples/*/graph.json'))
        graph.write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.prepare(out, stage='prepare', drop_failed=True)
        self.assertFalse((out / 'prepared').exists())
