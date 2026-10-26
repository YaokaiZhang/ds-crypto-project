"""Bounded retrospective graphs, transactional cleanup and concurrent quota checks."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
import copy
import io
import json
from pathlib import Path
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

from checks import test_phishing_preparation as fixtures
from packages.collection import EtherscanClient
from packages.collection import CollectionError
from packages.collection_recent import RecentHistoryCollector
from packages.graph import RECENT_SAMPLING, RECENT_VIEW_VERSION, build_graph_sample, fit_scaler, graph_is_usable
from packages.io import read_records, load_json
from packages.provider_access import SerialRequestBudget
from packages.observations import ObservationStore, read_sample_events
from packages.sources.address_pools import load_address_pool
from research.scam._commands import main
from research.scam.cohorts import build_reference_phishing_cohort
from research.scam.recent import prepare_recent_phishing


class RecentPipelineTests(unittest.TestCase):
    setUp = fixtures.PhishingPreparationTests.setUp

    def recent_settings(self):
        transactions = self.settings['collection']['fixtures']['txlist'][:-1]
        payloads = {'getblocknobytime': {'result': '100'}}
        for entity in [fixtures.address(i) for i in range(1, 41)] + [fixtures.address(999)]:
            for action in ('txlist', 'txlistinternal'):
                query = {'chainid': 1, 'module': 'account', 'action': action, 'address': entity,
                         'startblock': 0, 'endblock': 100, 'page': 1, 'offset': 100, 'sort': 'desc'}
                rows = [r for r in transactions if entity in (r['from'], r['to'])] if action == 'txlist' else []
                payloads[EtherscanClient.request_id(query)] = {'status': '1', 'result': rows}
        return {'label_files': self.settings['label_files'], 'collection': {'fixtures': payloads},
                'address_pool_root': str(self.root / 'shared/address_pools'),
                'observation_root': str(self.root / 'shared/observations')}

    def recent_config(self):
        return load_json(Path(__file__).resolve().parents[1] / 'research/scam/configs/phishing_recent.json')

    def prepare(self, out, **options):
        return prepare_recent_phishing(out, self.recent_config(), settings=self.recent_settings(),
                                      source_as_of=self.cutoff, progress='off', **options)

    def test_reference_only_cohort_caps_positive_count_without_rpc(self):
        fixtures.PhishingPreparationTests.sources(self)
        targets, evidence, report = build_reference_phishing_cohort(self.root / 'sources')
        self.assertEqual(report['per_class_selected'], 20)
        self.assertEqual(report['background_source_counts']['historical_rpc'], 0)
        self.assertEqual(len(targets), 40)
        self.assertTrue(all(r['source_file'] != 'historical_rpc' for r in evidence))
        self.assertEqual(report['excluded_background_positive_overlap'], [fixtures.address(1)])

    def test_end_to_end_sample_cleanup_preparation_and_cached_resume(self):
        out = self.root / 'recent'
        with patch('packages.collection.urlopen', side_effect=AssertionError('network')):
            result = self.prepare(out)
        self.assertEqual(result['status'], 'prepared')
        directories = list((out / 'collection/samples').iterdir())
        self.assertEqual(len(directories), 40)
        self.assertEqual(list((out / 'collection/.work').glob('*/raw_requests/*.json')), [])
        manifest = load_json(out / 'collection/manifest.json')
        self.assertEqual(manifest['statistics']['median_queries_per_sample'], 4)
        self.assertEqual(manifest['provider_policy']['rate_limit_rps'], 2.5)
        graphs = read_records(out / 'prepared/graphs.jsonl')
        self.assertTrue(all(g['graph_view_version'] == RECENT_VIEW_VERSION for g in graphs))
        self.assertTrue(all(graph_is_usable(g) for g in graphs))
        self.assertTrue(all(g['quality']['full_history_complete'] is False for g in graphs))
        self.assertTrue(all('input' not in r for r in read_sample_events(directories[0])))
        self.assertTrue(all(not (p / 'events.jsonl').exists() for p in directories))
        # Published graphs pin shared replay inputs and need no HTTP on resume.
        with patch('packages.collection.EtherscanClient.request', side_effect=AssertionError('HTTP called')):
            again = self.prepare(out)
        self.assertEqual(again['status'], 'prepared')
        self.assertEqual(load_json(out / 'collection/manifest.json'), manifest)

    def test_frozen_higher_rate_snapshot_resumes_under_lower_runtime_cap(self):
        out = self.root / 'frozen-higher-rate'
        config = self.recent_config()
        config['collection']['rate_limit_rps'] = 4.8
        def run():
            return prepare_recent_phishing(out, config, settings=self.recent_settings(),
                                           source_as_of=self.cutoff, progress='off')
        self.assertEqual(run()['status'], 'prepared')
        frozen = load_json(out / 'cohort/manifest.json')
        collected = load_json(out / 'collection/manifest.json')
        self.assertEqual(frozen['config']['collection']['rate_limit_rps'], 4.8)
        self.assertEqual(collected['provider_policy']['rate_limit_rps'], 2.5)
        with patch.object(RecentHistoryCollector, 'collect', side_effect=AssertionError('history refetched')):
            self.assertEqual(run()['status'], 'prepared')
        self.assertEqual(load_json(out / 'cohort/manifest.json'), frozen)
        self.assertEqual(load_json(out / 'collection/manifest.json'), collected)

    def test_two_snapshots_share_candidate_pool_and_neutral_observations(self):
        first, second = self.root / 'shared-first', self.root / 'shared-second'
        self.prepare(first)
        # A new task snapshot still looks up its cutoff, but every address history
        # must come from the shared normalized observation store.
        with patch.object(RecentHistoryCollector, 'collect', side_effect=AssertionError('history refetched')):
            self.assertEqual(self.prepare(second)['status'], 'prepared')
        reference = load_json(first / 'background_ref.json')
        self.assertEqual(reference, load_json(second / 'background_ref.json'))
        rows, pool = load_address_pool(reference['path'])
        self.assertEqual(pool['addresses'], 21)  # Includes task-excluded positive overlap.
        self.assertTrue(all(row['label_status'] == 'unlabeled' and 'task_id' not in row for row in rows))
        self.assertEqual(len(list((self.root / 'shared/address_pools').iterdir())), 1)
        samples = list((second / 'collection/samples').iterdir())
        self.assertTrue(all(load_json(p / 'manifest.json')['observation_cache_hit'] for p in samples))
        self.assertTrue(all(load_json(p / 'manifest.json')['http_attempts'] == 0 for p in samples))
        shared = Path(load_json(samples[0] / 'manifest.json')['shared_observation']['path'])
        self.assertTrue(all(not set(row) & {'task_id', 'sample_id', 'label', 'label_status'}
                            for row in read_records(shared / 'events.jsonl.gz')))

    def test_shared_observation_identity_ignores_task_but_isolates_cutoff_and_recipe(self):
        store = ObservationStore(self.root / 'observations', {'actions': ['txlist', 'txlistinternal']})
        target = {'target': fixtures.address(1), 'cutoff': self.cutoff, 'task_id': 'phishing', 'sample_id': 'a'}
        graph = self.recent_config()['graph']
        spec = store.specification(target, graph, 100)
        store.publish(spec, [], {'complete': True}, {'complete': True})
        other_task = dict(target, task_id='ponzi', sample_id='b', label_status='unlabeled')
        self.assertIsNotNone(store.read(store.specification(other_task, graph, 100)))
        self.assertIsNone(store.read(store.specification(dict(target, cutoff=self.cutoff-1), graph, 100)))
        changed = copy.deepcopy(graph); changed['rows_per_action'] = 99
        self.assertIsNone(store.read(store.specification(target, changed, 100)))
        self.assertIsNone(store.read(store.specification(target, graph, 99)))
        with self.assertRaisesRegex(ValueError, 'task_labels'):
            store.publish(spec, [{'label_status': 'unlabeled'}], {'complete': True}, {'complete': True})
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            store.publish(spec, [], {'complete': False}, {'complete': True})
        (store.path(spec) / 'events.jsonl.gz').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            store.read(spec)

    def test_shared_fixture_origin_tracks_content_changes(self):
        directory = self.root / 'fixture-origin'
        directory.mkdir()
        fixture = directory / 'txlist.json'
        fixture.write_text('{"result": []}')
        settings = {'fixture_dir': str(directory), 'actions': ['txlist', 'txlistinternal']}
        first = ObservationStore(self.root / 'observations', settings)
        fixture.write_text('{"result": [{"changed": true}]}')
        second = ObservationStore(self.root / 'observations', settings)
        self.assertNotEqual(first.origin, second.origin)

    def test_failure_before_sample_publication_keeps_raw_then_resumes(self):
        out = self.root / 'interrupt'
        self.prepare(out, stage='cohort')
        with patch('research.scam.recent.build_graph_sample', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.prepare(out, stage='collect')
        self.assertEqual(list((out / 'collection/samples').iterdir()), [])
        self.assertTrue(list((out / 'collection/.work').glob('*/raw_requests/*.json')))
        self.assertEqual(self.prepare(out, stage='collect')['status'], 'collected')
        self.assertFalse(list((out / 'collection/.work').glob('*/raw_requests/*.json')))

    def test_sample_checksum_failure_never_refetches_or_deletes_evidence(self):
        out = self.root / 'tampered'
        self.prepare(out, stage='cohort')
        self.prepare(out, stage='collect')
        directory = next((out / 'collection/samples').iterdir())
        (directory / 'target.json').write_text('tampered')
        with patch('packages.collection.EtherscanClient.request', side_effect=AssertionError('HTTP called')):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                self.prepare(out, stage='collect')
        self.assertEqual((directory / 'target.json').read_text(), 'tampered')

    def test_interruption_after_publication_finishes_cleanup_without_refetch(self):
        from research.scam import recent
        out = self.root / 'cleanup-interruption'
        self.prepare(out, stage='cohort')
        first = read_records(out / 'cohort/targets.jsonl')[0]
        key = recent._sample_key(first)
        cleanup = recent._clean_work
        def interrupted(work):
            if work.name == key:
                raise OSError('simulated post-publication interruption')
            cleanup(work)
        with patch('research.scam.recent._clean_work', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'post-publication'):
                self.prepare(out, stage='collect')
        self.assertTrue((out / 'collection/samples' / key / 'manifest.json').exists())
        self.assertTrue((out / 'collection/.work' / key).exists())
        collect = RecentHistoryCollector.collect
        queried = []
        def observe(collector, target, *args):
            queried.append(target['sample_id'])
            return collect(collector, target, *args)
        with patch.object(RecentHistoryCollector, 'collect', new=observe):
            self.assertEqual(self.prepare(out, stage='collect')['status'], 'collected')
        self.assertNotIn(first['sample_id'], queried)
        self.assertFalse((out / 'collection/.work' / key).exists())

    def test_cli_new_snapshot_defaults_to_recent_and_dry_run_writes_nothing(self):
        out = self.root / 'new'
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = main(['prepare-phishing', '--task', 'phishing', '--snapshot', 'new',
                         '--output', str(out), '--stage', 'all', '--dry-run'])
        self.assertEqual(code, 0)
        self.assertFalse(out.exists())
        self.assertEqual(json.loads(output.getvalue())['queries_per_sample_upper_bound'], 66)

    def test_recent_selection_prefers_time_over_hash_and_preserves_cutoff(self):
        config = self.recent_config()['graph']
        config.update(fanouts=[1, 1], window_days=30)
        cutoff = 3000000
        target = {'sample_id': 'x', 'task_id': 'phishing', 'target': fixtures.address(1), 'cutoff': cutoff,
                  'coverage': {'complete': True, 'scope': RECENT_SAMPLING, 'sampled_history_complete': True,
                    'cutoff': cutoff, 'sources': [{'complete': True}],
                    **{k: config[k] for k in ('hops','fanouts','seed','max_nodes','rows_per_action','pages_per_action')}}}
        def event(index, stamp):
            return {'event_id': str(index), 'src': target['target'], 'dst': fixtures.address(index),
                    'timestamp': stamp, 'relation': 'external_eth', 'asset': 'ETH', 'raw_amount': '1',
                    'decimals': 18, 'success': True}
        graph = build_graph_sample(target, [event(2, cutoff-100), event(3, cutoff-1), event(4, cutoff+1)], **config)
        self.assertEqual(set(graph['node_refs']), {target['target'], fixtures.address(3)})
        self.assertEqual(graph['quality']['excluded_future_events'], 1)

    def test_bounded_pages_are_successful_sampling_and_never_fetch_older_pages(self):
        from checks.test_data import tx
        cutoff = self.cutoff
        root, neighbor = fixtures.address(1), fixtures.address(2)
        calls = []
        sample_states = []
        def transport(query):
            calls.append(query)
            rows = ([tx(hash=f'0x{i:064x}', **{'from': root, 'to': neighbor,
                      'timeStamp': str(cutoff-i), 'blockNumber': str(100-i)}) for i in (1, 2)]
                    if query['action'] == 'txlist' else [])
            return {'status': '1', 'result': rows}
        collector = RecentHistoryCollector({'actions': ['txlist', 'txlistinternal'], 'page_size': 2,
                                            'max_pages': 1, 'transport': transport}, sample_observer=sample_states.append)
        graph = self.recent_config()['graph']; graph['rows_per_action'] = 2
        target = {'sample_id': 'bounded', 'task_id': 'phishing', 'target': root, 'cutoff': cutoff}
        try:
            events, coverage, _ = collector.collect(target, graph, 100, self.root / 'bounded')
        finally:
            collector.close()
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(q['page'] == 1 and q['sort'] == 'desc' and q['endblock'] == 100 for q in calls))
        self.assertTrue(coverage['sampling_truncated'])
        self.assertEqual(sample_states[-1]['completed_queries'], 4)
        self.assertEqual(sample_states[-1]['total_queries'], 4)
        self.assertTrue(all(s['completed_queries'] <= s['total_queries'] for s in sample_states))
        self.assertFalse(coverage['full_history_complete'])
        sample = build_graph_sample(dict(target, coverage=coverage), events, **graph)
        self.assertTrue(graph_is_usable(sample))

    def test_future_provider_rows_are_rejected(self):
        from checks.test_data import tx
        root, other = fixtures.address(1), fixtures.address(2)
        def transport(query):
            return {'status': '1', 'result': [tx(**{'from': root, 'to': other,
                     'timeStamp': str(self.cutoff+1), 'blockNumber': '100'})]}
        collector = RecentHistoryCollector({'actions': ['txlist', 'txlistinternal'], 'transport': transport})
        try:
            with self.assertRaisesRegex(CollectionError, 'outside_cutoff'):
                collector.collect({'target': root, 'cutoff': self.cutoff}, self.recent_config()['graph'],
                                  100, self.root / 'future')
        finally:
            collector.close()

    def test_conflicting_history_flags_are_resolved_by_matching_receipt(self):
        from checks.test_data import tx
        root, other = fixtures.address(1), fixtures.address(2)
        row = tx(**{'from': root, 'to': other, 'timeStamp': str(self.cutoff-1),
                    'blockNumber': '99', 'isError': '0', 'txreceipt_status': '0', 'input': '0x1234'})
        for status in (0, 1):
            with self.subTest(receipt_status=status):
                calls = []
                def transport(query):
                    calls.append(query)
                    if query['action'] == 'eth_getTransactionReceipt':
                        return {'result': {'transactionHash': row['hash'], 'blockNumber': '0x63',
                            'blockHash': row['blockHash'], 'from': root, 'to': other, 'status': hex(status)}}
                    return {'status': '1', 'result': [row] if query['action'] == 'txlist' else []}
                work = self.root / f'conflict-{status}'
                collector = RecentHistoryCollector({'actions': ['txlist', 'txlistinternal'], 'transport': transport})
                try:
                    events, coverage, audit = collector.collect({'target': root, 'cutoff': self.cutoff},
                                                               self.recent_config()['graph'], 100, work)
                finally:
                    collector.close()
                self.assertTrue(audit['complete'])
                self.assertEqual(len(audit['execution_status_resolutions']), 1)
                self.assertEqual(sum(q['action'] == 'eth_getTransactionReceipt' for q in calls), 1)
                self.assertEqual(len(coverage['sources']), 5)
                self.assertTrue(all(event['success'] is bool(status) for event in events))
                self.assertEqual(any(e['relation'] == 'external_eth' for e in events), bool(status))
                self.assertTrue(all('execution_status_resolution' in e['lineage'] for e in events))
                raw = next(json.loads(p.read_text()) for p in (work/'raw_requests').glob('*.json')
                           if json.loads(p.read_text())['request']['action'] == 'txlist')
                self.assertEqual(raw['response']['result'][0]['txreceipt_status'], '0')
                self.assertNotIn('success', raw['response']['result'][0])

    def test_receipt_identity_mismatch_cannot_resolve_history_flags(self):
        from checks.test_data import tx
        root, other = fixtures.address(1), fixtures.address(2)
        row = tx(**{'from': root, 'to': other, 'timeStamp': str(self.cutoff-1),
                    'blockNumber': '99', 'txreceipt_status': '0'})
        def transport(query):
            if query['action'] == 'eth_getTransactionReceipt':
                return {'result': {'transactionHash': row['hash'], 'blockNumber': '0x62',
                    'blockHash': row['blockHash'], 'from': root, 'to': other, 'status': '0x1'}}
            return {'status': '1', 'result': [row] if query['action'] == 'txlist' else []}
        collector = RecentHistoryCollector({'actions': ['txlist', 'txlistinternal'], 'transport': transport})
        try:
            with self.assertRaisesRegex(CollectionError, 'recent_receipt_identity'):
                collector.collect({'target': root, 'cutoff': self.cutoff}, self.recent_config()['graph'],
                                  100, self.root / 'bad-receipt')
        finally:
            collector.close()

    def test_receipt_verification_budget_stops_additional_calls(self):
        from checks.test_data import tx
        collector = RecentHistoryCollector({'actions': ['txlist', 'txlistinternal']})
        rows = [tx(source_kind='normal', txreceipt_status='0')]
        try:
            with patch.object(collector, '_verify_execution', side_effect=AssertionError('over-budget request')):
                sources = [{'purpose': 'execution_status_verification', 'cache_hits': 0} for _ in range(8)]
                with self.assertRaisesRegex(CollectionError, 'receipt_verification_budget_pending'):
                    collector._normalize(rows, self.root / 'receipt-budget', sources, {})
        finally:
            collector.close()

    def test_receipt_budget_resume_reuses_cached_verifications_and_finishes_ninth(self):
        from checks.test_data import tx
        rows = [tx(source_kind='normal', hash=f'0x{i:064x}', blockNumber='99', txreceipt_status='0')
                for i in range(1, 10)]
        calls = []
        def transport(query):
            calls.append(query['txhash'])
            return {'result': {'transactionHash': query['txhash'], 'blockNumber': '0x63',
                'blockHash': rows[0]['blockHash'], 'from': rows[0]['from'], 'to': rows[0]['to'], 'status': '0x0'}}
        work = self.root / 'ninth-receipt'
        collector = RecentHistoryCollector({'actions': ['txlist', 'txlistinternal'], 'transport': transport})
        try:
            with self.assertRaisesRegex(CollectionError, 'receipt_verification_budget_pending'):
                collector._normalize(copy.deepcopy(rows), work, [], {})
            self.assertEqual(len(calls), 8)
            sources = []
            events, audit = collector._normalize(copy.deepcopy(rows), work, sources, {})
        finally:
            collector.close()
        self.assertTrue(audit['complete'])
        self.assertEqual(len(calls), 9)
        self.assertEqual(sum(s['cache_hits'] for s in sources), 8)
        self.assertEqual(len(events), 9)
        self.assertTrue(all(e['relation'] == 'failed_call' for e in events))

    def test_nonunique_internal_trace_ids_preserve_calls_and_observed_multiplicity(self):
        from checks.test_data import tx
        first = tx(source_kind='internal', traceId='0_1', type='call', value='1', gas='2300', gasUsed='83')
        second = dict(first, to=fixtures.address(999), value='2')
        rows = [dict(first, request_id='a', source_row=0), dict(first, request_id='a', source_row=1),
                dict(second, request_id='a', source_row=2), dict(first, request_id='b', source_row=0),
                dict(second, request_id='b', source_row=1)]
        collector = RecentHistoryCollector({'actions': ['txlist', 'txlistinternal']})
        try:
            with patch.object(collector, '_verification_request', side_effect=AssertionError('extra API call')):
                events, audit = collector._normalize(copy.deepcopy(rows), self.root/'internal-ids', [], {})
                reordered, _ = collector._normalize(list(reversed(copy.deepcopy(rows))), self.root/'internal-ids', [], {})
        finally:
            collector.close()
        self.assertTrue(audit['complete'])
        money = [e for e in events if e['relation'] == 'internal_eth']
        self.assertEqual(len(money), 3)
        self.assertEqual(sum(int(e['raw_amount']) for e in money), 4)
        self.assertEqual({e['event_id'] for e in events}, {e['event_id'] for e in reordered})
        self.assertTrue(all(e['lineage']['provider_original_trace_id'] == '0_1' for e in events))
        self.assertEqual(len(audit['trace_identity_resolutions']), 1)

    def test_scoped_internal_identity_preserves_root_transfer_suppression(self):
        from checks.test_data import tx
        normal = tx(source_kind='normal', value='11', request_id='normal', source_row=0)
        internal = dict(normal, source_kind='internal', traceId='0', type='call', request_id='internal')
        other = dict(internal, **{'from': internal['to'], 'to': fixtures.address(999), 'value': '4', 'source_row': 1})
        collector = RecentHistoryCollector({'actions': ['txlist', 'txlistinternal']})
        try:
            events, audit = collector._normalize([normal, internal, other], self.root/'root-transfer', [], {})
        finally:
            collector.close()
        self.assertTrue(audit['complete'])
        self.assertEqual(len(audit['suppressed_root_internal']), 1)
        self.assertEqual([e['raw_amount'] for e in events if e['relation'] == 'internal_eth'], ['4'])

    def test_local_failure_finishes_other_roots_and_resume_recovers_failures(self):
        out = self.root / 'local-failures'
        self.prepare(out, stage='cohort')
        targets = read_records(out / 'cohort/targets.jsonl')
        failed = {targets[0]['sample_id']: 'recent_normalization_failed:invalid_amount',
                  targets[1]['sample_id']: 'temporarily unavailable'}
        original = RecentHistoryCollector.collect
        attempted = []
        def collect(collector, target, *args):
            attempted.append(target['sample_id'])
            if target['sample_id'] in failed:
                raise CollectionError(failed[target['sample_id']])
            return original(collector, target, *args)
        with patch.object(RecentHistoryCollector, 'collect', new=collect), redirect_stderr(io.StringIO()):
            first = self.prepare(out, stage='collect')
        self.assertEqual(first['status'], 'collection_incomplete')
        self.assertEqual(first['collection']['sample_count'], 38)
        self.assertEqual(len(attempted), 40)
        with patch.object(RecentHistoryCollector, 'collect', new=lambda c,t,*a: original(c,t,*a)):
            self.assertEqual(self.prepare(out, stage='collect')['status'], 'collected')
        self.assertEqual(list((out / 'collection/failures').glob('*.json')), [])
        recovered = list((out / 'collection/failures/recovered').glob('*.json'))
        self.assertEqual(len(recovered), 2)
        self.assertTrue(all(load_json(p)['status'] == 'recovered' for p in recovered))

    def test_unified_runner_prepares_new_default_profile_and_training_dry_run(self):
        from research.scam.pipeline import main as runner
        out = self.root / 'cli-recent'
        settings = self.root / 'recent-settings.json'
        settings.write_text(json.dumps(self.recent_settings()))
        args = ['--snapshot', 'cli-recent', '--output', str(out), '--settings', str(settings), '--progress', 'off']
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for stage in ('sources', 'collect', 'prepare'):
                self.assertEqual(runner([*args, '--stage', stage, '--source-as-of', str(self.cutoff)]), 0)
            self.assertEqual(runner([*args, '--stage', 'train', '--run', 'dry-check', '--dry-run']), 0)
        self.assertTrue((out / 'prepared/dataset_manifest.json').exists())
        self.assertEqual(load_json(out / 'cohort/manifest.json')['config']['history_policy'], 'bounded_recent')

    def test_new_graph_bundle_roundtrip_and_legacy_recipe_isolation(self):
        import torch
        from packages.bundle import export_model_bundle, load_model_bundle, predict_bundle
        from packages.models import create_model
        out = self.root / 'bundle-input'
        self.prepare(out)
        graphs = read_records(out / 'prepared/graphs.jsonl')
        scaler = fit_scaler(graphs[:2])
        config = self.recent_config()['model']
        model = create_model(config, input_dim=20, edge_dim=11, num_relations=28)
        path = self.root / 'bundle'
        export_model_bundle(path, model, config, scaler, 'phishing', .5,
                            {'config': self.recent_config(), 'graph_recipe': scaler['graph_recipe']})
        loaded = load_model_bundle(path)
        self.assertEqual(loaded.manifest['graph_view_version'], RECENT_VIEW_VERSION)
        self.assertEqual(len(predict_bundle(loaded, graphs[:2])), 2)
        bad = copy.deepcopy(graphs[0]); bad['lineage']['sampling']['rows_per_action'] = 101
        with self.assertRaisesRegex(ValueError, 'recipe'):
            predict_bundle(loaded, [bad])


class ConcurrentBudgetTests(unittest.TestCase):
    def test_shared_budget_spaces_starts_while_http_contexts_overlap(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            budget = SerialRequestBudget(Path(directory) / 'quota.sqlite3', rate=2.5)
            lock = threading.Lock()
            starts, active, peak = [], 0, 0
            def request():
                nonlocal active, peak
                with budget.request_slot():
                    with lock:
                        starts.append(time.monotonic()); active += 1; peak = max(peak, active)
                    time.sleep(.6)
                    with lock:
                        active -= 1
            with ThreadPoolExecutor(max_workers=5) as pool:
                list(pool.map(lambda _: request(), range(5)))
            self.assertGreater(peak, 1)
            self.assertTrue(all(b-a >= 1/2.5 - .015 for a,b in zip(starts, starts[1:])))
            with sqlite3.connect(budget.path) as db:
                self.assertEqual(db.execute('SELECT SUM(calls) FROM buckets').fetchone()[0], 5)

    def test_daily_quota_wait_can_be_cancelled_without_a_second_reservation(self):
        import tempfile
        noticed = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            budget = SerialRequestBudget(Path(directory) / 'quota.sqlite3', rate=2.5, limit=1,
                                         notify=lambda _: noticed.set())
            with budget.request_slot():
                pass
            def waiting_request():
                with budget.request_slot():
                    self.fail('daily quota allowed an extra request')
            with ThreadPoolExecutor(max_workers=1) as pool:
                task = pool.submit(waiting_request)
                self.assertTrue(noticed.wait(2))
                budget.cancel()
                with self.assertRaises(InterruptedError):
                    task.result(timeout=2)
            with sqlite3.connect(budget.path) as db:
                self.assertEqual(db.execute('SELECT SUM(calls) FROM buckets').fetchone()[0], 1)
