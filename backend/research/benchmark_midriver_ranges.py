"""Wider public river continuations, isolated time/RSS and exact best-response checks.
Explicit seeded subsets retain public weights; this does not validate range calibration.
"""
import argparse
import json
import math
import platform
import random
import sys
import time
from research.benchmark_snapshot import control
from research.benchmark_expanded import run_guarded


def make_case(name,n,widths,seed,*,mode='plain',actions=None,board=None,river_stacks=None):
    if actions is None:
        actions=[('check',None),('bet',10)]+([('raise',20)] if n>=3 else [])
    snapshot=control(n,mode,actions,board,river_stacks)
    rng=random.Random(seed);chosen={};weights={}
    for player,width in zip(snapshot['players'],widths):
        if player['status']=='folded':continue
        selected=rng.sample(player['range'],width)
        chosen[player['id']]=[row['cards'] for row in selected]
        weights[player['id']]=selected
    raw=math.prod(len(hands) for hands in chosen.values())
    return {'name':name,'seed':seed,'raw_combinations':raw,'snapshot':snapshot,
            'selected_hands':chosen,'selected_public_weights':weights,
            'input':dict(bet_sizes=[10,40],raise_sizes=[80,120],max_raises=1,
                         max_joint_combos=4096,utility_storage='compact')}


def scenarios():
    widths={2:[12,12],3:[5]*3,4:[4,4,4,2],5:[3,3,3,2,2],6:[3,2,2,2,2,2]}
    for texture,board in [('dry',['2c','4d','7h','9s','Jc']),('flush',['2s','5s','9s','Kh','Ad'])]:
        for n,sizes in widths.items():
            yield make_case(f'{texture}_{n}',n,sizes,20261030+n+100*(texture=='flush'),board=board)
    yield make_case('river_fold_4',4,[5]*4,20261040,actions=[('check',None),('bet',10),('raise',20),('call',None),('fold',None)])
    yield make_case('prior_allin_3',3,[5]*3,20261041,mode='prior_sidepot',actions=[('bet',10)])
    yield make_case('short_closed_3',3,[5]*3,20261042,river_stacks=[200,200,60],
                    actions=[('bet',40),('raise',60),('call',None)])
    yield make_case('short_reopened_4',4,[4,4,4,2],20261043,river_stacks=[80,200,200,60],
                    actions=[('check',None),('bet',40),('raise',60),('raise',80),('call',None)])
    yield make_case('wide_2_4096',2,[64]*2,20261044)
    yield make_case('six_729',6,[3]*6,20261045)


def benchmark(iterations=100,timeout_seconds=45,memory_mib=128,names=None):
    cases=list(scenarios())
    if names is not None:
        if not names or len(set(names))!=len(names) or set(names)-{c['name'] for c in cases}:
            raise ValueError('Select nonempty, distinct known case names.')
        cases=[c for c in cases if c['name'] in names]
    rows=[]
    for case in cases:
        print('Starting '+case['name'],file=sys.stderr,flush=True)
        result=run_guarded(case,iterations,timeout_seconds,memory_mib,method='cfr_plus_native')
        snapshot=case['snapshot']
        # Full ranges can be recreated by the seeded fixture; do not duplicate them in the report.
        rows.append({**{k:v for k,v in case.items() if k not in ('snapshot','selected_hands')},
                     'source_information_key':snapshot['information_key'],'board':snapshot['board'],
                     'public_players':[{k:v for k,v in p.items() if k!='range'} for p in snapshot['players']],
                     'public_history':snapshot['history'],**result})
        print(case['name']+': '+result['status']+(' gap='+str(result['metrics']['max_unilateral_gain_pct_pot']) if 'metrics' in result else ''),file=sys.stderr,flush=True)
    completed=[r for r in rows if r['status']=='completed']
    return {'iterations':iterations,'method':'cfr_plus_native','timeout_seconds':timeout_seconds,'memory_mib':memory_mib,
            'quality_gate_pct_decision_pot':.5,'python':sys.version,'platform':platform.platform(),
            'scope':'Seeded explicit subsets of public heuristic ranges at mid-river decisions. Every live seat has multiple hands. Exact best responses in bounded continuations, not full-range GTO. RSS sampling is soft, every 0.2s.',
            'results':rows,'summary':{'total':len(rows),'completed':len(completed),
                'quality_passed':sum(r['passes_quality_gate'] for r in completed),
                'statuses':{s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})}}}


def paired_controls(iterations=20):
    """Compare wider weighted public inputs on the same tree, without process budgets."""
    from research.river_snapshot import build_river_from_snapshot
    rows=[]
    for case in scenarios():
        if case['name'] not in ('dry_3','short_reopened_4'):continue
        game,meta=build_river_from_snapshot(case['snapshot'],case['selected_hands'],**case['input'])
        policies={};metrics={};timings={}
        for method in ('cfr_plus_indexed','cfr_plus_native'):
            start=time.perf_counter();policies[method]=game.train(iterations,method=method)
            timings[method]=time.perf_counter()-start
            metrics[method]=game.measure(policies[method])
        left,right=policies.values()
        if set(left)!=set(right):raise AssertionError('Different information sets')
        policy_diff=max((abs(x-y) for k in left for x,y in zip(left[k],right[k])),default=0)
        metric_diff=max(abs(x-y) for k in ('policy_payoffs','best_response_payoffs','unilateral_gains')
                        for x,y in zip(metrics['cfr_plus_indexed'][k],metrics['cfr_plus_native'][k]))
        if policy_diff>1e-10 or metric_diff>1e-8:raise AssertionError('Native/Python mismatch')
        rows.append({'name':case['name'],'source_information_key':meta['source_information_key'],
                     'task_key':meta['task_key'],'public_nodes':len(game.nodes),'joint_deals':len(game.deals),
                     'train_seconds':timings,'max_policy_difference':policy_diff,'max_metric_difference':metric_diff})
    return {'iterations':iterations,'scope':'Paired wider weighted public-prefix controls; no timing/RSS gate.', 'results':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations',type=int,default=100)
    parser.add_argument('--timeout-seconds',type=float,default=45)
    parser.add_argument('--memory-mib',type=float,default=128)
    parser.add_argument('--cases',nargs='+')
    parser.add_argument('--paired',action='store_true',help='Run the two fixed numerical equivalence controls')
    args=parser.parse_args()
    if not 1<=args.iterations<=2000 or any(not math.isfinite(v) or v<=0 for v in (args.timeout_seconds,args.memory_mib)):
        parser.error('Positive finite time/memory and 1–2000 iterations required.')
    if args.paired and args.cases:parser.error('--paired uses its two fixed controls; --cases is not supported.')
    report=paired_controls(args.iterations) if args.paired else benchmark(args.iterations,args.timeout_seconds,args.memory_mib,args.cases)
    print(json.dumps(report,indent=2))
