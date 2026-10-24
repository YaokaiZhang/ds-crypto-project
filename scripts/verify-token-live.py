"""Submit/read local mainnet acceptance jobs; never prints provider credentials."""
import argparse
import json
from pathlib import Path
import sqlite3
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TOKENS = {'GNO':'0x6810e776880c02933d47db1b9fc05908e5386b96',
          'RAI':'0x03ab458634910aad20ef5f1c8ee96f1d6ac54919',
          'LQTY':'0x6dea81c8171d0ba574754ef6f8b412f2ed88c54d'}
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--submit',action='store_true')
args=parser.parse_args()
report=ROOT/'reports/serving/token-live-smoke.json'
records=json.loads(report.read_text()) if report.exists() else {}
db=sqlite3.connect(ROOT/'.runtime/eth-analysis.sqlite3')
for name,token in TOKENS.items():
    if name not in records:
        existing=None
        if name=='GNO':
            for row in db.execute('SELECT id,result FROM jobs ORDER BY created DESC'):
                result=json.loads(row[1])
                if result['target']==token and result['family']=='token_scam': existing=result; break
        if existing:
            records[name]={'target':token,'analysis_id':existing['analysis_id']}
        elif args.submit:
            request=Request('http://127.0.0.1:8000/api/v1/analyses',data=json.dumps({'target':token,'family':'token_scam'}).encode(),
                headers={'Content-Type':'application/json','Idempotency-Key':'token-mainnet-acceptance-1:'+token})
            with urlopen(request,timeout=20) as response: created=json.load(response)
            records[name]={'target':token,'analysis_id':created['analysis_id']}
    record=records.get(name)
    if not record: continue
    row=db.execute('SELECT result FROM jobs WHERE id=?',(record['analysis_id'],)).fetchone()
    result=json.loads(row[0])
    record.update(status=result['status'],stage=result['stage'],progress=result.get('progress'),message=result.get('message'),
        cutoff=result.get('cutoff'),window_start=result.get('window_start'),basic_information=result.get('basic_information'),tasks=result['tasks'])
    record['ledger']={r[0]:r[1] for r in db.execute('SELECT category,COUNT(*) FROM ledger WHERE job=? GROUP BY category',(record['analysis_id'],))}
    record['graphs']={task:{'nodes':len(g['nodes']),'edges':len(g['edges']),
        'first_with_root':sum(n.get('hop') in (0,1) for n in g['nodes']),'second':sum(n.get('hop')==2 for n in g['nodes'])} for task,g in result['graphs'].items()}
    activity=result.get('activity')
    record['activity_complete']=activity['scope']['complete'] if activity else False
    if activity:
        record['daily_counts']={key:sum(p.get(key) or 0 for p in activity['points']) for key in ('transfer_count','swap_count','mint_count','burn_count')}
    record['inputs']={}
    for task in ('honeypot','rug_pull'):
        row=db.execute('SELECT payload FROM artifacts WHERE job=? AND kind=? AND task=?',(record['analysis_id'],'model_delivery',task)).fetchone()
        if row:
            delivery=json.loads(row[0]); payload=json.loads(Path(delivery['input_path']).read_text())
            record['inputs'][task]={'delivery':delivery['delivery'],'sha256':delivery['input_sha256'],
                'model_version':payload['model_version'],'graph_recipe':payload['graph_recipe'],'consumed_inputs':list(payload['inputs']),
                'nodes':len(payload['graph_sample']['node_refs']),'edges':len(payload['graph_sample']['edge_index'][0])}
report.parent.mkdir(parents=True,exist_ok=True)
report.write_text(json.dumps(records,indent=2)+'\n')
for name,record in records.items():
    print(json.dumps({'token':name,**{k:record.get(k) for k in ('analysis_id','status','stage','progress','ledger','graphs','message')}},ensure_ascii=False))
