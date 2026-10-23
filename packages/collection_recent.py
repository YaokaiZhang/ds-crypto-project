"""Bounded descending address histories with one shared in-process API budget."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import hashlib
import json
import threading
from pathlib import Path

from .collection import CollectionError, EtherscanClient
from .data import SOURCE_KINDS, normalize_records
from .graph import RECENT_SAMPLING, recent_neighbors
from .io import save_json
from .provider_access import SerialRequestBudget, REQUESTS_PER_SECOND
from .transactions import address, integer


class RecentHistoryCollector:
    """Bounded roots share concurrent independent history-action workers.

    Raw response caches are owned by the caller's current sample work directory.
    This collector never traverses older pages beyond the frozen page budget.
    """
    def __init__(self, settings, *, budget=None, observer=None, sample_observer=None):
        self.settings = dict(settings)
        self.settings.pop("shared_cache_dir", None)
        self.rows = int(settings.get("page_size", 100))
        self.pages = int(settings.get("max_pages", 1))
        self.workers = int(settings.get("workers", 5))
        if not 1 <= self.rows <= 1000 or not 1 <= self.pages <= 3 or not 1 <= self.workers <= 16:
            raise ValueError("invalid_recent_history_rows_pages_or_workers")
        if set(settings.get("actions", ())) != {"txlist", "txlistinternal"}:
            raise ValueError("recent_history_requires_external_and_internal_actions")
        rate = min(REQUESTS_PER_SECOND, float(settings.get("rate_limit_rps", REQUESTS_PER_SECOND)))
        self.budget = budget or SerialRequestBudget(rate=rate)
        self.observer = observer
        self.sample_observer = sample_observer
        self.lock = threading.Lock()
        self.states = {}
        self.samples = {}
        self.totals = {key: 0 for key in ("requests", "cache_hits", "http_attempts", "http_seconds")}
        self.executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="recent-history")

    def close(self, *, cancel=False):
        if cancel:
            self.budget.cancel()
        self.executor.shutdown(wait=True, cancel_futures=True)

    def _observe(self, identity, state, work=None):
        with self.lock:
            previous = self.states.get(identity, {})
            for key in self.totals:
                delta = state.get(key, 0) - previous.get(key, 0)
                self.totals[key] += delta
                if str(work) in self.samples:
                    self.samples[str(work)][key] = self.samples[str(work)].get(key, 0) + delta
            self.states[identity] = state
            sample = self.samples.get(str(work))
            if sample is not None:
                sample['action'] = state['query'].get('action')
                if state['phase'] in {'received', 'cache'}:
                    sample['completed_queries'] += 1
                if self.sample_observer:
                    self.sample_observer(dict(sample))
            if self.observer:
                self.observer(self.stats(), state["query"])

    def _sample_phase(self, work, phase, extra_queries=0):
        with self.lock:
            sample = self.samples.get(str(work))
            if sample is not None:
                sample['phase'] = phase
                sample['total_queries'] += extra_queries
                if self.sample_observer:
                    self.sample_observer(dict(sample))

    def stats(self):
        return dict(self.totals)

    def cutoff_block(self, cutoff, work):
        client = EtherscanClient(work, self.settings)
        client.budget = self.budget
        client.on_progress = lambda state: self._observe("cutoff", state)
        return client.block_by_time(cutoff)

    def _fetch(self, entity, action, cutoff, end_block, work, stop):
        identity = f"{work}:{entity}:{action}"
        try:
            return self._fetch_impl(entity, action, cutoff, end_block, work, identity, stop)
        finally:
            with self.lock:
                self.states.pop(identity, None)

    def _fetch_impl(self, entity, action, cutoff, end_block, work, identity, stop):
        client = EtherscanClient(work, self.settings)
        client.settings["cancel_event"] = stop
        client.budget = self.budget
        client.on_progress = lambda state: self._observe(identity, state, work)
        rows, requests = [], []
        full = False
        previous_block = end_block
        for page in range(1, self.pages + 1):
            if stop.is_set():
                raise CollectionError("sample_request_cancelled")
            if page > 1:
                self._sample_phase(work, f'page {page}', 1)
            bundle = client.request("account", action, address=entity, startblock=0, endblock=end_block,
                                    page=page, offset=self.rows, sort="desc")
            raw = bundle["response"].get("result") or []
            if len(raw) > self.rows:
                raise CollectionError("recent_response_page_size_exceeded")
            for index, row in enumerate(raw):
                block = integer(row.get("blockNumber"))
                stamp = integer(row.get("timeStamp"))
                src, dst = address(row.get("from")), address(row.get("to")) or address(row.get("contractAddress"))
                if (block is None or not 0 <= block <= previous_block or stamp is None or stamp > cutoff
                        or entity not in (src, dst)):
                    raise CollectionError("recent_row_outside_cutoff_address_or_descending_order")
                previous_block = block
                rows.append({**row, "source_kind": SOURCE_KINDS[action], "request_id": bundle["request_id"],
                             "source_row": index, "retrieved_at": bundle["retrieved_at"],
                             "_history_address": entity, "_history_page": page})
            requests.append({"request_id": bundle["request_id"], "query": bundle["request"],
                             "response_sha256": bundle["response_sha256"], "retrieved_at": bundle["retrieved_at"],
                             "endpoint": bundle["endpoint"], "returned_rows": len(raw)})
            requests[-1]["response_bytes"] = Path(bundle["raw_path"]).stat().st_size
            full = len(raw) == self.rows
            if not full:
                break
        return rows, {"address": entity, "action": action, "complete": True,
                      "sampling_limit_reached": full, "rows": len(rows), "requests": requests,
                      "http_attempts": client.http_attempts, "cache_hits": client.cached_count,
                      "http_seconds": client.http_seconds}

    def _verification_request(self, row, work, module, action):
        tx_hash = row['hash'].lower()
        identity = f"{work}:verify:{action}:{tx_hash}"
        client = EtherscanClient(work, self.settings)
        client.budget = self.budget
        client.on_progress = lambda state: self._observe(identity, state, work)
        self._sample_phase(work, 'receipt', 1)
        try:
            bundle = client.request(module, action, txhash=tx_hash)
        finally:
            with self.lock:
                self.states.pop(identity, None)
        request = {'request_id': bundle['request_id'], 'query': bundle['request'],
                   'response_sha256': bundle['response_sha256'], 'retrieved_at': bundle['retrieved_at'],
                   'endpoint': bundle['endpoint'],
                   'response_bytes': Path(bundle['raw_path']).stat().st_size}
        source = {'address': row['from'].lower(), 'action': action, 'hop': -1,
                  'purpose': 'provider_record_verification', 'complete': True, 'requests': [request],
                  'http_attempts': client.http_attempts, 'cache_hits': client.cached_count,
                  'http_seconds': client.http_seconds}
        return bundle, source

    def _verify_execution(self, row, work):
        """Resolve conflicting ordinary-history flags from the matching receipt."""
        bundle, source = self._verification_request(row, work, 'proxy', 'eth_getTransactionReceipt')
        tx_hash = row['hash'].lower()
        receipt = bundle['response'].get('result')
        if not isinstance(receipt, dict):
            raise CollectionError('recent_receipt_execution_status_unresolved')
        status = integer(receipt.get('status'))
        if (str(receipt.get('transactionHash', '')).lower() != tx_hash
                or integer(receipt.get('blockNumber')) != integer(row.get('blockNumber'))
                or str(receipt.get('blockHash', '')).lower() != str(row.get('blockHash', '')).lower()
                or address(receipt.get('from')) != address(row.get('from'))
                or address(receipt.get('to')) != address(row.get('to'))
                or status not in (0, 1)):
            raise CollectionError('recent_receipt_identity_or_execution_status_mismatch')
        request = source['requests'][0]
        request['returned_rows'] = 1
        source['purpose'] = 'execution_status_verification'
        resolution = {'tx_hash': tx_hash, 'block_number': integer(receipt['blockNumber']),
                      'block_hash': str(receipt['blockHash']).lower(),
                      'from': address(receipt.get('from')), 'to': address(receipt.get('to')),
                      'receipt_status': status, 'receipt_request': request, 'history_flags': []}
        return resolution, source

    @staticmethod
    def _internal_identity(row):
        return (integer(row.get('blockNumber')), integer(row.get('timeStamp')),
                address(row.get('from')), address(row.get('to')), address(row.get('contractAddress')),
                integer(row.get('value')), str(row.get('type', '')).lower(),
                integer(row.get('gas')), integer(row.get('gasUsed')),
                str(row.get('input') or '0x').lower(), str(row.get('isError')), str(row.get('errCode', '')),
                str(row.get('original_trace_id', row.get('traceId'))) == '0')

    def _scope_internal_records(self, rows, traces):
        groups = defaultdict(set)
        for row in rows:
            original = row.get('original_trace_id', row.get('traceId'))
            if row.get('source_kind') == 'internal' and original and row.get('hash'):
                tx_hash = str(row['hash']).lower()
                groups[(tx_hash, original)].add(self._internal_identity(row))
        for (tx_hash, _), identities in groups.items():
            if len(identities) < 2:
                continue
            traces.setdefault(tx_hash, {'evidence': {
                'tx_hash': tx_hash,
                'identity_scope': 'provider_observed_records_not_canonical_evm_paths',
                'observed_mappings': []}})
        # Provider traceId is not a unique call identity. Keep distinct observed
        # records and their within-address multiplicity; overlapping histories
        # deduplicate equal record occurrences. No unseen transfers are imported.
        occurrences = defaultdict(int)
        for row in sorted(rows, key=lambda r: (r.get('_history_address', r.get('request_id', '')),
                                               r.get('_history_page', 1), r.get('source_row', 0))):
            tx_hash = str(row.get('hash', '')).lower()
            if row.get('source_kind') != 'internal' or tx_hash not in traces:
                continue
            if not row.get('original_trace_id', row.get('traceId')):
                continue  # Missing trace metadata remains an explicit invalid row.
            identity = self._internal_identity(row)
            key = (row.get('_history_address', row['request_id']), tx_hash, identity)
            ordinal = occurrences[key]
            occurrences[key] += 1
            row.setdefault('original_trace_id', row.get('traceId'))
            digest = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
            row['traceId'] = f'provider-record:{digest}:{ordinal}'
            mapping = {name: row.get(name) for name in ('request_id', 'source_row', 'original_trace_id')}
            mapping['observed_record_identity'] = row['traceId']
            mappings = traces[tx_hash]['evidence']['observed_mappings']
            if mapping not in mappings:
                mappings.append(mapping)

    def _check_bytes(self, sources):
        size = sum(r['response_bytes'] for source in sources for r in source['requests'])
        if size > int(self.settings.get('max_sample_bytes', 16 * 1024 * 1024)):
            raise CollectionError('sample_byte_budget_exhausted')

    def _normalize(self, rows, work, sources, resolutions, traces=None):
        self._sample_phase(work, 'normalize')
        traces = traces if traces is not None else {}
        self._scope_internal_records(rows, traces)
        events, audit = normalize_records(rows)
        if not audit['complete']:
            save_json(Path(work) / 'normalization_failure.json', audit)
        for invalid in audit['invalid_records']:
            if invalid['reason'] != 'conflicting_transaction_success_flags':
                continue
            row = rows[invalid['row']]
            # A transaction receipt cannot resolve an individual internal trace.
            if row['source_kind'] != 'normal':
                continue
            tx_hash = row['hash'].lower()
            if tx_hash not in resolutions:
                query = {'chainid': 1, 'module': 'proxy', 'action': 'eth_getTransactionReceipt', 'txhash': tx_hash}
                cached = Path(work) / 'raw_requests' / f'{EtherscanClient.request_id(query)}.json'
                new_lookups = sum(s.get('purpose') == 'execution_status_verification'
                                  and not s.get('cache_hits') for s in sources)
                if new_lookups >= 8 and not cached.exists():
                    raise CollectionError('recent_receipt_verification_budget_pending')
                resolution, source = self._verify_execution(row, work)
                resolutions[tx_hash] = resolution
                sources.append(source)
                self._check_bytes(sources)
        for row in rows:
            tx_hash = str(row.get('hash', '')).lower()
            if row.get('source_kind') != 'normal' or tx_hash not in resolutions:
                continue
            resolution = resolutions[tx_hash]
            if (integer(row.get('blockNumber')) != resolution['block_number']
                    or str(row.get('blockHash', '')).lower() != resolution['block_hash']
                    or address(row.get('from')) != resolution['from']
                    or address(row.get('to')) != resolution['to']):
                raise CollectionError('recent_receipt_identity_or_execution_status_mismatch')
            original = {key: row.get(key) for key in ('request_id', 'source_row', 'isError', 'txreceipt_status')}
            if original not in resolution['history_flags']:
                resolution['history_flags'].append(original)
            row['success'] = resolution['receipt_status'] == 1
        if resolutions:
            events, audit = normalize_records(rows)
        if not audit['complete']:
            save_json(Path(work) / 'normalization_failure.json', audit)
            reasons = ','.join(sorted({r['reason'] for r in audit['invalid_records']}))
            raise CollectionError(f'recent_normalization_failed:{reasons}')
        for event in events:
            if event['source_kind'] == 'normal' and event['tx_hash'] in resolutions:
                event['lineage']['execution_status_resolution'] = resolutions[event['tx_hash']]
            if event['source_kind'] == 'internal' and event['tx_hash'] in traces:
                event['lineage']['internal_identity_scope'] = 'provider_observed_records_not_canonical_evm_paths'
        audit['execution_status_resolutions'] = [resolutions[k] for k in sorted(resolutions)]
        audit['trace_identity_resolutions'] = [traces[k]['evidence'] for k in sorted(traces)]
        return events, audit

    def collect(self, target, graph, end_block, work):
        if self.sample_observer:
            with self.lock:
                self.samples[str(work)] = {'sample_id': target.get('sample_id', target['target']),
                    'target': target['target'], 'phase': 'starting', 'completed_queries': 0,
                    'total_queries': 0, 'http_attempts': 0, 'cache_hits': 0}
        try:
            return self._collect_impl(target, graph, end_block, work)
        finally:
            with self.lock:
                self.samples.pop(str(work), None)

    def _collect_impl(self, target, graph, end_block, work):
        root, cutoff = target["target"], target["cutoff"]
        all_rows, sources, scopes = [], [], []
        resolutions = {}
        traces = {}
        stop = threading.Event()
        frontier = [root]
        sampled = {root}
        truncated = False
        for hop in range(graph["hops"]):
            self._sample_phase(work, f'hop {hop+1}/{graph["hops"]}', len(frontier) * 2)
            futures = {self.executor.submit(self._fetch, entity, action, cutoff, end_block, work, stop): (entity, action)
                       for entity in frontier for action in ("txlist", "txlistinternal")}
            histories = {entity: [] for entity in frontier}
            failures = []
            for future in as_completed(futures):
                entity, action = futures[future]
                try:
                    rows, coverage = future.result()
                    sources.append({**coverage, "hop": hop})
                    self._check_bytes(sources)
                    histories[entity].extend(rows)
                    all_rows.extend(rows)
                    truncated |= coverage["sampling_limit_reached"]
                except Exception as error:
                    # Drain every future before the caller can clean or reuse
                    # this sample directory. Never publish a partial sample.
                    failures.append(error)
                    stop.set()
                    for job in futures:
                        job.cancel()
            if failures:
                raise failures[0]
            next_frontier = []
            for entity in frontier:
                events, audit = self._normalize(histories[entity], work, sources, resolutions, traces)
                selected = recent_neighbors(entity, events, graph["fanouts"][hop])
                admitted = []
                for other in selected:
                    if other not in sampled:
                        if len(sampled) >= graph["max_nodes"]:
                            truncated = True
                            continue
                        sampled.add(other)
                        next_frontier.append(other)
                    admitted.append(other)
                scopes.append({"address": entity, "hop": hop, "selected_neighbors": admitted})
            frontier = sorted(next_frontier)
            if not frontier:
                break
        # Deterministic ordering makes graphs independent of worker completion order.
        all_rows.sort(key=lambda row: (row["request_id"], row["source_row"]))
        events, audit = self._normalize(all_rows, work, sources, resolutions, traces)
        self._check_bytes(sources)
        for event in events:
            event.pop("input", None)  # parsed call/transfer semantics are retained
            event.pop("function_name", None)
        sources.sort(key=lambda row: (row["hop"], row["address"], row["action"]))
        scopes.sort(key=lambda row: (row["hop"], row["address"]))
        coverage = {"scope": RECENT_SAMPLING, "complete": True, "sampled_history_complete": True,
                    "full_history_complete": False, "neighborhood_history_complete": False,
                    "cutoff": cutoff, "cutoff_block": end_block, "sources": sources,
                    "frontier_scopes": scopes, "sampling_truncated": truncated,
                    **{key: graph[key] for key in ("hops", "fanouts", "seed", "max_nodes", "rows_per_action", "pages_per_action")}}
        return events, coverage, audit
