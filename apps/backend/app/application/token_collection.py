"""Cutoff-bound ERC-20/v2 discovery and replayable newest-first log scans."""
import asyncio
import hashlib
import json
import re

from packages.io import atomic_bytes
from packages.token import UNISWAP_V2_FACTORY
from packages.transactions import address, integer, decode_v2_log, V2_TOPICS

from ..adapters.analysis_store import utc
from ..errors import ServiceError
from .eth_collection import EthCollection

ZERO = '0x' + '0' * 40
QUOTES = (
    ('0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2', 'WETH'),
    ('0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', 'USDC'),
    ('0xdac17f958d2ee523a2206206994597c13d831ec7', 'USDT'),
    ('0x6b175474e89094c44da98b954eedeac495271d0f', 'DAI'),
)
PAIR_TOPIC = next(k for k, v in V2_TOPICS.items() if v == 'pair_created')


def uint_word(raw):
    if not isinstance(raw, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', raw):
        raise ValueError('invalid_uint_abi')
    return int(raw, 16)


def address_word(raw):
    value = uint_word(raw)
    if value >= 2**160:
        raise ValueError('invalid_address_abi')
    return '0x' + f'{value:040x}'


def abi_text(raw):
    if not isinstance(raw, str) or len(raw) > 8194 or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})*', raw):
        raise ValueError('invalid_text_abi')
    data = bytes.fromhex(raw[2:])
    if len(data) == 32:
        data = data.rstrip(b'\0')
    else:
        if len(data) < 64 or int.from_bytes(data[:32], 'big') != 32:
            raise ValueError('invalid_text_offset')
        size = int.from_bytes(data[32:64], 'big')
        if size > 256 or len(data) < 64 + size:
            raise ValueError('invalid_text_size')
        data = data[64:64+size]
    value = data.decode('utf-8').strip()
    if not value or any(ord(c) < 32 for c in value):
        raise ValueError('invalid_text')
    return value[:128]


class TokenCollection(EthCollection):
    async def rpc_capture(self, method, params):
        query = {'method': method, 'params': params}
        key = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
        path = self.directory / 'rpc' / f'{key}.json'
        if path.exists():
            data = json.loads(path.read_text())
            if data['query'] != query or data['sha256'] != hashlib.sha256(json.dumps(data['result'], sort_keys=True).encode()).hexdigest():
                raise ServiceError('data_incomplete')
            return data['result'], str(path)
        result = await self.rpc.call(method, params)
        await asyncio.to_thread(atomic_bytes, path, json.dumps({'query': query, 'result': result,
            'sha256': hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(), 'retrieved_at': utc()}).encode(), immutable=True)
        return result, str(path)

    async def call(self, context, entity, selector):
        return await self.rpc_capture('eth_call', [{'to': entity, 'data': selector},
            {'blockHash': context['cutoff_hash'], 'requireCanonical': True}])

    def publish_context(self, context):
        from .token_presentation import basic_information
        self.store.save(self.lease, {'cutoff': utc(context['cutoff']), 'cutoff_block': context['cutoff_block'],
            'cutoff_block_hash': context['cutoff_hash'], 'window_start': utc(context['window_start']),
            'snapshot_id': context['snapshot_id'], 'basic_information': basic_information(context)},
            artifacts={('context', ''): context})

    async def freeze(self, request):
        context = await super().freeze(request)
        if context.get('token_resolution_complete'):
            return context
        if context['entity_type'] not in ('contract', 'token'):
            raise ServiceError('invalid_token')
        if not context.get('token_metadata'):
            try:
                raw, ref = await self.call(context, request.target, '0x313ce567')
                decimals = uint_word(raw)
                supply, _ = await self.call(context, request.target, '0x18160ddd')
                balance, _ = await self.call(context, request.target, '0x70a08231' + ZERO[2:].rjust(64, '0'))
                if decimals > 255:
                    raise ValueError('invalid_precision')
                context.update(entity_type='token', total_supply_raw=str(uint_word(supply)),
                    zero_balance_raw=str(uint_word(balance)), token_metadata={'decimals': decimals,
                    'verified_at_block': context['cutoff_block'], 'evidence_ref': ref})
            except ValueError:
                raise ServiceError('invalid_token') from None
            except ServiceError as error:
                if error.code == 'provider_response_invalid':
                    raise ServiceError('invalid_token') from None
                raise
            for name, selector in (('symbol', '0x95d89b41'), ('name', '0x06fdde03')):
                try:
                    raw, _ = await self.call(context, request.target, selector)
                    context[name] = abi_text(raw)
                except ValueError:
                    context[name] = None
                except ServiceError as error:
                    if error.code not in ('provider_response_invalid',):
                        raise
                    context[name] = None
            self.publish_context(context)
        if request.pools:
            selected = list(request.pools)
        else:
            # Indexed factory metadata discovers both token positions, including
            # non-WETH pairs; never infer a pool from a holder/transfer address.
            candidates = {}
            root_topic = '0x' + request.target[2:].rjust(64, '0')
            for slot in (1, 2):
                async for batch in self.log_batches(UNISWAP_V2_FACTORY, 0, context['cutoff_block'], context['cutoff'],
                        topic0=PAIR_TOPIC, **{f'topic{slot}': root_topic, f'topic0_{slot}_opr': 'and'}):
                    for row in batch:
                        try:
                            event = decode_v2_log(row)
                        except ValueError:
                            raise ServiceError('data_incomplete') from None
                        if not event or event['relation'] != 'pair_created' or request.target not in (event['token0'], event['token1']):
                            raise ServiceError('data_incomplete')
                        candidates[event['pool']] = {**event, 'block': integer(row['blockNumber'])}
            quote_rank = {a: i for i, (a, _) in enumerate(QUOTES)}
            def order(item):
                other = item['token1'] if item['token0'] == request.target else item['token0']
                return quote_rank.get(other, len(QUOTES)), item['block'], item['pool']
            selected = [min(candidates.values(), key=order)['pool']] if candidates else []
            context['pool_discovery'] = {'factory': UNISWAP_V2_FACTORY, 'candidate_count': len(candidates),
                'policy': 'WETH-USDC-USDT-DAI-then-other; earliest creation; one pool by default'}
        metadata = []
        for pool in selected:
            facts = {'pool': pool, 'verified_at_block': context['cutoff_block']}
            refs = []
            try:
                for key, selector in (('token0', '0x0dfe1681'), ('token1', '0xd21220a7'), ('factory', '0xc45a0155')):
                    raw, ref = await self.call(context, pool, selector)
                    facts[key] = address_word(raw); refs.append(ref)
                if (facts['factory'] != UNISWAP_V2_FACTORY or facts['token0'] >= facts['token1']
                        or request.target not in (facts['token0'], facts['token1'])):
                    raise ValueError('unsupported_pair')
                raw, ref = await self.call(context, UNISWAP_V2_FACTORY,
                    '0xe6a43905' + facts['token0'][2:].rjust(64, '0') + facts['token1'][2:].rjust(64, '0'))
                if address_word(raw) != pool:
                    raise ValueError('factory_membership')
                facts.update(evidence_ref=ref, getter_refs=refs)
            except ValueError:
                raise ServiceError('invalid_pool') from None
            metadata.append(facts)
            quote = facts['token1'] if facts['token0'] == request.target else facts['token0']
            try:
                raw, _ = await self.call(context, quote, '0x313ce567')
                precision = uint_word(raw)
                if precision > 255:
                    raise ValueError('invalid_precision')
                context.setdefault('quote_metadata', {})[quote] = {'decimals': precision,
                    'symbol': dict(QUOTES).get(quote, quote)}
            except ValueError:
                context.setdefault('quote_metadata', {})[quote] = {'decimals': None, 'symbol': quote}
            except ServiceError as error:
                if error.code != 'provider_response_invalid':
                    raise
                context.setdefault('quote_metadata', {})[quote] = {'decimals': None, 'symbol': quote}
        context.update(pools=sorted(selected), pool_metadata=metadata, token_resolution_complete=True)
        self.publish_context(context)
        return context

    async def log_batches(self, entity, low, high, cutoff, *, limit=None, max_queries=None, **filters):
        """Newest ranges first; a saturated range is split before selecting rows.

        No descending sort is assumed for getLogs. A single saturated block is
        completely paginated or explicitly fails, never silently truncated.
        """
        queries = 0
        remaining = limit
        async def fetch(start, end, page=1):
            nonlocal queries
            queries += 1
            if max_queries is not None and queries > max_queries:
                raise ServiceError('data_incomplete')
            raw = await self.fetch('logs', 'getLogs', address=entity, fromBlock=start, toBlock=end,
                                   page=page, offset=1000, **filters)
            if len(raw) > 1000:
                raise ServiceError('data_incomplete')
            if raw:
                self.records += len(raw)
                self.store.save(self.lease, {'progress': {'state': 'running', 'unit': 'requests',
                    'completed': self.completed, 'total': None, 'total_final': False, 'records_collected': self.records}})
            query = {'chainid': 1, 'module': 'logs', 'action': 'getLogs', 'address': entity,
                'fromBlock': start, 'toBlock': end, 'page': page, 'offset': 1000, **filters}
            key = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
            capture_path = self.directory / 'requests' / f'{key}.json'
            retrieved_at = json.loads(capture_path.read_text())['retrieved_at']
            result = []
            for i, row in enumerate(raw):
                block = integer(row.get('blockNumber'))
                if address(row.get('address')) != entity or block is None or not start <= block <= end or row.get('removed') is True:
                    raise ServiceError('data_incomplete')
                stamp = integer(row.get('timeStamp'))
                if stamp is None:
                    header, _ = await self.rpc_capture('eth_getBlockByNumber', [hex(block), False])
                    if not isinstance(header, dict) or integer(header.get('number')) != block:
                        raise ServiceError('data_incomplete')
                    stamp = integer(header.get('timestamp'))
                if stamp is None or stamp > cutoff or integer(row.get('logIndex')) is None:
                    raise ServiceError('data_incomplete')
                result.append({**row, 'timeStamp': str(stamp), 'source_kind': 'logs', 'request_id': key,
                    'source_row': i, 'raw_path': str(capture_path), 'retrieved_at': retrieved_at})
            return result
        async def interval(start, end):
            rows = await fetch(start, end)
            if len(rows) == 1000 and start < end:
                mid = (start + end) // 2
                async for batch in interval(mid+1, end):
                    yield batch
                if remaining is None or remaining > 0:
                    async for batch in interval(start, mid):
                        yield batch
                return
            if len(rows) == 1000:
                for page in range(2, 17):
                    more = await fetch(start, end, page)
                    rows.extend(more)
                    if len(more) < 1000:
                        break
                else:
                    raise ServiceError('data_incomplete')
            identities = [(r.get('transactionHash'), integer(r.get('logIndex'))) for r in rows]
            if len(set(identities)) != len(identities):
                raise ServiceError('data_incomplete')
            rows.sort(key=lambda r: (integer(r['blockNumber']), integer(r.get('transactionIndex')) or 0,
                                      integer(r['logIndex'])), reverse=True)
            yield rows
        # Discovery filters can span the entire chain in one small response.
        span = high - low + 1 if filters else 50000
        while high >= low and (remaining is None or remaining > 0):
            start = max(low, high - span + 1)
            stream = interval(start, high)
            try:
                async for batch in stream:
                    if remaining is not None:
                        batch = batch[:remaining]
                        remaining -= len(batch)
                    if batch:
                        yield batch
                    if remaining == 0:
                        return
            finally:
                await stream.aclose()
            high, span = start-1, min(span*2, 2000000)

    async def model_account(self, context, entity, action, pages, rows):
        result, exhausted = [], False
        for page in range(1, pages+1):
            batch = await self.fetch('account', action, address=entity, startblock=0,
                endblock=context['cutoff_block'], sort='desc', page=page, offset=rows)
            if len(batch) > rows:
                raise ServiceError('data_incomplete')
            self.validate_rows(batch, entity, 0, context['cutoff_block'], context['cutoff'])
            if result and batch and integer(batch[0]['blockNumber']) > integer(result[-1]['blockNumber']):
                raise ServiceError('data_incomplete')
            result.extend(batch)
            if len(batch) < rows:
                exhausted = True; break
        return result, exhausted

    async def normalize(self, raw):
        events, audit, rows = await super().normalize(raw)
        context = self.store.artifact(self.lease['id'], 'context') or {}
        pools = set(context.get('pools', []))
        positions = {(str(r.get('transactionHash')).lower(), integer(r.get('logIndex'))):
                     integer(r.get('transactionIndex')) for r in rows if r.get('source_kind') == 'logs'}
        for event in events:
            if event.get('log_index') is not None:
                event['transaction_index'] = positions.get((event['tx_hash'], event['log_index']))
            if event['relation'] == 'erc20_transfer' and event.get('asset') in pools:
                event['relation'] = 'lp_transfer'
        return events, audit, rows
