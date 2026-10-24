"""Label-free adapter to the existing Task A wallet graph builder."""
from scripts.build_wallet_graph import aggregate_wallet_edges, wallet_graph_for_target, validate_graph
from ..adapters.analysis_store import utc
from ..errors import ServiceError
from .token_window import TokenWindow
from .forecast_presentation import ForecastDisplay, basic_information


class ForecastWindow(TokenWindow):
    graph_class = ForecastDisplay
    information = staticmethod(basic_information)
    family = 'forecast'
    policy = 'forecast-first7-1'


def prepare_input(context, ledger, sample_id):
    pools = [{'pool_address':p['pool'],'protocol':'uniswap_v2','token0':p['token0'],'token1':p['token1'],
              'creation_timestamp':utc(context['forecast_pool_creations'][p['pool']]['timestamp'])} for p in context['pool_metadata']]
    events = []
    for row in ledger:
        if row['event'] not in ('Swap','Mint','Burn'):
            continue
        if not utc(context['t0']) <= row['block_time'] <= utc(context['cutoff']) or row['pool'] not in context['pools']:
            raise ServiceError('data_incomplete')
        data = row.get('event_data') or {}
        events.append({'token_address':context['target'],'source_dataset':'ethereum-mainnet-forecast-v1',
            'event_type':row['event'].lower(),'protocol':'uniswap_v2','pool_address':row['pool'],
            'event_id':row['id'],'block_timestamp':row['block_time'],'block_number':row['block_number'],
            'swap_sender':data.get('swap_sender'),'swap_recipient':data.get('swap_recipient'),
            'transaction_from':None,'amount_usd':None})
    counts = {name:sum(e['event_type']==name for e in events) for name in ('swap','mint','burn')}
    target = {'token_address':context['target'],'source_dataset':'ethereum-mainnet-forecast-v1',
        'partition':'inference','graph_role':'first_week','t0':utc(context['t0']),'cutoff':utc(context['cutoff']),
        'event_count':len(events),'swap_count':counts['swap'],'mint_count':counts['mint'],'burn_count':counts['burn'],
        'pre_cutoff_volume_usd':None,'active_day_count':len({e['block_timestamp'][:10] for e in events})}
    edges, quality = aggregate_wallet_edges(target,events,pools,pool_scope_complete=True)
    quality.update(observation_complete=context['observation_complete'], historical_usd='unavailable',
                   transaction_from='unavailable', selected_pool_scope='canonical_uniswap_v2')
    if not quality['model_ready']:
        return None, quality
    graph = wallet_graph_for_target(target,pools,edges,events)
    # Inference must never inherit a label or training partition from research.
    graph.pop('label',None)
    validate_graph(graph)
    return {'protocol_version':'forecast-wallet-observations-1','task_id':'continued_activity',
        'sample_id':sample_id,'target':context['target'],'chain_id':1,'cutoff':utc(context['cutoff']),
        'cutoff_block':context['cutoff_block'],'cutoff_block_hash':context['cutoff_hash'],
        'window_start':utc(context['t0']),'model_version':'forecast-wallet-graph-mock-v1',
        'preprocessing':'unscaled; awaiting Forecast deployment manifest and training-fitted scaler',
        'historical_usd':'unavailable; no current-price substitution','quality':quality,
        'inputs':{'node_features':graph['node_features'],'edge_index':graph['edge_index'],'root_index':0},
        'graph_sample':graph},quality
