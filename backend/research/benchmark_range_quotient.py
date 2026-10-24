"""Isolated full-range vs exact quotient controls on small explicit river models."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from research.benchmark_expanded import make_case,run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.custom_river import RiverGame
from research.exact_range_quotient import compress_ranges,lift_policy,verify_quotient


def scenarios():
    for n in range(2,7):
        for texture,board in [('dry',['2c','4d','7h','9s','Jc']),('flush',['2s','5s','9s','Kh','Ad'])]:
            width={2:8,3:5,4:4,5:3,6:3}[n]
            case=make_case(texture+'_'+str(n),board,[width]*n,20261024+n+100*(texture=='flush'))
            case['input'].update(raise_sizes=[],max_raises=0)
            yield case
        # Deliberately equivalent pairs provide a positive contraction control.
        ranges=[[(r+'h'+r+'d',1.),(r+'c'+r+'s',3.)] for r in 'AKQT86'[:n]]
        yield {'name':'equivalent_'+str(n),'input':{'board':['2c','4d','7h','9s','Jc'],'ranges':ranges,
            'pot':60*n,'stacks':[100]*n,'initial_contributions':[60]*n,
            'bet_sizes':[40],'raise_sizes':[],'max_raises':0,'min_bet':10,'max_joint_combos':4096}}
    # One all-in short contributor creates a side pot. Fourth seat is folded.
    yield {'name':'sidepot_folded_blocker','input':{'board':['2c','4d','7h','9s','Jc'],
        'ranges':[[('AhAd',1.),('AcAs',2.)],[('AhKd',1.),('AcKs',3.)],[('QhQd',2.),('QcQs',1.)],[]],
        'pot':200,'stacks':[100,100,0,0],'initial_contributions':[60,60,20,60],
        'folded':[3],'dealer':3,'bet_sizes':[40],'raise_sizes':[],'max_raises':0,'min_bet':10,'max_joint_combos':4096}}


    yield {'name':'board_tie_odd_chips','input':{'board':['Ts','Js','Qs','Ks','As'],
        'ranges':[[('2c3d',1.),('2h3c',2.)],[('4c5d',3.),('4h5c',1.)],[('6c7d',1.)],[]],
        'pot':19,'stacks':[20,20,0,0],'initial_contributions':[5,5,4,5],
        'folded':[3],'dealer':3,'bet_sizes':[3],'raise_sizes':[],'max_raises':0,'min_bet':1,'max_joint_combos':4096}}


def worker(case,iterations):
    def phase(name):print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    phase('build');spec={**case['input'],'utility_storage':'compact'}
    start=time.perf_counter();full=RiverGame(**spec);full_build=time.perf_counter()-start
    start=time.perf_counter();quotient=compress_ranges(spec['board'],spec['ranges'],folded=spec.get('folded',()))
    compression=time.perf_counter()-start
    start=time.perf_counter();reduced=RiverGame(**{**spec,'ranges':quotient['ranges']});small_build=time.perf_counter()-start
    phase('verify');verification=verify_quotient(full,reduced,quotient)
    phase('train');start=time.perf_counter();fp=full.train(iterations,method='cfr_plus_native');ft=time.perf_counter()-start
    start=time.perf_counter();rp=reduced.train(iterations,method='cfr_plus_native');rt=time.perf_counter()-start
    phase('measure');fm=full.measure(fp);rm=reduced.measure(rp);lifted=full.measure(lift_policy(full,rp,quotient))
    error=max(abs(a-b) for key in ('policy_payoffs','best_response_payoffs','unilateral_gains') for a,b in zip(rm[key],lifted[key]))
    if error>1e-8:raise ValueError('Lifted full-game policy changed payoff or best-response values.')
    return {'status':'completed','quotient':quotient,'verification':verification,
        'full_deals':len(full.deals),'compressed_deals':len(reduced.deals),'public_nodes':len(full.nodes),
        'full_metrics':fm,'compressed_metrics':rm,'lifted_full_metrics':lifted,
        'max_lifted_metric_error_chips':error,'passes_quality_gate':all(m['max_unilateral_gain_pct_pot']<=.5 for m in (fm,rm,lifted)),
        'seconds':{'full_build':full_build,'compression':compression,'compressed_build':small_build,'full_train':ft,'compressed_train':rt},
        'peak_rss_mib':peak_rss_mib()}


def benchmark(iterations):
    results=[]
    for case in scenarios():
        print(case['name'],file=sys.stderr,flush=True)
        result=run_guarded(case,iterations,45,128,method='cfr_plus_native',worker_module='research.benchmark_range_quotient')
        results.append({'case':case,**result})
    return {'iterations':iterations,'limits':{'wall_seconds':45,'memory_mib':128,'quality_gate_pct_pot':.5},
        'scope':'Small explicit synthetic river ranges, 2–6 seats. Full and quotient share the public tree; all original legal deals and terminal payouts checked. Live trainer unchanged.',
        'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('benchmark_range_quotient.py','exact_range_quotient.py','custom_river.py')},
        'all_verified':all(r.get('verification',{}).get('verified',False) for r in results),
        'all_quality_passed':all(r.get('passes_quality_gate',False) for r in results),'results':results}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true');p.add_argument('--iterations',type=int,default=100)
    p.add_argument('--method',choices=['cfr_plus_native'],default='cfr_plus_native');args=p.parse_args()
    if not 1<=args.iterations<=2000:p.error('1–2000 iterations required.')
    report=worker(json.load(sys.stdin),args.iterations) if args.worker else benchmark(args.iterations)
    print(json.dumps(report,indent=None if args.worker else 2,allow_nan=False))
