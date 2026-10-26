"""Explicit mainnet acceptance report; --submit opts into provider-consuming jobs."""
import argparse
import json
from pathlib import Path
import sqlite3
from urllib.request import Request,urlopen

PROJECT=Path(__file__).resolve().parents[2]
TOKENS={'GNO':'0x6810e776880c02933d47db1b9fc05908e5386b96',
        'RAI':'0x03ab458634910aad20ef5f1c8ee96f1d6ac54919',
        'LQTY':'0x6dea81c8171d0ba574754ef6f8b412f2ed88c54d'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family',choices=('token_scam','forecast'),required=True)
    parser.add_argument('--submit',action='store_true')
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--database',type=Path,default=PROJECT/'.runtime/eth-analysis.sqlite3')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    report=args.report or PROJECT/f'checks/.runtime/{args.family}-acceptance.json'
    records=json.loads(report.read_text()) if report.exists() else {}
    # Read-only mode cannot accidentally create an empty analysis database.
    with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        for name,target in TOKENS.items():
            if name not in records:
                existing=next((json.loads(row[0]) for row in db.execute('SELECT result FROM jobs ORDER BY created DESC')
                    if json.loads(row[0])['target']==target and json.loads(row[0])['family']==args.family
                    and json.loads(row[0]).get('result_origin')=='chain_data_model_scores'),None)
                if existing:
                    records[name]={'target':target,'analysis_id':existing['analysis_id']}
                elif args.submit:
                    request=Request(args.url.rstrip('/')+'/api/v1/analyses',data=json.dumps({'target':target,'family':args.family}).encode(),
                        headers={'Content-Type':'application/json','Idempotency-Key':'mainnet-regression-1:'+args.family+':'+target})
                    with urlopen(request,timeout=30) as response:created=json.load(response)
                    records[name]={'target':target,'analysis_id':created['analysis_id']}
            if name not in records:continue
            record=records[name]
            row=db.execute('SELECT result FROM jobs WHERE id=?',(record['analysis_id'],)).fetchone()
            if row is None:continue
            result=json.loads(row[0])
            record.update({key:result.get(key) for key in ('status','stage','progress','message','cutoff','window_start','basic_information','tasks','result_origin')})
            record['ledger']={r[0]:r[1] for r in db.execute('SELECT category,COUNT(*) FROM ledger WHERE job=? GROUP BY category',(record['analysis_id'],))}
            record['graphs']={task:{'nodes':len(g['nodes']),'edges':len(g['edges']),
                'first_with_root':sum(n.get('hop') in (0,1) for n in g['nodes']),'second':sum(n.get('hop')==2 for n in g['nodes'])}
                for task,g in result['graphs'].items()}
            activity=result.get('activity');record['activity_complete']=bool(activity and activity['scope']['complete'])
            if activity:record['daily_counts']={key:sum(p.get(key) or 0 for p in activity['points'])
                for key in ('transfer_count','swap_count','mint_count','burn_count')}
            record['inputs']={}
            for task in ('continued_activity',) if args.family=='forecast' else ('honeypot','rug_pull'):
                saved=db.execute('SELECT payload FROM artifacts WHERE job=? AND kind=? AND task=?',
                    (record['analysis_id'],'model_delivery',task)).fetchone()
                if saved:
                    delivery=json.loads(saved[0]);payload=json.loads(Path(delivery['input_path']).read_text());graph=payload['graph_sample']
                    record['inputs'][task]={'delivery':delivery['delivery'],'sha256':delivery['input_sha256'],
                        'model_version':payload['model_version'],'nodes':len(graph['node_refs']),'edges':len(graph['edge_index'][0])}
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(records,indent=2)+'\n')
    for name,record in records.items():
        print(json.dumps({'token':name,**{k:record.get(k) for k in ('analysis_id','status','stage','progress','ledger','graphs','message')}}))


if __name__=='__main__':main()
