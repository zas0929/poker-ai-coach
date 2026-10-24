"""Fused exact policy value, unrestricted BR and refinement action values.

Reference research modules stay frozen. Hidden deals are grouped by own hand;
all branches share opponent/chance reach, own decisions aggregate before max.
"""
import math


def evaluate_policy(game,policy):
    if set(policy)!=game.keys or any(len(row)!=game.action_counts[key] or
        any(not math.isfinite(p) or not 0<=p<=1 for p in row) or abs(sum(row)-1)>1e-8 for key,row in policy.items()):
        raise ValueError('Complete normalized finite policy required.')
    records={};profile=[];best=[]
    for me in range(game.n):
        hands={}
        for d,(texts,weight,_) in enumerate(game.deals):hands.setdefault(texts[me],[]).append((d,weight))
        def visit(node,weights):
            if node.actor==-1:
                value=sum(w*game.utilities[(id(node),d)][me] for d,w in weights)
                return value,value
            if node.actor==me:
                children=[visit(child,weights) for child in node.children]
                q=[value[1] for value in children]
                key=game.key(node,weights[0][0]);strategy=policy[key]
                records[key]={'q':q,'mass':sum(w for _,w in weights),'actions':node.actions}
                return sum(p*value[0] for p,value in zip(strategy,children)),max(q)
            children=[visit(child,[(d,w*policy[game.key(node,d)][a]) for d,w in weights]) for a,child in enumerate(node.children)]
            return sum(value[0] for value in children),sum(value[1] for value in children)
        values=[visit(game.root,weights) for weights in hands.values()]
        profile.append(sum(value[0] for value in values));best.append(sum(value[1] for value in values))
    gains=[max(0,b-v) for b,v in zip(best,profile)]
    return {'policy_payoffs':profile,'best_response_payoffs':best,'unilateral_gains':gains,
            'nash_conv_chips':sum(gains),'max_unilateral_gain_pct_pot':max(gains)/game.decision_pot*100},records
