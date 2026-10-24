"""First-week facts and a bounded wallet--pool--token display graph."""
import hashlib
import json

from packages.transactions import address
from ..adapters.analysis_store import utc
from .token_presentation import basic_information as token_information


def basic_information(context, metrics=None):
    facts = token_information(context, metrics)
    resolved = context.get('forecast_window_resolved', False)
    for field in facts['fields']:
        if field['key'] == 'window':
            field['value'] = f"{utc(context['window_start'])} → {utc(context['cutoff'])}" if resolved else 'Resolving first 7 days'
            field['hint'] = 'From the earliest selected-pool creation through the fixed seven-day cutoff.'
        elif field['key'] in ('transfers','participants','swap','mint','burn'):
            field['hint'] = 'Observed first-week records collected so far; participants are addresses, not a holder count.'
    if context.get('state_timestamp') is not None:
        facts['state_time'] = utc(context['state_timestamp'])
    return facts


class ForecastDisplay:
    def __init__(self, context):
        self.context = context
        self.groups = {}
        self.wallets = set()
        self.locked = False

    def observe(self, events):
        pools = set(self.context.get('pools', []))
        for event in sorted(events, key=lambda e:(e['timestamp'],e['block_number'],e.get('log_index',-1)), reverse=True):
            if event['relation'] != 'swap' or event.get('pool') not in pools:
                continue
            sender = address(event.get('event_sender'))
            # Only the actual event sender creates a wallet-pool link.
            if not sender or sender == self.context['target'] or sender in pools:
                continue
            if sender not in self.wallets:
                if len(self.wallets) >= 16:
                    continue
                self.wallets.add(sender)
            key = sender, event['pool']
            if key not in self.groups:
                self.groups[key] = {'source': sender, 'target': event['pool'], 'relation': 'swap_activity',
                    'kind': 'observed', 'direction': 'original', 'event_count': 0, 'amount': None, 'asset': None,
                    'first_seen': utc(event['timestamp']), 'last_seen': utc(event['timestamp'])}
            group = self.groups[key]
            group['event_count'] += 1
            group['first_seen'] = min(group['first_seen'],utc(event['timestamp']))
            group['last_seen'] = max(group['last_seen'],utc(event['timestamp']))

    def payload(self):
        return {'wallets': sorted(self.wallets), 'groups': list(self.groups.values())}

    @classmethod
    def restore(cls, context, payload):
        graph = cls(context)
        graph.wallets = set(payload['wallets'])
        graph.groups = {(row['source'],row['target']):row for row in payload['groups']}
        return graph

    def views(self):
        context = self.context
        root, selected = context['target'], context['pools']
        nodes = [{'id':root,'ref':root,'role':'token','label':context.get('name'),'is_root':True,'hop':0,'individually_assessed':True}]
        nodes += [{'id':p,'ref':p,'role':'pool','is_root':False,'hop':1,'individually_assessed':False} for p in selected]
        nodes += [{'id':w,'ref':w,'role':'wallet','is_root':False,'hop':2,'individually_assessed':False} for w in sorted(self.wallets)]
        edges = [{'source':p,'target':root,'relation':'contains_token','kind':'structural','direction':'original',
                  'event_count':1,'amount':None,'asset':None,'first_seen':utc(context['forecast_pool_creations'][p]['timestamp']),
                  'last_seen':utc(context['cutoff'])} for p in selected] + list(self.groups.values())
        edges = [{**row,'id':hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()} for row in edges]
        sample = hashlib.sha256(f"{context['snapshot_id']}:forecast-display-1".encode()).hexdigest()
        return {'continued_activity': {'sample_id':sample,'task_id':'continued_activity','nodes':nodes,'edges':edges,
            'context':{'sample_id':sample,'task_id':'continued_activity','model_nodes':None,'model_edges':None,
                'window':f"{utc(context['window_start'])} → {utc(context['cutoff'])}",'cutoff':utc(context['cutoff']),
                'version':'forecast-wallet-display-1','sampling':'Verified selected pools and observed first-week Swap.sender; at most 16 second-hop participants',
                'view_scope':'display_first_week'}}}
