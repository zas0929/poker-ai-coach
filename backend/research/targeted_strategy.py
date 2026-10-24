"""Experimental refinement targeting the largest original-game unilateral gain.
Same row/iteration/quality limits. A ranking heuristic, not a convergence claim.
"""
import math
from research.indexed_split import propose_split_indexed


def propose_targeted_split(game,mapping,records,max_groups_per_seat,max_strategy_rows,metrics):
    gains=metrics['unilateral_gains']
    if len(gains)!=game.n or any(not math.isfinite(v) or v<0 for v in gains):
        raise ValueError('One finite nonnegative unilateral gain per seat required.')
    for seat in sorted(range(game.n),key=lambda p:(-gains[p],p)):
        if gains[seat]<=1e-10:continue
        own={key:value for key,value in records.items() if key[0]==seat}
        proposal=propose_split_indexed(game,mapping,own,max_groups_per_seat,max_strategy_rows)
        if proposal is not None:
            return {**proposal,'target_unilateral_gain_chips':gains[seat]}
    return None
