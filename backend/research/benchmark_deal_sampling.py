"""Empirical fixed-sample CFR vs exact full-range controls; not MCCFR."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from research.benchmark_expanded import make_case,run_guarded
from research.benchmark_capacity import peak_rss_mib
from research.custom_river import RiverGame
from research.deal_sampling import sample_joint_ranges,SampleView
from research.fused_best_response import evaluate_policy
from research.native_cfr import train_native


def scenarios():
    for texture,board in [('dry',['2c','4d','7h','9s','Jc']),('flush',['2s','5s','9s','Kh','Ad'])]:
        for n in range(2,7):
            width={2:8,3:5,4:4,5:3,6:3}[n]
            case=make_case(f'{texture}_{n}',board,[width]*n,404+n)
            case['input'].update(raise_sizes=[],max_raises=0)
            yield case


def worker(case):
    def phase(name):print(json.dumps({'phase':name,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    phase('build');game=RiverGame(**{**case['input'],'utility_storage':'compact'})
    baseline=train_native(game,100);base_metrics,_=evaluate_policy(game,baseline)
    uniform={k:[1./c]*c for k,c in game.action_counts.items()};uniform_metrics,_=evaluate_policy(game,uniform)
    exact_weights={t:w for t,w,_ in game.deals};rows=[]
    for samples in (32,128,512):
        for seed in (11,43,97):
            phase(f'sample_{samples}_{seed}')
            draw=sample_joint_ranges(game.board,game.ranges,folded=game.folded,samples=samples,seed=seed,max_attempts=samples*100)
            evidence={k:v for k,v in draw.items() if k!='counts'}
            if draw['status']!='sampled':rows.append({'sampling':evidence,'status':draw['status']});continue
            view=SampleView(game,draw);policy=train_native(view,100);empirical,_=evaluate_policy(view,policy)
            sampled_uniform={k:[1./c]*c for k,c in view.action_counts.items()}
            um,_=evaluate_policy(view,sampled_uniform)
            row={'sampling':evidence,'status':'incomplete_coverage' if view.missing_keys else 'comparable',
                'unique_deals':len(view.deals),'missing_strategy_rows':len(view.missing_keys),
                'joint_distribution_tv':.5*sum(abs(draw['counts'].get(t,0)/samples-w) for t,w in exact_weights.items()),
                'empirical_metrics':empirical,'empirical_quality_passed':empirical['max_unilateral_gain_pct_pot']<=.5,
                'fixed_uniform_payoff_error_chips':[a-b for a,b in zip(um['policy_payoffs'],uniform_metrics['policy_payoffs'])]}
            if not view.missing_keys:
                full,_=evaluate_policy(game,policy)
                row.update(full_metrics=full,full_quality_passed=full['max_unilateral_gain_pct_pot']<=.5,
                    root_mean_tv=sum(w*.5*sum(abs(a-b) for a,b in zip(policy[(game.root.actor,t[game.root.actor],game.root.history)],baseline[(game.root.actor,t[game.root.actor],game.root.history)])) for t,w,_ in game.deals))
            rows.append(row)
    return {'status':'completed','baseline_metrics':base_metrics,'baseline_quality_passed':base_metrics['max_unilateral_gain_pct_pot']<=.5,
            'legal_deals':len(game.deals),'samples':rows,'peak_rss_mib':peak_rss_mib()}


def summarize(rows):
    result={}
    for size in (32,128,512):
        selected=[s for row in rows if row['status']=='completed' for s in row['samples'] if s['sampling']['requested']==size]
        comparable=[s for s in selected if s['status']=='comparable']
        result[str(size)]={'attempted':len(selected),'comparable':len(comparable),
            'empirical_quality_passed':sum(s.get('empirical_quality_passed',False) for s in selected),
            'full_quality_passed':sum(s['full_quality_passed'] for s in comparable),
            'empirical_pass_full_fail':sum(s['empirical_quality_passed'] and not s['full_quality_passed'] for s in comparable)}
    return result


def benchmark():
    rows=[]
    for case in scenarios():
        print(case['name'],file=sys.stderr,flush=True)
        rows.append({'case':case,**run_guarded(case,100,45,128,method='cfr_plus_native',worker_module='research.benchmark_deal_sampling')})
    return {'scope':'90 fixed-sample solves, 10 small exact controls, 3 sample sizes and 3 seeds. Whole-lineup rejection preserves conditional product-weighted law. No grouping, coverage repair, confidence bound, MCCFR, or live advice. Exact full game is still built as a reference.',
        'limits':{'wall_seconds_per_case':45,'memory_mib':128},
        'source_sha256':{p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in ('deal_sampling.py','benchmark_deal_sampling.py','fused_best_response.py','custom_river.py')},
        'summary':summarize(rows),'results':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true');p.add_argument('--iterations',type=int,default=100);p.add_argument('--method',default='cfr_plus_native');args=p.parse_args()
    print(json.dumps(worker(json.load(sys.stdin)) if args.worker else benchmark(),indent=None if args.worker else 2,allow_nan=False))
