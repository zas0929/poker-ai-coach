"""Prespecified synthetic holdout controls for the frozen adaptive prototype.

Write the immutable manifest BEFORE running solves. No training-policy edits or
lucky-seed retries. Engine probe checks all paths of one legal deal per case.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
from research.benchmark_expanded import make_case,run_guarded
from research.benchmark_adaptive_strategy import worker as adaptive_worker
from research.benchmark_capacity import peak_rss_mib
from research.custom_river import RiverGame
from research.sidepot_reference import compare_every_path

FROZEN_ADAPTIVE_SHA='4e86db66bf9de0020acc3415ab4df515fac8f07673bbaecbeb9141612724ffdf'
SOURCES=('adaptive_strategy.py','strategy_abstraction.py','benchmark_adaptive_strategy.py',
         'benchmark_strategy_abstraction.py','custom_river.py','river_replay.py','native_cfr.py',
         'native/cfr.cpp','compare_coach.py','sidepot_reference.py','validate_adaptive_strategy.py')
SEEDS=(101,211)


def digest(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def scenarios():
    for family in ('sizing','short_raises','prior_sidepot','folded','board_tie'):
        for n in range(3 if family in ('prior_sidepot','folded') else 2,7):
            for seed in SEEDS:
                board=(['3h','6h','Th','Ks','Ac'] if family=='short_raises' else
                       ['3c','3d','8h','Ts','Qc'] if family=='prior_sidepot' else
                       ['Tc','Jc','Qc','Kc','Ac'] if family=='board_tie' else ['3c','6d','8h','Ts','Qc'])
                width={2:6,3:4,4:3,5:3,6:3}[n]
                case=make_case(f'{family}_{n}_{seed}',board,[width]*n,seed)
                spec=case['input'];spec.update(bet_sizes=[15,35],raise_sizes=[],max_raises=0)
                if family=='short_raises':spec.update(stacks=[8,12,20,35,50,75][:n],min_bet=5,bet_sizes=[10],raise_sizes=[20],max_raises=1)
                elif family=='prior_sidepot':spec.update(stacks=[0,25,40,60,80,100][:n],initial_contributions=[15]+[45]*(n-1),pot=15+45*(n-1),bet_sizes=[15],raise_sizes=[30],max_raises=1)
                elif family=='folded':
                    spec['ranges'][1]=[];spec.update(folded=[1],stacks=[60]*n,initial_contributions=[45]*n,pot=45*n,bet_sizes=[15])
                elif family=='board_tie':spec.update(stacks=[7,11,18,25,40,60][:n],initial_contributions=[3]*n,pot=3*n,min_bet=1,bet_sizes=[4],raise_sizes=[8],max_raises=1)
                yield {**case,'family':family,'seed':seed,'dealt_players':n,'live_players':n-len(spec.get('folded',[])),'row_budget':'compact'}


def source_hashes():return {p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in SOURCES}


def manifest():
    hashes=source_hashes()
    if hashes['adaptive_strategy.py']!=FROZEN_ADAPTIVE_SHA:raise ValueError('Frozen adaptive algorithm changed; new study version required.')
    payload={'version':1,'seeds':SEEDS,'iterations_per_round':100,'max_splits':12,'max_groups_per_seat':8,
        'row_budget_fraction':.75,'quality_gate_pct_pot':.5,'limits':{'wall_seconds':45,'memory_mib':128},
        'source_sha256':hashes,'cases':list(scenarios()),
        'scope':'Prespecified synthetic holdout, 46 controls; not real-player calibration. No retuning on outcomes; all refusals retained.'}
    return {**payload,'manifest_sha256':digest(payload)}


def write_manifest(path):
    value=manifest()
    if path.exists():
        if json.loads(path.read_text())!=json.loads(json.dumps(value)):raise ValueError('Existing manifest differs; refusing overwrite.')
    else:path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    return value


def load_manifest(path):
    value=json.loads(path.read_text());payload={k:v for k,v in value.items() if k!='manifest_sha256'}
    if digest(payload)!=value.get('manifest_sha256'):raise ValueError('Manifest content hash mismatch.')
    if value!=json.loads(json.dumps(manifest())):raise ValueError('Manifest does not match frozen source/config/corpus.')
    return value


def worker(case,iterations):
    result=adaptive_worker(case,iterations)
    print(json.dumps({'phase':'engine_probe','observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    full=RiverGame(**{**case['input'],'utility_storage':'compact'})
    texts=full.deals[0][0]
    probe=RiverGame(**{**case['input'],'ranges':[[(t,1.)] if t else [] for t in texts],'utility_storage':'compact'})
    result['engine_probe']={'scope':'All public paths of the first legal original deal only.',**compare_every_path(probe)}
    result['peak_rss_mib']=peak_rss_mib()
    return result


def summarize(rows):
    def group(subset):
        completed=[r for r in subset if r['status']=='completed']
        eligible=[r for r in completed if r['baseline_quality_passed']]
        ready=[r for r in eligible if r['adaptive']['status']=='ready']
        return {'attempted':len(subset),'process_statuses':dict(Counter(r['status'] for r in subset)),
            'baseline_unqualified':len(completed)-len(eligible),'eligible':len(eligible),'ready':len(ready),
            'ready_with_actual_compression':sum(r['adaptive']['history'][-1]['grouped_strategy_rows']<r['adaptive']['original_strategy_rows'] for r in ready),
            'eligible_rejections':dict(Counter(r['adaptive']['reason'] for r in eligible if r['adaptive']['status']!='ready')),
            'adaptive_ready_with_unqualified_baseline':sum(r['adaptive']['status']=='ready' and not r['baseline_quality_passed'] for r in completed)}
    return {'overall':group(rows),'by_family':{f:group([r for r in rows if r['case']['family']==f]) for f in sorted({r['case']['family'] for r in rows})},
        'by_live_players':{str(n):group([r for r in rows if r['case']['live_players']==n]) for n in range(2,7)}}


def benchmark(path):
    plan=load_manifest(path);rows=[]
    for case in plan['cases']:
        print(case['name'],file=sys.stderr,flush=True)
        result=run_guarded(case,plan['iterations_per_round'],plan['limits']['wall_seconds'],plan['limits']['memory_mib'],method='cfr_plus_native',worker_module='research.validate_adaptive_strategy')
        rows.append({'case':case,**result})
    load_manifest(path) # Fail if source, plan or inputs changed during the run.
    return {'manifest_sha256':plan['manifest_sha256'],'source_sha256':plan['source_sha256'],
            'scope':plan['scope'],'summary':summarize(rows),'results':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true')
    p.add_argument('--iterations',type=int,default=100);p.add_argument('--method',choices=['cfr_plus_native'],default='cfr_plus_native')
    p.add_argument('--write-manifest',type=Path);p.add_argument('--manifest',type=Path);args=p.parse_args()
    if not 1<=args.iterations<=2000:p.error('1–2000 worker iterations required.')
    if args.worker:value=worker(json.load(sys.stdin),args.iterations)
    elif args.write_manifest:value={'manifest_sha256':write_manifest(args.write_manifest)['manifest_sha256']}
    elif args.manifest:value=benchmark(args.manifest)
    else:p.error('Write the manifest first, then run --manifest.')
    print(json.dumps(value,indent=None if args.worker else 2,allow_nan=False))
