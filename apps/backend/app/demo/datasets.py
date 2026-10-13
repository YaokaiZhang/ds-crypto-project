"""Load frozen JSON scenarios; never generate transactions at request time.

Only address aliases and analysis/sample identities are adapted per request.
All observations, amounts, timestamps, charts and outcomes remain fixed.
"""
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from ..api.schemas import AnalysisRequest, AnalysisResult

FIXTURE_DIRECTORY = Path(__file__).with_name('fixtures')
FIXTURE_FILES = {'eth_scam': 'eth_scam.json', 'token_scam': 'token_scam.json', 'forecast': 'forecast.json'}
ADDRESS_PATTERN = re.compile(r'^0x[0-9a-f]{40}$')


def digest(value: str) -> str:
    return '0x' + hashlib.sha256(value.encode()).hexdigest()


def iso(value: datetime) -> str:
    return value.isoformat().replace('+00:00', 'Z')


@lru_cache(maxsize=3)
def _load_fixture(family: str) -> tuple[dict, str]:
    raw = (FIXTURE_DIRECTORY / FIXTURE_FILES[family]).read_bytes()
    fixture = json.loads(raw)
    AnalysisResult.model_validate(fixture['result'])
    return fixture, hashlib.sha256(raw).hexdigest()


ETH_TARGET = _load_fixture('eth_scam')[0]['metadata']['default_target']
TOKEN_TARGET = _load_fixture('token_scam')[0]['metadata']['default_target']
POOL = _load_fixture('token_scam')[0]['metadata']['pools'][0]
def fixture_cutoff(family: str) -> datetime:
    return datetime.fromisoformat(_load_fixture(family)[0]['result']['cutoff'])


CUTOFF = fixture_cutoff('eth_scam')
PROFILES = [{key: _load_fixture(family)[0]['metadata'][key] for key in ('family', 'name', 'pools')}
            | {'target': _load_fixture(family)[0]['metadata']['default_target']}
            for family in FIXTURE_FILES]


def _addresses(value) -> set[str]:
    if isinstance(value, str):
        return {value} if ADDRESS_PATTERN.fullmatch(value) else set()
    if isinstance(value, list):
        return set().union(*(_addresses(item) for item in value))
    if isinstance(value, dict):
        return set().union(*(_addresses(item) for item in value.values()))
    return set()


def _alias(value, mapping: dict[str, str]):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_alias(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: _alias(item, mapping) for key, item in value.items()}
    return value


def build_dataset(request: AnalysisRequest, analysis_id: str) -> dict:
    fixture, fingerprint = _load_fixture(request.family)
    data = deepcopy(fixture)
    original_target = data['metadata']['default_target']
    mapping = {original_target: request.target}
    # Any address also includes addresses already used by a fixture participant.
    # Move that participant's alias so the root never duplicates a graph node.
    addresses = _addresses(data)
    if request.target != original_target and request.target in addresses:
        index = 0
        while True:
            replacement = digest(f'{fingerprint}:{request.target}:participant:{index}')[:42]
            if replacement not in addresses and replacement != request.target:
                break
            index += 1
        mapping[request.target] = replacement
    data = _alias(data, mapping)
    result = data['result']
    # V2 pairs sort addresses numerically. If an address alias reverses that
    # order, swap indexed event fields; asset amounts themselves stay fixed.
    for pool in result['basic_information']['pools']:
        if pool['token0'] < pool['token1']:
            continue
        pool['token0'], pool['token1'] = pool['token1'], pool['token0']
        for row in data['ledger'] + result['transactions']['items']:
            fields = row.get('event_data')
            if row['pool'] != pool['address'] or not fields:
                continue
            for first, second in (('amount0In', 'amount1In'), ('amount0Out', 'amount1Out'),
                                  ('amount0', 'amount1'), ('reserve0', 'reserve1')):
                if first in fields and second in fields:
                    fields[first], fields[second] = fields[second], fields[first]
    result['activity']['scope']['pools'] = deepcopy(result['basic_information']['pools'])
    result['analysis_id'] = analysis_id
    result['target'] = request.target
    result['snapshot_id'] = digest(f'{fingerprint}:{request.target}:snapshot')
    result['graphs'] = {task: result['graphs'][task] for task in request.tasks}
    result['tasks'] = [task for task in result['tasks'] if task['task_id'] in request.tasks]
    for task in result['tasks']:
        graph = result['graphs'][task['task_id']]
        sample_id = digest(f"{fingerprint}:{request.target}:{task['task_id']}:sample")
        graph['sample_id'] = sample_id
        graph['context']['sample_id'] = sample_id
        task['sample_id'] = sample_id
    result = AnalysisResult.model_validate(result).model_dump(mode='json')
    return {'result': result, 'ledger': data['ledger'], 'graph_events': data['graph_events']}
