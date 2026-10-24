"""Fixed tiny unequal-stack river controls; no full-game optimality claim."""
import argparse
import json
import sys
import time
from research.custom_river import RiverGame,demo_ranges
from research.sidepot_reference import compare_every_path


def scenarios():
    for n in range(2,7):
        ranges=demo_ranges(n) if n<=4 else [demo_ranges(n)[0]]+[r[:1] for r in demo_ranges(n)[1:]]
        stacks=[15,30,50,70,90,110][:n]
        yield 'unequal',dict(board=['2c','4d','7h','9s','Jc'],ranges=ranges,pot=60*n,
                             stacks=stacks,initial_contributions=[60]*n,
                             bet_sizes=[min(40,max(stacks))],raise_sizes=[min(80,max(stacks))],max_raises=1,min_bet=10)
        if n>=3:
            yield 'prior_sidepot',dict(board=['2c','4d','7h','9s','Jc'],ranges=ranges,pot=30+60*(n-1),
                                      stacks=[0]+stacks[1:],initial_contributions=[30]+[60]*(n-1),
                                      bet_sizes=[min(40,max(stacks))],raise_sizes=[min(80,max(stacks))],max_raises=1,min_bet=10)
        stacks=[2,5,8,11,14,17][:n]
        yield 'tie_odd',dict(board=['As','Ks','Qs','Js','Ts'],ranges=ranges,pot=3*n,
                             stacks=stacks,initial_contributions=[3]*n,
                             bet_sizes=[4],raise_sizes=[min(8,max(stacks))],max_raises=1,min_bet=1)


def benchmark(iterations=200):
    rows=[]
    for name,spec in scenarios():
        game=RiverGame(**spec)
        checked=compare_every_path(game)
        uniform=game.measure({k:[1/m]*m for k,m in game.action_counts.items()})
        start=time.perf_counter();policy=game.train(iterations,method='cfr_plus');elapsed=time.perf_counter()-start
        after=game.measure(policy)
        row={'scenario':name,'input':spec,'public_nodes':len(game.nodes),'joint_deals':len(game.deals),
             'engine_comparison':checked,'uniform':uniform,'trained':after,'training_seconds':round(elapsed,4)}
        rows.append(row)
        print(f"{name} {game.n}: {after['max_unilateral_gain_pct_pot']:.4f}% ({elapsed:.2f}s)",file=sys.stderr,flush=True)
    return {'method':'cfr_plus','iterations':iterations,
            'scope':'14 fixed small-range river abstractions. At 5/6 seats only seat zero has two private hands. All players begin river live, some already all-in. Not representative full-game validation.',
            'results':rows,'summary':{'worst_max_gain_pct_pot':max(r['trained']['max_unilateral_gain_pct_pot'] for r in rows),
                                     'node_deal_visits':sum(r['engine_comparison']['node_deal_visits'] for r in rows),
                                     'terminal_deal_checks':sum(r['engine_comparison']['terminal_deal_checks'] for r in rows)}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--iterations',type=int,default=200)
    args=parser.parse_args();print(json.dumps(benchmark(args.iterations),indent=2))
