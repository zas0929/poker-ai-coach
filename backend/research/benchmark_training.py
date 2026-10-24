"""Compare training on a FIXED synthetic suite with exact unilateral best responses.
This research quality gate applies only to the restricted river game, not NLHE.
"""
import argparse
import json
import random
import time
from research.custom_river import RiverGame,demo_ranges

TARGET_MAX_GAIN_PCT_POT=.5

def scenarios():
    for n in range(2,7):
        yield 'original_dry',n,['2c','4d','7h','9s','Jc'],demo_ranges(n),100,50
        for name,board,bet in [('weighted_flush',['2s','5s','9s','Kh','Ad'],25),('weighted_paired',['Kh','Kd','2c','7s','9h'],100)]:
            rng=random.Random(20261024+n+(100 if name=='weighted_paired' else 0))
            deck=[r+s for r in '23456789TJQKA' for s in 'cdhs' if r+s not in board]
            ranges=[]
            for _ in range(n):
                hands=[]
                while len(hands)<2:
                    text=''.join(sorted(rng.sample(deck,2)))
                    if all(set((text[:2],text[2:]))!=set((old[:2],old[2:])) for old,_ in hands):hands.append((text,rng.choice([.2,.5,1.])))
                ranges.append(hands)
            yield name,n,board,ranges,100,bet
        yield 'board_tie',n,['As','Ks','Qs','Js','Ts'],[r[:1] for r in demo_ranges(n)],100,50

def benchmark(iterations=200,progress=None):
    results=[]
    for name,n,board,ranges,pot,bet in scenarios():
        game=RiverGame(board,ranges,pot=pot,bet=bet,stack=100)
        row={'scenario':name,'players':n,'board':board,'ranges':ranges,'pot':pot,'bet':bet,'joint_deals':len(game.deals),'uniform':game.measure({k:[.5,.5] for k in game.keys})}
        for method in ('cfr','cfr_plus'):
            started=time.perf_counter();policy=game.train(iterations,method=method)
            train_seconds=time.perf_counter()-started;metrics=game.measure(policy)
            row[method]={'train_seconds':round(train_seconds,4),**metrics,'passes_research_gate':metrics['max_unilateral_gain_pct_pot']<=TARGET_MAX_GAIN_PCT_POT}
        results.append(row)
        if progress:progress(f"{name} {n} players: {row['cfr']['max_unilateral_gain_pct_pot']:.4f}% -> {row['cfr_plus']['max_unilateral_gain_pct_pot']:.4f}%")
    return {'iterations':iterations,'gate_max_unilateral_gain_pct_pot':TARGET_MAX_GAIN_PCT_POT,'scope':'Fixed small-range one-bet river games only. Passing is not full-game GTO certification.','results':results,'summary':{method:{'passed':sum(r[method]['passes_research_gate'] for r in results),'total':len(results),'worst_max_gain_pct_pot':max(r[method]['max_unilateral_gain_pct_pot'] for r in results)} for method in ('cfr','cfr_plus')}}

if __name__=='__main__':
    import sys
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--iterations',type=int,default=200);parser.add_argument('--check',action='store_true',help='Exit nonzero if CFR+ fails the restricted research gate');args=parser.parse_args()
    report=benchmark(args.iterations,lambda line:print(line,file=sys.stderr,flush=True))
    print(json.dumps(report,indent=2))
    if args.check and report['summary']['cfr_plus']['passed']!=len(report['results']):
        raise SystemExit(1)
