"""Isolated tree-free exact compression audit on public river range supports."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import random
import sys
import time
from research.benchmark_snapshot import control
from research.benchmark_expanded import run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.wide_range_audit import audit_ranges

BOARDS={'dry':['2c','4d','7h','9s','Jc'],'flush':['2s','5s','9s','Kh','Ad'],
        'paired':['2c','2d','7h','9s','Jc'],'royal':['Ts','Js','Qs','Ks','As']}


def scenarios():
    for texture,board in BOARDS.items():
        for n in range(2,7):
            snapshot=control(n,board=board)
            yield {'name':texture+'_full_'+str(n),'board':board,
                   'ranges':[[(r['cards'],r['weight']) for r in p['range']] for p in snapshot['players']],
                   'public_snapshot_key':snapshot['information_key'],'source':'entire_public_range'}
    for width in (32,128):
        for n in (2,4,6):
            snapshot=control(n,board=BOARDS['dry']);ranges=[]
            for i,p in enumerate(snapshot['players']):
                rows=sorted(p['range'],key=lambda r:r['cards']);random.Random(20261024+i).shuffle(rows)
                ranges.append([(r['cards'],r['weight']) for r in rows[:width]])
            yield {'name':'dry_sample_'+str(width)+'_'+str(n),'board':BOARDS['dry'],'ranges':ranges,
                   'source':'seeded_public_subset','seed':20261024,'public_snapshot_key':snapshot['information_key']}
    yield {'name':'positive_equivalent_6','board':BOARDS['dry'],
           'ranges':[[(r+'h'+r+'d',1.),(r+'c'+r+'s',3.)] for r in 'AKQT86'],
           'source':'deliberately_equivalent_positive_control'}


def worker(case):
    print(json.dumps({'phase':'audit','observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    start=time.perf_counter();result=audit_ranges(case['board'],case['ranges'])
    result.pop('groups')
    return {**result,'audit_seconds':time.perf_counter()-start,'peak_rss_mib':peak_rss_mib()}


def benchmark():
    rows=[]
    for case in scenarios():
        print(case['name'],file=sys.stderr,flush=True)
        result=run_guarded(case,1,45,128,worker_module='research.benchmark_wide_ranges')
        rows.append({'case':{k:v for k,v in case.items() if k!='ranges'},
                     'range_source_sha256':sha256(json.dumps(case['ranges'],sort_keys=True).encode()).hexdigest(),**result})
    return {'scope':'27 tree-free audits; four boards, 2–6 seats with whole public supports; sampled and positive controls. No solver run or live-advice admission.',
        'limits':{'wall_seconds':45,'memory_mib':128,'max_pair_checks':36000000,'max_hands_per_live_seat':1081},
        'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('wide_range_audit.py','benchmark_wide_ranges.py','benchmark_snapshot.py')},
        'all_audited':all(r.get('status')=='audited' for r in rows),'results':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true')
    p.add_argument('--iterations',type=int,default=1);p.add_argument('--method',default='cfr_plus_indexed')
    args=p.parse_args();print(json.dumps(worker(json.load(sys.stdin)) if args.worker else benchmark(),indent=None if args.worker else 2,allow_nan=False))
