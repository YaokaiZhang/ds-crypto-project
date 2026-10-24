"""Resolve selected-pool t0 and freeze the first-seven-day replay window."""
from copy import deepcopy
import hashlib
import json

from packages.transactions import integer, decode_v2_log
from packages.token import UNISWAP_V2_FACTORY
from ..adapters.analysis_store import utc
from ..errors import ServiceError
from .token_collection import TokenCollection, PAIR_TOPIC


class ForecastCollection(TokenCollection):
    def publish_context(self, context):
        from .forecast_presentation import basic_information
        resolved = context.get('forecast_window_resolved', False)
        self.store.save(self.lease, {'cutoff': utc(context['cutoff']) if resolved else None,
            'cutoff_block': context['cutoff_block'] if resolved else None,
            'cutoff_block_hash': context['cutoff_hash'] if resolved else None,
            'window_start': utc(context['window_start']) if resolved else None,
            'snapshot_id': context['snapshot_id'], 'basic_information': basic_information(context)},
            artifacts={('context', ''): context})

    async def finish_window(self, context, request):
        request = request.model_copy(update={'pools': list(context['pools'])})
        # Reverify decimals, total supply and pair getters at the first-week end,
        # never reuse today's mutable ERC-20 state in historical features.
        context = await super().freeze(request)
        context['forecast_resolution_complete'] = True
        self.publish_context(context)
        return context

    async def freeze(self, request):
        existing = self.store.artifact(self.lease['id'], 'context')
        if existing and existing.get('forecast_resolution_complete'):
            return existing
        if existing and existing.get('forecast_window_resolved'):
            return await self.finish_window(existing, request)
        context = await super().freeze(request)
        self.store.save(self.lease, {}, artifacts={('forecast_discovery_context', ''): context})
        if not context['pools']:
            context.update(family='forecast', forecast_resolution_complete=True)
            self.publish_context(context)
            return context
        found = {}
        root_topic = '0x' + request.target[2:].rjust(64, '0')
        for slot in (1, 2):
            async for batch in self.log_batches(UNISWAP_V2_FACTORY, 0, context['cutoff_block'], context['cutoff'],
                    topic0=PAIR_TOPIC, **{f'topic{slot}': root_topic, f'topic0_{slot}_opr': 'and'}):
                for row in batch:
                    try:
                        event = decode_v2_log(row)
                    except ValueError:
                        raise ServiceError('data_incomplete') from None
                    if not event or event.get('pool') not in context['pools']:
                        continue
                    if request.target not in (event.get('token0'), event.get('token1')):
                        raise ServiceError('data_incomplete')
                    fact = {'pool': event['pool'], 'block': integer(row['blockNumber']),
                            'timestamp': integer(row['timeStamp']), 'evidence_ref': row['raw_path']}
                    if event['pool'] in found and found[event['pool']] != fact:
                        raise ServiceError('data_incomplete')
                    found[event['pool']] = fact
        if set(found) != set(context['pools']):
            raise ServiceError('data_incomplete')
        first = min(found.values(), key=lambda f: (f['timestamp'], f['block']))
        t0, nominal_end = first['timestamp'], first['timestamp'] + 7*86400
        mature = nominal_end <= context['cutoff']
        cutoff = nominal_end if mature else context['cutoff']
        number = integer(await self.fetch('block', 'getblocknobytime', timestamp=cutoff, closest='before'))
        if number is None or number > context['cutoff_block'] or number < first['block']:
            raise ServiceError('data_incomplete')
        header, _ = await self.rpc_capture('eth_getBlockByNumber', [hex(number), False])
        if (not isinstance(header, dict) or integer(header.get('number')) != number
                or integer(header.get('timestamp')) is None or not t0 <= integer(header['timestamp']) <= cutoff or not header.get('hash')):
            raise ServiceError('data_incomplete')
        context = deepcopy(context)
        eligible = sorted(pool for pool, fact in found.items() if fact['timestamp'] <= cutoff and fact['block'] <= number)
        context.update(family='forecast', t0=t0, forecast_nominal_end=nominal_end, observation_complete=mature,
            discovery_cutoff=context['cutoff'], window_start=t0, start_block=first['block'],
            cutoff=cutoff, cutoff_block=number, cutoff_hash=header['hash'], state_timestamp=integer(header['timestamp']),
            pools=eligible, pool_metadata=[], token_metadata={}, quote_metadata={}, name=None, symbol=None,
            token_resolution_complete=False, boundary_inclusive=True, forecast_window_resolved=True,
            forecast_pool_creations=found)
        context['snapshot_id'] = hashlib.sha256(json.dumps({k:context[k] for k in
            ('target','pools','t0','cutoff','cutoff_block','cutoff_hash')}, sort_keys=True).encode()).hexdigest()
        self.publish_context(context)
        return await self.finish_window(context, request)
