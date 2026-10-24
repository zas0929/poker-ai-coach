"""Checkpointed fixed-time reallocation. Parent keeps last completed verified trial.
Each model build/evaluation/train runs in an externally bounded child process.
"""
import argparse
import json
from pathlib import Path
import time
from research.custom_river import RiverGame
from research.adaptive_strategy_indexed import train_adaptive_indexed
from research.group_reallocation import recover_mapping,candidates,project_merge,partition_key
from research.strategy_abstraction import StrategyView,lift_policy
from research.fused_best_response import evaluate_policy
from research.targeted_strategy import propose_targeted_split
from research.native_cfr import train_native
from research.benchmark_expanded import run_guarded
from research.benchmark_capacity import peak_rss_mib


def encode(policy):return [[seat,hand,history,row] for (seat,hand,history),row in sorted(policy.items())]


def decode(rows):
    result={(seat,hand,tuple(tuple(a) for a in history)):probs for seat,hand,history,probs in rows}
    if len(result)!=len(rows):raise ValueError('Duplicate policy rows.')
    return result


def better(a,b):
    x=a['metrics']['max_unilateral_gain_pct_pot'];y=b['metrics']['max_unilateral_gain_pct_pot']
    return x<y-1e-10 or abs(x-y)<=1e-10 and a['rows']<b['rows']


def checkpoint(game,mapping,policy,metrics):
    return {'mapping':mapping,'policy':encode(policy),'metrics':metrics,
            'rows':len(StrategyView(game,mapping).keys)}


def worker(job):
    def phase(name):print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    phase('build');game=RiverGame(**{**job['case']['input'],'utility_storage':'compact'})
    if job['kind']=='baseline':
        phase('baseline');policy,e=train_adaptive_indexed(game,max_strategy_rows=len(game.keys)*3//4)
        cp=checkpoint(game,recover_mapping(game,e),policy,e['metrics_original_game']) if policy is not None else None
        return {'status':'completed','checkpoint':cp,'baseline_evidence':e,'peak_rss_mib':peak_rss_mib()}
    phase('validate_checkpoint');cp=job['checkpoint'];policy=decode(cp['policy']);metrics,_=evaluate_policy(game,policy)
    if metrics!=cp['metrics'] or len(StrategyView(game,cp['mapping']).keys)!=cp['rows']:raise ValueError('Invalid checkpoint.')
    mapping=cp['mapping'];ranked=[c for c in candidates(game,mapping,policy) if c['max_tv']<=.1]
    if job['candidate_index']>=len(ranked):return {'status':'completed','outcome':'no_candidate','checkpoint':None,'peak_rss_mib':peak_rss_mib()}
    selected=ranked[job['candidate_index']];phase('merge');merged,projected=project_merge(game,mapping,policy,selected)
    merged_metrics,records=evaluate_policy(game,projected)
    if merged_metrics['max_unilateral_gain_pct_pot']>metrics['max_unilateral_gain_pct_pot']+1e-10:
        return {'status':'completed','outcome':'merge_regression','candidate':selected,'checkpoint':None,'peak_rss_mib':peak_rss_mib()}
    best=checkpoint(game,merged,projected,merged_metrics);outcome='merge_only'
    proposal=propose_targeted_split(game,merged,records,8,job['row_limit'],merged_metrics)
    if proposal is not None and partition_key(proposal['mapping'])!=partition_key(mapping):
        phase('retrain');updated=proposal['mapping'];view=StrategyView(game,updated)
        trained=train_native(view,100);lifted=lift_policy(game,view,trained);after,_=evaluate_policy(game,lifted)
        trial=checkpoint(game,updated,lifted,after)
        if better(trial,best):best=trial;outcome='reallocated'
    if best['rows']>job['row_limit']:raise ValueError('Row cap exceeded.')
    return {'status':'completed','outcome':outcome,'candidate':selected,
            'checkpoint':best if better(best,cp) else None,'peak_rss_mib':peak_rss_mib()}


def run_cycle(case,*,total_seconds=45,memory_mib=128,max_cycles=2,max_candidates=2,_runner=run_guarded,_clock=time.perf_counter):
    if type(total_seconds) not in (int,float) or not 0<total_seconds<=45 or type(memory_mib) not in (int,float) or not 0<memory_mib<=128:
        raise ValueError('Positive time <=45s and RSS <=128 MiB required.')
    if type(max_cycles) is not int or not 0<=max_cycles<=2 or type(max_candidates) is not int or not 1<=max_candidates<=2:
        raise ValueError('At most two cycles and two candidates per cycle required.')
    started=_clock();baseline=_runner({'kind':'baseline','case':case},100,total_seconds,memory_mib,
                                      method='cfr_plus_native',worker_module='research.reallocation_cycle')
    result={'baseline':baseline,'attempts':[],'live_advice_allowed':False,
            'limits':{'total_seconds':total_seconds,'memory_mib':memory_mib,'max_cycles':max_cycles,'max_candidates':max_candidates}}
    if baseline['status']!='completed' or baseline.get('checkpoint') is None:
        return {**result,'status':'unavailable','reason':'baseline_unavailable','elapsed_seconds':_clock()-started}
    best=baseline['checkpoint'];seen={partition_key(best['mapping'])};reason='cycle_budget'
    row_limit=baseline['baseline_evidence']['limits']['max_strategy_rows']
    for cycle in range(max_cycles):
        if best['metrics']['max_unilateral_gain_pct_pot']<=.5:reason='quality_passed';break
        improved=False
        for index in range(max_candidates):
            remaining=total_seconds-(_clock()-started)
            # Reserve return/serialization time; never discard a completed baseline.
            if remaining<=.5:reason='time_budget';break
            trial=_runner({'kind':'trial','case':case,'checkpoint':best,'candidate_index':index,'row_limit':row_limit},
                          100,remaining-.5,memory_mib,method='cfr_plus_native',worker_module='research.reallocation_cycle')
            entry={'cycle':cycle,'candidate_index':index,**trial};result['attempts'].append(entry)
            if trial['status']!='completed':reason='trial_'+trial['status'];break
            candidate=trial.get('checkpoint')
            if candidate is not None:
                if candidate['rows']>row_limit:raise ValueError('Checkpoint exceeds row limit.')
                key=partition_key(candidate['mapping'])
                if key not in seen and better(candidate,best):
                    best=candidate;seen.add(key);improved=True;entry['accepted']=True;break
            entry['accepted']=False
            if trial.get('outcome')=='no_candidate':break
        if not improved:
            if reason=='cycle_budget':reason='no_improvement'
            break
    ready=best['metrics']['max_unilateral_gain_pct_pot']<=.5
    return {**result,'status':'ready' if ready else 'rejected','reason':'quality_passed' if ready else reason,
            'best_checkpoint':best,'elapsed_seconds':_clock()-started}


if __name__=='__main__':
    import sys
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true');p.add_argument('--iterations',type=int,default=100);p.add_argument('--method',default='cfr_plus_native');p.parse_args()
    print(json.dumps(worker(json.load(sys.stdin)),allow_nan=False))
