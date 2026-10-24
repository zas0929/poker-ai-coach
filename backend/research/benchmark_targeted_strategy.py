"""Paired regression, not independent validation, of gain-targeted refinement."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from research.custom_river import RiverGame
from research.adaptive_strategy_indexed import train_adaptive_indexed
from research.adaptive_strategy_targeted import train_adaptive_targeted
from research.benchmark_expanded import run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.validate_adaptive_strategy import load_manifest


def worker(job):
    def phase(name):print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    phase('build');game=RiverGame(**{**job['case']['input'],'utility_storage':'compact'})
    phase(job['method']);start=time.perf_counter()
    fn=train_adaptive_indexed if job['method']=='reference' else train_adaptive_targeted
    policy,evidence=fn(game,iterations=100,max_strategy_rows=len(game.keys)*3//4)
    return {'status':'completed','seconds':time.perf_counter()-start,'evidence':evidence,'peak_rss_mib':peak_rss_mib()}


def summarize(rows):
    def group(subset):
        paired=[r for r in subset if all(v['status']=='completed' for v in r['methods'].values())]
        a=lambda r,m:r['methods'][m]['evidence']['status']=='ready'
        return {'attempted':len(subset),'both_completed':len(paired),
            'process_statuses':{m:dict(Counter(r['methods'][m]['status'] for r in subset)) for m in ('reference','targeted')},
            'reference_ready':sum(a(r,'reference') for r in paired),'targeted_ready':sum(a(r,'targeted') for r in paired),
            'improved':sum(not a(r,'reference') and a(r,'targeted') for r in paired),
            'regressed':sum(a(r,'reference') and not a(r,'targeted') for r in paired)}
    return {'overall':group(rows),'by_live_players':{str(n):group([r for r in rows if r['case']['live_players']==n]) for n in range(2,7)}}


def benchmark():
    path=Path(__file__).parents[2]/'docs/research/adaptive-validation-manifest-2026-10-24.json'
    plan=load_manifest(path);rows=[]
    for i,case in enumerate(plan['cases']):
        results={}
        for method in ('reference','targeted') if i%2==0 else ('targeted','reference'):
            print(case['name']+'/'+method,file=sys.stderr,flush=True)
            results[method]=run_guarded({'case':case,'method':method},100,45,128,method='cfr_plus_native',worker_module='research.benchmark_targeted_strategy')
        rows.append({'case':case,'methods':results})
    load_manifest(path)
    return {'scope':'Known 46-case regression corpus, not independent validation. Same 100 iterations, 75% row budget, 12 splits, 8 groups/seat and 0.5% gate. No live advice.',
        'limits':{'wall_seconds':45,'memory_mib':128},'parent_manifest_sha256':plan['manifest_sha256'],
        'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('targeted_strategy.py','adaptive_strategy_targeted.py','adaptive_strategy_indexed.py','indexed_split.py','benchmark_targeted_strategy.py')},
        'summary':summarize(rows),'results':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true');p.add_argument('--iterations',type=int,default=100);p.add_argument('--method',default='cfr_plus_native');args=p.parse_args()
    print(json.dumps(worker(json.load(sys.stdin)) if args.worker else benchmark(),indent=None if args.worker else 2,allow_nan=False))
