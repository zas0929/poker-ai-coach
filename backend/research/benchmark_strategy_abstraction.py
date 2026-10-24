"""Common-reference EV and unrestricted best-response checks for strategy tying."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from research.benchmark_expanded import make_case,run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.custom_river import RiverGame
from research.strategy_abstraction import train_abstract
from research.compare_coach import root_action_values


def scenarios():
    for texture,board in [('dry',['2c','4d','7h','9s','Jc']),('flush',['2s','5s','9s','Kh','Ad'])]:
        for n in range(2,7):
            for seed in (17,31,73):
                width={2:8,3:5,4:4,5:3,6:3}[n]
                case=make_case(texture+'_'+str(n)+'_'+str(seed),board,[width]*n,seed)
                case['seed']=seed;case['input'].update(raise_sizes=[],max_raises=0)
                yield case


def root_diagnostic(game,baseline,candidate):
    hands=sorted({t[game.root.actor] for t,_,_ in game.deals});rows=[]
    for hand in hands:
        q,mass=root_action_values(game,baseline,hand,best_response=True)
        key=(game.root.actor,hand,game.root.history)
        a=candidate[key];b=baseline[key]
        ev=sum(p*v for p,v in zip(a,q));base_ev=sum(p*v for p,v in zip(b,q))
        rows.append({'hand':hand,'mass':mass,'tv':sum(abs(x-y) for x,y in zip(a,b))/2,
                     'loss_chips':max(q)-ev,'additional_loss_chips':base_ev-ev})
    return {'mean_tv':sum(r['mass']*r['tv'] for r in rows),
        'mean_first_action_loss_chips':sum(r['mass']*r['loss_chips'] for r in rows),
        'mean_additional_loss_chips':sum(r['mass']*r['additional_loss_chips'] for r in rows),
        'max_hand_first_action_loss_chips':max(r['loss_chips'] for r in rows),
        'scope':'Candidate first-action mixture evaluated with baseline Q and optimal future own continuation; not actual game loss.'}


def worker(case,iterations):
    def phase(name):print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    phase('build');game=RiverGame(**{**case['input'],'utility_storage':'compact'})
    phase('baseline');baseline=game.train(iterations,method='cfr_plus_native');base=game.measure(baseline)
    rows={}
    for mode in ('identity','category','equity_2','equity_4'):
        phase(mode);start=time.perf_counter();policy,evidence=train_abstract(game,mode,iterations)
        seconds=time.perf_counter()-start;metrics=game.measure(policy)
        identity_delta=max(abs(a-b) for key,row in policy.items() for a,b in zip(row,baseline[key])) if mode=='identity' else None
        rows[mode]={'evidence':evidence,'metrics_original_game':metrics,
            'passes_original_quality_gate':metrics['max_unilateral_gain_pct_pot']<=.5,
            'train_seconds':seconds,'identity_max_policy_delta':identity_delta,
            'root_diagnostic':root_diagnostic(game,baseline,policy)}
    return {'status':'completed','baseline_metrics':base,'baseline_quality_passed':base['max_unilateral_gain_pct_pot']<=.5,
            'methods':rows,'joint_deals':len(game.deals),'public_nodes':len(game.nodes),'peak_rss_mib':peak_rss_mib()}


def summarize(rows):
    eligible=[r for r in rows if r['status']=='completed' and r['baseline_quality_passed']]
    result={}
    for mode in ('identity','category','equity_2','equity_4'):
        values=[r['methods'][mode] for r in eligible]
        result[mode]={'cases_with_qualified_baseline':len(values),
            'quality_passed':sum(v['passes_original_quality_gate'] for v in values),
            'actually_compressed_cases':sum(v['evidence']['grouped_strategy_rows']<v['evidence']['original_strategy_rows'] for v in values),
            'actually_compressed_quality_passed':sum(v['passes_original_quality_gate'] and v['evidence']['grouped_strategy_rows']<v['evidence']['original_strategy_rows'] for v in values),
            'max_unilateral_gain_pct_pot':max((v['metrics_original_game']['max_unilateral_gain_pct_pot'] for v in values),default=None),
            'mean_root_additional_loss_chips':sum(v['root_diagnostic']['mean_additional_loss_chips'] for v in values)/len(values) if values else None,
            'mean_root_tv':sum(v['root_diagnostic']['mean_tv'] for v in values)/len(values) if values else None}
    return result


def benchmark(iterations):
    rows=[]
    for case in scenarios():
        print(case['name'],file=sys.stderr,flush=True)
        rows.append({'case':case,**run_guarded(case,iterations,45,128,method='cfr_plus_native',worker_module='research.benchmark_strategy_abstraction')})
    convergence=[]
    # Post-hoc failure probes, explicitly not an independent validation set.
    for case in scenarios():
        if case['name'] not in ('dry_2_17','dry_3_73','flush_3_31'):continue
        print('Convergence '+case['name'],file=sys.stderr,flush=True)
        convergence.append({'case':case,'iterations':1000,**run_guarded(case,1000,45,128,method='cfr_plus_native',worker_module='research.benchmark_strategy_abstraction')})
    return {'iterations':iterations,'convergence_checks':convergence,'limits':{'wall_seconds':45,'memory_mib':128,'quality_gate_pct_pot':.5},
        'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('strategy_abstraction.py','benchmark_strategy_abstraction.py','custom_river.py','compare_coach.py')},
        'scope':'30 synthetic full small-range river games, three seeds, 2–6 seats; single opening size, no future raises. Original deals and payoffs unchanged. No full public ranges or live advice.',
        'summary':summarize(rows),'results':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true')
    p.add_argument('--iterations',type=int,default=100);p.add_argument('--method',choices=['cfr_plus_native'],default='cfr_plus_native');args=p.parse_args()
    if not 1<=args.iterations<=2000:p.error('1–2000 iterations required.')
    print(json.dumps(worker(json.load(sys.stdin),args.iterations) if args.worker else benchmark(args.iterations),indent=None if args.worker else 2,allow_nan=False))
