"""Frozen synthetic validation of the checkpointed cycle; no outcome-driven edits."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from research.benchmark_expanded import make_case,run_guarded
from research.reallocation_cycle import run_cycle
from research.benchmark_reallocation_cycle import summarize
from research.validate_adaptive_strategy import digest,load_manifest as load_old_manifest

FROZEN_CYCLE_SHA='dc356b181b50c9e6557ba7fe903a590301a0157b1b99957adb1d855fbff9ae07'
SOURCES=('reallocation_cycle.py','group_reallocation.py','adaptive_strategy_indexed.py','indexed_split.py',
         'targeted_strategy.py','fused_best_response.py','strategy_abstraction.py','custom_river.py',
         'native_cfr.py','native/cfr.cpp','benchmark_expanded.py','validate_reallocation_cycle.py')


def cases():
    for family in ('sizing','short_raise','sidepot_or_tie'):
        for n in range(2,7):
            for seed in (503,907):
                board=(['4h','7h','Jh','Qs','Ac'] if family=='short_raise' else
                       ['Td','Jd','Qd','Kd','Ad'] if family=='sidepot_or_tie' and n==2 else
                       ['4c','4s','8d','Jh','Kc'] if family=='sidepot_or_tie' else ['2h','5c','8s','Jd','Kh'])
                width={2:5,3:4,4:3,5:3,6:3}[n]
                case=make_case(f'cycle_{family}_{n}_{seed}',board,[width]*n,seed);spec=case['input']
                spec.update(pot=48*n,initial_contributions=[48]*n,min_bet=4,bet_sizes=[12,28],raise_sizes=[],max_raises=0)
                if family=='short_raise':spec.update(stacks=[9,17,25,39,57,79][:n],bet_sizes=[8],raise_sizes=[16],max_raises=1)
                elif family=='sidepot_or_tie':
                    if n==2:spec.update(pot=10,initial_contributions=[5,5],stacks=[9,17],min_bet=1,bet_sizes=[3],raise_sizes=[6],max_raises=1)
                    else:
                        spec.update(pot=12+36*(n-1),initial_contributions=[12]+[36]*(n-1),stacks=[0,18,29,47,61,83][:n],bet_sizes=[12],raise_sizes=[24],max_raises=1)
                        if n>=4:spec['ranges'][-1]=[];spec['folded']=[n-1]
                yield {**case,'family':family,'seed':seed,'dealt_players':n,'live_players':n-len(spec.get('folded',[]))}


def manifest():
    hashes={p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in SOURCES}
    if hashes['reallocation_cycle.py']!=FROZEN_CYCLE_SHA:raise ValueError('Cycle version changed; new study required.')
    parent=Path(__file__).parents[2]/'docs/research/adaptive-validation-manifest-2026-10-24.json'
    control=next(c for c in load_old_manifest(parent)['cases'] if c['name']=='sizing_4_101')
    payload={'version':1,'sources':hashes,'cases':list(cases()),'fault_case':control,
        'faults':['trial_timeout','trial_memory'],'limits':{'total_seconds':45,'memory_mib':128,'max_cycles':2,'max_candidates':2},
        'scope':'30 prespecified new synthetic cases, seeds 503/907. Two separate known-case process-fault controls excluded from quality summary. No retuning.'}
    return json.loads(json.dumps({**payload,'manifest_sha256':digest(payload)}))


def write_manifest(path):
    value=manifest()
    if path.exists():
        if json.loads(path.read_text())!=value:raise ValueError('Refusing changed manifest overwrite.')
    else:path.write_text(json.dumps(value,indent=2)+'\n')
    return value


def load_manifest(path):
    value=json.loads(path.read_text())
    if digest({k:v for k,v in value.items() if k!='manifest_sha256'})!=value.get('manifest_sha256'):raise ValueError('Manifest hash mismatch.')
    if value!=manifest():raise ValueError('Frozen source/config/corpus mismatch.')
    return value


def compact(result):
    for container in [result.get('baseline',{}),result,*result['attempts']]:
        for key in ('checkpoint','best_checkpoint'):
            cp=container.get(key)
            if cp is not None:
                cp=dict(cp);cp['policy_sha256']=sha256(json.dumps(cp.pop('policy'),sort_keys=True).encode()).hexdigest();container[key]=cp
    return result


def fault_runner(fault):
    def run(job,iterations,timeout,memory,**kwargs):
        if job['kind']=='trial':
            if fault=='trial_timeout':timeout=min(timeout,.001)
            elif fault=='trial_memory':memory=1
            else:raise ValueError('Unknown fault.')
        return run_guarded(job,iterations,timeout,memory,**kwargs)
    return run


def benchmark(path):
    plan=load_manifest(path);rows=[];faults=[]
    for case in plan['cases']:
        print(case['name'],file=sys.stderr,flush=True)
        rows.append({'case':case,'result':compact(run_cycle(case,**plan['limits']))})
    for fault in plan['faults']:
        print('Fault '+fault,file=sys.stderr,flush=True)
        result=compact(run_cycle(plan['fault_case'],_runner=fault_runner(fault),**plan['limits']))
        base=result['baseline'].get('checkpoint');best=result.get('best_checkpoint')
        preserved=base is not None and best is not None and base['policy_sha256']==best['policy_sha256'] and base['metrics']==best['metrics']
        faults.append({'fault':fault,'baseline_preserved':preserved,'result':result})
    load_manifest(path)
    return {'manifest_sha256':plan['manifest_sha256'],'sources':plan['sources'],'scope':plan['scope'],
        'summary':summarize(rows),'by_live_players':{str(n):summarize([r for r in rows if r['case']['live_players']==n]) for n in range(2,7)},
        'fault_controls':faults,'results':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--write-manifest',type=Path);p.add_argument('--manifest',type=Path);args=p.parse_args()
    if args.write_manifest:value={'manifest_sha256':write_manifest(args.write_manifest)['manifest_sha256']}
    elif args.manifest:value=benchmark(args.manifest)
    else:p.error('Write a manifest before running validation.')
    print(json.dumps(value,indent=2,allow_nan=False))
