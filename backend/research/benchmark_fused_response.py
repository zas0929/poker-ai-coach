"""Paired numerical/evaluation timing controls for fused exact BR traversal."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys
import time
from research.custom_river import RiverGame
from research.adaptive_strategy import action_values,train_adaptive
from research.adaptive_strategy_fast import train_adaptive_fast
from research.fused_best_response import evaluate_policy
from research.benchmark_strategy_abstraction import scenarios as development
from research.benchmark_expanded import run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.validate_adaptive_strategy import load_manifest
from research.native_cfr import load_library


def digest(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def reference(game,policy):return game.measure(policy),action_values(game,policy)


class CountUtilities:
    def __init__(self,base):self.base=base;self.reads=0
    def __getitem__(self,key):self.reads+=1;return self.base[key]


def worker(job,iterations):
    def phase(name):print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    phase('build');game=RiverGame(**{**job['case']['input'],'utility_storage':'compact'})
    if job['kind']=='evaluation':
        policy={key:[1./count]*count for key,count in game.action_counts.items()}
        times={'reference':[],'fused':[]};equivalent=True
        phase('paired_evaluation')
        for repeat in range(3):
            values={}
            for name in ('reference','fused') if repeat%2==0 else ('fused','reference'):
                start=time.perf_counter();values[name]=(reference if name=='reference' else evaluate_policy)(game,policy)
                times[name].append(time.perf_counter()-start)
            equivalent=equivalent and values['reference']==values['fused']
        reads={};base=game.utilities
        try:
            for name,fn in [('reference',reference),('fused',evaluate_policy)]:
                wrapped=CountUtilities(base);game.utilities=wrapped;fn(game,policy);reads[name]=wrapped.reads
        finally:game.utilities=base
        medians={k:statistics.median(v) for k,v in times.items()}
        return {'status':'completed','equivalent':equivalent,'seconds':times,'median_seconds':medians,
            'median_speedup':medians['reference']/medians['fused'],'utility_reads':reads,
            'strategy_rows':len(game.keys),'public_nodes':len(game.nodes),'joint_deals':len(game.deals),'peak_rss_mib':peak_rss_mib()}
    phase('warm_native');load_library()
    phase(job['method']);start=time.perf_counter()
    fn=train_adaptive if job['method']=='reference' else train_adaptive_fast
    policy,evidence=fn(game,iterations=iterations,max_strategy_rows=max(1,len(game.keys)*3//4))
    seconds=time.perf_counter()-start
    policy_hash=digest(sorted((key,row) for key,row in policy.items())) if policy is not None else digest(None)
    return {'status':'completed','adaptive_seconds':seconds,'evidence':evidence,'policy_sha256':policy_hash,
            'evidence_sha256':digest(evidence),'public_nodes':len(game.nodes),'joint_deals':len(game.deals),'peak_rss_mib':peak_rss_mib()}


def compare_pair(results):
    a,b=results['reference'],results['fused']
    complete=a['status']=='completed' and b['status']=='completed'
    return {'both_completed':complete,
        'exact_policy_and_trace_match':a['policy_sha256']==b['policy_sha256'] and a['evidence_sha256']==b['evidence_sha256'] if complete else None,
        'speedup':a['adaptive_seconds']/b['adaptive_seconds'] if complete else None,
        'scope':'One isolated run per method; build/startup excluded, native loader warmed. Timing is descriptive only.'}


def benchmark():
    frozen=Path(__file__).parents[2]/'docs/research/adaptive-validation-manifest-2026-10-24.json'
    plan=load_manifest(frozen);held={c['name']:c for c in plan['cases']}
    dev={c['name']:c for c in development()}
    micro=[dev['dry_2_17'],dev['flush_3_31'],held['folded_6_101'],held['sizing_6_101'],held['prior_sidepot_6_101'],held['short_raises_6_101']]
    full=[dev['dry_2_17'],dev['dry_3_73'],held['sizing_6_101'],held['prior_sidepot_6_101'],held['short_raises_6_101'],held['short_raises_6_211']]
    evaluations=[];adaptive=[]
    for case in micro:
        print('Evaluation '+case['name'],file=sys.stderr,flush=True)
        evaluations.append({'case':case,**run_guarded({'kind':'evaluation','case':case},100,45,128,method='cfr_plus_native',worker_module='research.benchmark_fused_response')})
    for i,case in enumerate(full):
        results={};order=('reference','fused') if i%2==0 else ('fused','reference')
        for method in order:
            print('Adaptive '+case['name']+'/'+method,file=sys.stderr,flush=True)
            results[method]=run_guarded({'kind':'adaptive','case':case,'method':method},100,45,128,method='cfr_plus_native',worker_module='research.benchmark_fused_response')
        adaptive.append({'case':case,'execution_order':order,'methods':results,'comparison':compare_pair(results)})
    return {'iterations_per_round':100,'limits':{'wall_seconds':45,'memory_mib':128},
        'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('fused_best_response.py','adaptive_strategy_fast.py','adaptive_strategy.py','benchmark_fused_response.py','custom_river.py')},
        'scope':'Exact original-game evaluation optimization only; same quality/row/split limits. Old reference and frozen holdout remain unchanged. No live advice integration.',
        'evaluations':evaluations,'adaptive_pairs':adaptive}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true');p.add_argument('--iterations',type=int,default=100)
    p.add_argument('--method',choices=['cfr_plus_native'],default='cfr_plus_native');args=p.parse_args()
    print(json.dumps(worker(json.load(sys.stdin),args.iterations) if args.worker else benchmark(),indent=None if args.worker else 2,allow_nan=False))
