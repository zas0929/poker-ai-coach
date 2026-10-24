"""Deterministic public mid-river transport and paired kernel controls, not GTO quality."""
import argparse
import json
import time
from research.benchmark_snapshot import control,select
from research.river_snapshot import build_river_from_snapshot
from research.sidepot_reference import compare_every_path


def benchmark(iterations=20):
    rows=[]
    for n,mode in [(n,'plain') for n in range(2,7)]+[(4,'folded'),(3,'prior_sidepot')]:
        actions=[('check',None),('bet',10),('raise',20)]
        if mode=='prior_sidepot':actions=[('bet',10),('raise',20)]
        elif n>=4 and mode=='plain':actions += [('call',None),('fold',None)]
        snapshot=control(n,mode,actions);chosen=select(snapshot)
        start=time.perf_counter()
        game,meta=build_river_from_snapshot(snapshot,chosen,bet_sizes=(10,),raise_sizes=(40,),max_raises=1,utility_storage='compact')
        build_seconds=time.perf_counter()-start
        checks=compare_every_path(game)
        policies={};metrics={};timings={}
        for method in ('cfr_plus_indexed','cfr_plus_native'):
            start=time.perf_counter();policy=game.train(iterations,method=method)
            timings[method]=time.perf_counter()-start
            policies[method]=policy;metrics[method]=game.measure(policy)
        a,b=policies.values()
        assert set(a)==set(b)
        difference=max((abs(v-w) for key in a for v,w in zip(a[key],b[key])),default=0)
        assert difference<1e-10
        metric_difference=max(abs(x-y) for key in ('policy_payoffs','best_response_payoffs','unilateral_gains')
                              for x,y in zip(metrics['cfr_plus_indexed'][key],metrics['cfr_plus_native'][key]))
        assert metric_difference<1e-8
        root=game.root
        rows.append({'players':n,'scenario':mode,'metadata':meta,'selected_public_hands':chosen,
                     'observed_actions':actions,'board':game.board,'root_history':root.history,
                     'root_actor':root.actor,'root_actions':root.actions,'public_nodes':len(game.nodes),
                     'joint_deals':len(game.deals),'engine_comparison':checks,'build_seconds':build_seconds,
                     'train_seconds':timings,'max_policy_difference':difference,'max_metric_difference':metric_difference,
                     'metrics':metrics['cfr_plus_native'],
                     'root_policy':[{'hand':hand,'probabilities':b[(root.actor,hand,root.history)]} for hand,_ in game.ranges[root.actor]]})
    return {'iterations':iterations,'scope':'Seven deterministic mid-river transport controls with one explicitly selected public hand per live seat. Not full-range coaching quality validation.',
            'bet_sizes':[10],'raise_sizes':[40],'future_raise_cap':1,'results':rows,
            'terminal_deal_checks':sum(r['engine_comparison']['terminal_deal_checks'] for r in rows)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--iterations',type=int,default=20)
    args=parser.parse_args();print(json.dumps(benchmark(args.iterations),indent=2))
