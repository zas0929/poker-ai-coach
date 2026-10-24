"""Adaptive strategy refinement controls with explicit row/split/process budgets."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from research.benchmark_strategy_abstraction import scenarios,root_diagnostic
from research.benchmark_expanded import run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.custom_river import RiverGame
from research.adaptive_strategy import train_adaptive


def worker(case,iterations):
    def phase(name):print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    phase('build');game=RiverGame(**{**case['input'],'utility_storage':'compact'})
    phase('baseline');baseline=game.train(iterations,method='cfr_plus_native');base=game.measure(baseline)
    phase('adaptive');start=time.perf_counter()
    limit=len(game.keys) if case['row_budget']=='full' else max(1,len(game.keys)*3//4)
    policy,evidence=train_adaptive(game,iterations=iterations,max_splits=12,max_groups_per_seat=8,max_strategy_rows=limit)
    return {'status':'completed','baseline_metrics':base,'baseline_quality_passed':base['max_unilateral_gain_pct_pot']<=.5,
        'adaptive':evidence,'root_diagnostic':root_diagnostic(game,baseline,policy) if policy is not None else None,
        'adaptive_seconds':time.perf_counter()-start,'joint_deals':len(game.deals),'public_nodes':len(game.nodes),
        'peak_rss_mib':peak_rss_mib()}


def benchmark(iterations):
    rows=[]
    for case in scenarios():
        for budget in ('compact','full') if case['name'] in ('dry_2_17','dry_3_73','flush_3_31') else ('compact',):
            case={**case,'row_budget':budget};print(case['name']+'/'+budget,file=sys.stderr,flush=True)
            rows.append({'case':case,**run_guarded(case,iterations,45,128,method='cfr_plus_native',worker_module='research.benchmark_adaptive_strategy')})
    eligible=[r for r in rows if r['status']=='completed' and r['baseline_quality_passed']]
    summary={}
    for budget in ('compact','full'):
        selected=[r for r in eligible if r['case']['row_budget']==budget]
        ready=[r for r in selected if r['adaptive']['status']=='ready']
        summary[budget]={'eligible':len(selected),'ready':len(ready),
            'ready_with_actual_compression':sum(r['adaptive']['history'][-1]['grouped_strategy_rows']<r['adaptive']['original_strategy_rows'] for r in ready),
            'reasons':{reason:sum(r['adaptive']['reason']==reason for r in selected) for reason in sorted({r['adaptive']['reason'] for r in selected})}}
    return {'iterations_per_round':iterations,'limits':{'wall_seconds':45,'memory_mib':128},
        'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('adaptive_strategy.py','benchmark_adaptive_strategy.py','strategy_abstraction.py','benchmark_strategy_abstraction.py','custom_river.py')},
        'scope':'30 compact 75%-row controls plus full-row-budget checks on three previously selected failures. Synthetic full small ranges only; no live advice or wide-range solver claim.',
        'summary':summary,'results':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true');p.add_argument('--iterations',type=int,default=100)
    p.add_argument('--method',choices=['cfr_plus_native'],default='cfr_plus_native');args=p.parse_args()
    if not 1<=args.iterations<=2000:p.error('1–2000 iterations required.')
    print(json.dumps(worker(json.load(sys.stdin),args.iterations) if args.worker else benchmark(args.iterations),indent=None if args.worker else 2,allow_nan=False))
