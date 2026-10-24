"""Read TexasSolver JSON for the exact two-player, one-all-in-bet control.
The matching upstream input can be generated with solver_probe.commands for
pot=100, stack=50, demo_ranges(2), board=2c,4d,7h,9s,Jc.
"""
import argparse
import json
import math
from pathlib import Path
from research.custom_river import RiverGame,demo_ranges
from research.river_reference import row

def convert_policy(game,tree):
    if game.n!=2:raise ValueError('TexasSolver comparison supports two players only.')
    policy={}
    def visit(node,external):
        if node.actor==-1:return
        actions=[a if not a.startswith('BET ') else f'BET {float(a.split()[1]):.6f}' for a in node.actions]
        if external.get('player')!=1-node.actor or set(external.get('actions',[]))!=set(actions):
            raise ValueError('Solver game trees are not equivalent.')
        for hand,_ in game.ranges[node.actor]:
            key=(node.actor,hand,node.history)
            if key not in game.keys:continue
            probs=row(external,hand)
            if probs is None:raise ValueError('Missing hand.')
            total=sum(probs)
            if any(not math.isfinite(p) or not 0<=p<=1 for p in probs) or abs(total-1)>1e-5:
                raise ValueError('Invalid exported probabilities.')
            # Upstream JSON stores float32 rows; remove tiny sum-rounding only.
            policy[key]=[probs[external['actions'].index(action)]/total for action in actions]
        for action,child in zip(actions,node.children):visit(child,external.get('childrens',{}).get(action,{}))
    visit(game.root,tree)
    return policy

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('result_json',type=Path);args=parser.parse_args()
    game=RiverGame(['2c','4d','7h','9s','Jc'],demo_ranges(2),pot=100,bet=50,stack=50)
    external=convert_policy(game,json.loads(args.result_json.read_text()))
    print(json.dumps({'scope':'Identical two-player restricted all-in river tree, no action-frequency identity assumption.','custom_200_iterations':game.measure(game.train(200)),'texas_solver':game.measure(external)},indent=2))
