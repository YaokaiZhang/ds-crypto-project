"""Storage migrations preserve graph bytes, replay inputs and recovery contracts."""
import gzip
from pathlib import Path
import unittest
from unittest.mock import patch

from checks import test_recent_pipeline as recent_fixtures
from packages.graph import build_graph_sample
from packages.io import load_json, save_json, sha256_file
from packages.observations import read_sample_events
from research.scam import compaction


class StorageCompactionTests(unittest.TestCase):
    setUp = recent_fixtures.RecentPipelineTests.setUp
    recent_settings = recent_fixtures.RecentPipelineTests.recent_settings
    recent_config = recent_fixtures.RecentPipelineTests.recent_config
    prepare = recent_fixtures.RecentPipelineTests.prepare

    def legacy_snapshot(self):
        out = (self.root / 'legacy-storage').resolve()
        self.prepare(out, stage='cohort')
        self.prepare(out, stage='collect')
        collection = load_json(out / 'collection/manifest.json')
        for entry in collection['samples']:
            directory = out / 'collection/samples' / entry['key']
            sample = load_json(directory / 'manifest.json')
            shared = Path(sample['shared_observation']['path'])
            observation = load_json(shared / 'manifest.json')
            original = gzip.decompress((shared / 'events.jsonl.gz').read_bytes())
            (shared / 'events.jsonl').write_bytes(original)
            (directory / 'events.jsonl').write_bytes(original)
            observation.pop('events_uncompressed_sha256')
            observation.pop('storage_version')
            observation['artifacts'].pop('events.jsonl.gz')
            observation['artifacts']['events.jsonl'] = sha256_file(shared / 'events.jsonl')
            observation['artifacts'] = {name: observation['artifacts'][name] for name in
                                       ('events.jsonl', 'coverage.json', 'normalization_audit.json')}
            save_json(shared / 'manifest.json', observation)
            (shared / 'events.jsonl.gz').unlink()
            sample.pop('event_storage')
            sample['version'] = 'recent-sample-2'
            sample['shared_observation']['manifest_sha256'] = sha256_file(shared / 'manifest.json')
            sample['artifacts']['events.jsonl'] = sha256_file(directory / 'events.jsonl')
            save_json(directory / 'manifest.json', sample)
            entry['manifest_sha256'] = sha256_file(directory / 'manifest.json')
        save_json(out / 'collection/manifest.json', collection)
        # Keep an unfinished root cache that must never be garbage-collected.
        scratch = out / 'collection/.work/unfinished/raw_requests/failed.json'
        save_json(scratch, {'error': 'fixture'})
        return out

    def test_lossless_migration_and_offline_resume_then_preparation(self):
        out = self.legacy_snapshot()
        original = load_json(out / 'collection/manifest.json')
        first = out / 'collection/samples' / original['samples'][0]['key']
        event_bytes = (first / 'events.jsonl').read_bytes()
        graph_hashes = {p: sha256_file(p) for p in out.glob('collection/samples/*/graph.json')}
        frozen = {p: sha256_file(p) for p in out.glob('cohort/*') if p.is_file()}
        self.assertEqual(compaction.compact_snapshot(out, dry_run=True)['status'], 'planned')
        self.assertFalse((out / compaction.JOURNAL).exists())
        with patch('packages.collection.EtherscanClient.request', side_effect=AssertionError('HTTP called')):
            report = compaction.compact_snapshot(out)
            self.assertGreater(report['reclaimed_bytes'], 0)
            self.assertEqual(compaction.compact_snapshot(out)['status'], 'already_compacted')
            self.assertEqual(self.prepare(out, stage='all')['status'], 'prepared')
        self.assertEqual(graph_hashes, {p: sha256_file(p) for p in graph_hashes})
        self.assertEqual(frozen, {p: sha256_file(p) for p in frozen})
        self.assertTrue((out / 'collection/.work/unfinished/raw_requests/failed.json').exists())
        self.assertFalse(list(out.glob('collection/samples/*/events.jsonl')))
        shared = Path(load_json(first / 'manifest.json')['shared_observation']['path'])
        self.assertFalse((shared / 'events.jsonl').exists())
        self.assertEqual(gzip.decompress((shared / 'events.jsonl.gz').read_bytes()), event_bytes)
        events = read_sample_events(first)
        graph = build_graph_sample(load_json(first / 'target.json'), events,
                                   **load_json(out / 'cohort/training_config.json')['graph'])
        self.assertEqual(graph, load_json(first / 'graph.json'))

    def test_interrupted_reference_publication_and_index_publication_resume(self):
        for interrupt_at in ('sample', 'index', 'cleanup'):
            with self.subTest(interrupt_at=interrupt_at):
                # Each subtest gets its own fixture snapshot/shared store.
                out = self.legacy_snapshot()
                original_save = compaction._save
                original_unlink = Path.unlink
                interrupted = False

                def save(path, value):
                    nonlocal interrupted
                    is_sample = path.name == 'manifest.json' and path.parent.parent.name == 'samples'
                    is_index = path == out / 'collection/manifest.json'
                    if not interrupted and ((interrupt_at == 'sample' and is_sample)
                                            or (interrupt_at == 'index' and is_index)):
                        interrupted = True
                        raise KeyboardInterrupt
                    original_save(path, value)

                def unlink(path, *args, **kwargs):
                    nonlocal interrupted
                    result = original_unlink(path, *args, **kwargs)
                    if not interrupted and interrupt_at == 'cleanup' and path.name == 'events.jsonl':
                        interrupted = True
                        raise KeyboardInterrupt
                    return result

                with patch.object(compaction, '_save', side_effect=save), patch.object(Path, 'unlink', new=unlink):
                    with self.assertRaises(KeyboardInterrupt):
                        compaction.compact_snapshot(out)
                with self.assertRaisesRegex(ValueError, 'compaction_unfinished'):
                    self.prepare(out, stage='collect')
                self.assertEqual(compaction.compact_snapshot(out)['status'], 'compacted')
                with patch('packages.collection.EtherscanClient.request', side_effect=AssertionError('HTTP called')):
                    self.assertEqual(self.prepare(out, stage='collect')['status'], 'collected')
                # Remove this completed fixture only to start another subtest.
                import shutil
                shutil.rmtree(out)
                shutil.rmtree(self.root / 'shared/observations')

    def test_corrupted_duplicate_or_missing_shared_input_never_deleted(self):
        out = self.legacy_snapshot()
        first = next(out.glob('collection/samples/*'))
        events = first / 'events.jsonl'
        events.write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            compaction.compact_snapshot(out)
        self.assertEqual(events.read_text(), 'corrupt')
        self.assertFalse((out / compaction.JOURNAL / 'plan.json').exists())

    def test_missing_shared_dependency_blocks_new_sample_resume_without_http(self):
        out = self.root / 'missing-shared'
        self.prepare(out, stage='cohort')
        self.prepare(out, stage='collect')
        first = next(out.glob('collection/samples/*'))
        shared = Path(load_json(first / 'manifest.json')['shared_observation']['path'])
        (shared / 'events.jsonl.gz').unlink()
        with patch('packages.collection.EtherscanClient.request', side_effect=AssertionError('HTTP called')):
            with self.assertRaises(FileNotFoundError):
                self.prepare(out, stage='collect')

    def test_already_prepared_snapshot_refused_before_any_migration(self):
        out = self.legacy_snapshot()
        save_json(out / 'prepared/dataset_manifest.json', {'fixture': True})
        before = sha256_file(out / 'collection/manifest.json')
        with self.assertRaisesRegex(ValueError, 'preserve_published_training_provenance'):
            compaction.compact_snapshot(out)
        self.assertEqual(sha256_file(out / 'collection/manifest.json'), before)
        self.assertFalse((out / compaction.JOURNAL).exists())

    def test_incomplete_collection_failure_and_exclusion_metadata_preserved(self):
        out = self.legacy_snapshot()
        path = out / 'collection/manifest.json'
        original = load_json(path)
        original.update(complete=False, target_count=42, remaining_count=2, failed_count=2,
                        coverage=[{'target': 'fixture-a', 'failure': 'byte_budget'},
                                  {'target': 'fixture-b', 'failure': 'normalization'}])
        save_json(path, original)
        compaction.compact_snapshot(out)
        actual = load_json(path)
        self.assertEqual({k: v for k, v in actual.items() if k != 'samples'},
                         {k: v for k, v in original.items() if k != 'samples'})
        with self.assertRaisesRegex(ValueError, 'complete_collection_required'):
            self.prepare(out, stage='prepare')

    def test_two_legacy_snapshots_can_migrate_the_same_shared_objects_in_sequence(self):
        import shutil
        first = self.legacy_snapshot()
        second = first.with_name('second-legacy-storage')
        shutil.copytree(first, second)
        compaction.compact_snapshot(first)
        # The second snapshot still has old pins and intact local JSONL copies.
        compaction.compact_snapshot(second)
        for original in first.glob('collection/samples/*/manifest.json'):
            migrated = second / original.relative_to(first)
            self.assertEqual(load_json(original)['shared_observation'],
                             load_json(migrated)['shared_observation'])
        with patch('packages.collection.EtherscanClient.request', side_effect=AssertionError('HTTP called')):
            self.assertEqual(self.prepare(second, stage='prepare')['status'], 'prepared')
