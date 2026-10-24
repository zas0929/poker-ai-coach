"""Offline river strategy tying; original deals, chance weights and payoffs stay exact.

This reduces private strategy rows, NOT deal enumeration or the action tree.
Best responses must be measured in the original game after lifting the policy.
"""
import math
from research.indexed_cfr import train_indexed
from research.native_cfr import train_native

MODES=('identity','category','equity_2','equity_4')


def hand_groups(game,mode):
    if mode not in MODES:raise ValueError('Explicit supported abstraction mode required.')
    hands=[{} for _ in range(game.n)];masses=[{} for _ in range(game.n)]
    shares=[{} for _ in range(game.n)]
    for texts,weight,scores in game.deals:
        best=max(scores[p] for p in game.live);winners=[p for p in game.live if scores[p]==best]
        for p in game.live:
            text=texts[p];hands[p][text]=scores[p]
            masses[p][text]=masses[p].get(text,0.)+weight
            shares[p][text]=shares[p].get(text,0.)+weight*(1./len(winners) if p in winners else 0.)
    mapping=[]
    for p in range(game.n):
        if mode=='identity':seat={t:t for t in hands[p]}
        elif mode=='category':seat={t:'category_'+str(score[0]) for t,score in hands[p].items()}
        else:
            count=int(mode.split('_')[1])
            ordered=sorted(hands[p],key=lambda t:(shares[p][t]/masses[p][t],t))
            seat={t:'equity_bin_'+str(min(count-1,i*count//len(ordered))) for i,t in enumerate(ordered)}
        mapping.append(seat)
    return mapping


class StrategyView:
    """Numeric-kernel view; no mutation or rebuilding of the original game."""
    def __init__(self,game,mapping):
        if len(mapping)!=game.n:raise ValueError('One mapping per seat required.')
        for p,hand,_ in game.keys:
            if hand not in mapping[p] or not isinstance(mapping[p][hand],str) or not mapping[p][hand]:
                raise ValueError('Complete nonempty group labels required.')
        self.mapping=[dict(m) for m in mapping]
        self.nodes=game.nodes;self.root=game.root;self.deals=game.deals
        self.utilities=game.utilities;self.n=game.n
        self.keys=set();self.action_counts={}
        for key,count in game.action_counts.items():
            grouped=(key[0],self.mapping[key[0]][key[1]],key[2])
            if grouped in self.action_counts and self.action_counts[grouped]!=count:
                raise ValueError('Merged information sets must share legal actions.')
            self.keys.add(grouped);self.action_counts[grouped]=count

    def key(self,node,deal):
        return (node.actor,self.mapping[node.actor][self.deals[deal][0][node.actor]],node.history)


def lift_policy(game,view,policy):
    if set(policy)!=view.keys:raise ValueError('Complete grouped policy required.')
    for key,row in policy.items():
        if len(row)!=view.action_counts[key] or any(not math.isfinite(v) or not 0<=v<=1 for v in row) or abs(sum(row)-1)>1e-8:
            raise ValueError('Finite normalized grouped policy required.')
    return {key:list(policy[(key[0],view.mapping[key[0]][key[1]],key[2])]) for key in game.keys}


def train_abstract(game,mode,iterations=100,method='cfr_plus_native'):
    view=StrategyView(game,hand_groups(game,mode))
    if method=='cfr_plus_native':policy=train_native(view,iterations)
    elif method=='cfr_plus_indexed':policy=train_indexed(view,iterations)
    else:raise ValueError('Explicit indexed/native CFR+ required.')
    return lift_policy(game,view,policy),{'mode':mode,'original_strategy_rows':len(game.keys),
        'grouped_strategy_rows':len(view.keys),'hand_group_counts':[len(set(m.values())) for m in view.mapping],
        'original_deals_preserved':view.deals is game.deals,'original_payoffs_preserved':view.utilities is game.utilities,
        'live_advice_allowed':False,'scope':'Strategy restriction on explicit river ranges; full deals still enumerated.'}
