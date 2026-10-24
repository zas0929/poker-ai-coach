"""Paired split-selection and adaptive-path timing with exact trace hashes."""
import argparse
import cProfile
from hashlib import sha256
import json
from pathlib import Path
import pstats
import sys
import time
from research.custom_river import RiverGame
from research.strategy_abstraction import hand_groups
from research.fused_best_response import evaluate_policy
from research.adaptive_strategy import propose_split
from research.indexed_split import propose_split_indexed
from research.adaptive_strategy_fast import train_adaptive_fast
from research.adaptive_strategy_indexed import train_adaptive_indexed
from research.benchmark_expanded import run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.benchmark_strategy_abstraction import scenarios
from research.validate_adaptive_strategy import load_manifest
from research.native_cfr import load_library


def digest(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def worker(job):
    def phase(name):print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    phase('build');game=RiverGame(**{**job['case']['input'],'utility_storage':'compact'})
    if job['kind']=='selector':
        phase('prepare');policy={k:[1./c]*c for k,c in game.action_counts.items()}
        _,records=evaluate_policy(game,policy);mapping=hand_groups(game,'equity_2')
        outputs={};seconds={}
        for method,fn in [('reference',propose_split),('indexed',propose_split_indexed)]:
            phase(method);start=time.perf_counter();outputs[method]=fn(game,mapping,records,8,len(game.keys)*3//4);seconds[method]=time.perf_counter()-start
        profiler=cProfile.Profile();profiler.runcall(propose_split,game,mapping,records,8,len(game.keys)*3//4)
        stats=pstats.Stats(profiler).stats
        view_calls=sum(row[1] for (path,line,name),row in stats.items() if path.endswith('strategy_abstraction.py') and name=='__init__')
        return {'status':'completed','equivalent':outputs['reference']==outputs['indexed'],'seconds':seconds,
                'speedup':seconds['reference']/seconds['indexed'],'profile_reference_strategy_view_calls':view_calls,'peak_rss_mib':peak_rss_mib()}
    phase('warm');load_library();phase(job['method']);start=time.perf_counter()
    fn=train_adaptive_fast if job['method']=='reference' else train_adaptive_indexed
    policy,evidence=fn(game,iterations=100,max_strategy_rows=len(game.keys)*3//4)
    return {'status':'completed','seconds':time.perf_counter()-start,'evidence':evidence,
        'policy_sha256':digest(sorted(policy.items())) if policy else digest(None),'evidence_sha256':digest(evidence),'peak_rss_mib':peak_rss_mib()}


def benchmark():
    plan=load_manifest(Path(__file__).parents[2]/'docs/research/adaptive-validation-manifest-2026-10-24.json')
    held={c['name']:c for c in plan['cases']};dev={c['name']:c for c in scenarios()}
    cases=[dev['dry_2_17'],held['sizing_6_101'],held['short_raises_6_101'],held['short_raises_6_211']]
    selectors=[];pairs=[]
    for case in cases[:3]:
        print('Selector '+case['name'],file=sys.stderr,flush=True)
        selectors.append({'case':case,**run_guarded({'kind':'selector','case':case},100,45,128,method='cfr_plus_native',worker_module='research.benchmark_indexed_split')})
    for i,case in enumerate(cases):
        results={};order=('reference','indexed') if i%2==0 else ('indexed','reference')
        for method in order:
            print(case['name']+'/'+method,file=sys.stderr,flush=True)
            results[method]=run_guarded({'kind':'adaptive','case':case,'method':method},100,45,128,method='cfr_plus_native',worker_module='research.benchmark_indexed_split')
        a,b=results['reference'],results['indexed'];both=a['status']==b['status']=='completed'
        pairs.append({'case':case,'order':order,'methods':results,'both_completed':both,
            'exact_match':a['policy_sha256']==b['policy_sha256'] and a['evidence_sha256']==b['evidence_sha256'] if both else None,
            'speedup':a['seconds']/b['seconds'] if both else None})
    return {'limits':{'wall_seconds':45,'memory_mib':128},'iterations_per_round':100,
        'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('indexed_split.py','adaptive_strategy_indexed.py','adaptive_strategy_fast.py','adaptive_strategy.py','benchmark_indexed_split.py')},
        'scope':'Reference already uses fused BR. Same Q arithmetic, tie order, quality and row budgets. Single paired timing per case; profile excluded from selector timing. No live advice.',
        'selectors':selectors,'adaptive_pairs':pairs}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true');p.add_argument('--iterations',type=int,default=100)
    p.add_argument('--method',default='cfr_plus_native');args=p.parse_args()
    print(json.dumps(worker(json.load(sys.stdin)) if args.worker else benchmark(),indent=None if args.worker else 2,allow_nan=False))
