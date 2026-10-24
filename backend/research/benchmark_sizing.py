"""Deterministic expanded-tree controls, not a full-game quality certificate."""
import argparse
import json
import sys
import time
from research.custom_river import RiverGame,demo_ranges


def benchmark(iterations=200):
    results=[]
    for n in range(2,7):
        # Two private hands per player through four seats; at five/six only
        # seat zero is uncertain, explicitly limiting exact traversal cost.
        ranges=demo_ranges(n) if n<=4 else [demo_ranges(n)[0]]+[r[:1] for r in demo_ranges(n)[1:]]
        game=RiverGame(['2c','4d','7h','9s','Jc'],ranges,bet_sizes=(25,50),
                       raise_sizes=(100,),max_raises=1,min_bet=10)
        uniform=game.measure({k:[1/m]*m for k,m in game.action_counts.items()})
        started=time.perf_counter();policy=game.train(iterations,method='cfr_plus')
        seconds=time.perf_counter()-started
        row={'players':n,'board':['2c','4d','7h','9s','Jc'],'ranges':ranges,
             'pot':100,'stack':100,'bet_sizes':[25,50],'raise_sizes':[100],
             'max_raises':1,'min_bet':10,'public_nodes':len(game.nodes),
             'joint_deals':len(game.deals),'information_sets':len(game.keys),
             'training_seconds':round(seconds,4),'uniform':uniform,'trained':game.measure(policy)}
        results.append(row)
        print(f"{n} players: {row['trained']['max_unilateral_gain_pct_pot']:.4f}% ({seconds:.2f}s)",file=sys.stderr,flush=True)
    return {'iterations':iterations,'method':'cfr_plus',
            'scope':'Explicit two-bet/one-all-in-raise river abstraction. 5/6-player controls have uncertainty only at seat zero. Not a general quality gate or NLHE certification.',
            'results':results}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations',type=int,default=200)
    args=parser.parse_args()
    print(json.dumps(benchmark(args.iterations),indent=2))
