"""Bounded offline strategy refinement; evaluates every policy in original game.

Splits use counterfactual action values with exact original blocker-conditioned
chance. No representative cards, completed cache, or production advice route.
"""
from collections import defaultdict
import math
from research.strategy_abstraction import StrategyView,hand_groups,lift_policy
from research.indexed_cfr import train_indexed
from research.native_cfr import train_native


def action_values(game,policy):
    """Original own-hand BR continuation, aggregating hidden deals BEFORE max.

    Each record retains unnormalized chance/opponent-reach weighted action EVs.
    Own reach is excluded, so off-policy branches are available for refinement.
    """
    game.measure(policy)  # Validate complete normalized original-game policy.
    records={}
    for me in range(game.n):
        if me not in game.live:continue
        hands=defaultdict(list)
        for d,(texts,weight,_) in enumerate(game.deals):hands[texts[me]].append((d,weight))
        for hand,initial in sorted(hands.items()):
            def visit(node,weights):
                if node.actor==-1:
                    return sum(w*game.utilities[(id(node),d)][me] for d,w in weights)
                if node.actor==me:
                    q=[visit(child,weights) for child in node.children]
                    records[(me,hand,node.history)]={'q':q,'mass':sum(w for _,w in weights),'actions':node.actions}
                    return max(q)
                return sum(visit(child,[(d,w*policy[game.key(node,d)][a]) for d,w in weights])
                           for a,child in enumerate(node.children))
            visit(game.root,initial)
    return records


def propose_split(game,mapping,records,max_groups_per_seat,max_strategy_rows):
    view=StrategyView(game,mapping);bygroup=defaultdict(list)
    for (seat,hand,history),record in records.items():bygroup[(seat,mapping[seat][hand],history)].append((hand,record))
    best=None
    for (seat,label,history),items in sorted(bygroup.items()):
        if len(set(mapping[seat].values()))>=max_groups_per_seat or len(items)<2:continue
        items=sorted(items);count=len(items[0][1]['q'])
        total=[sum(r['q'][a] for _,r in items) for a in range(count)]
        # Binary split by differing best actions, not private opponent holdings.
        choices={hand:max(range(count),key=lambda a:r['q'][a]) for hand,r in items}
        for action in sorted(set(choices.values())):
            left=[hand for hand,_ in items if choices[hand]==action]
            if len(left)==len(items):continue
            leftset=set(left);lq=[sum(r['q'][a] for h,r in items if h in leftset) for a in range(count)]
            rq=[total[a]-lq[a] for a in range(count)]
            score=max(lq)+max(rq)-max(total)
            if score<=1e-10:continue
            candidate=[dict(m) for m in mapping]
            # Labels contain the split's history only in evidence. Mapping is
            # fixed for each hand across all histories, preserving own recall.
            suffix=0;new=label+'/split'+str(suffix)
            while new in candidate[seat].values():suffix+=1;new=label+'/split'+str(suffix)
            for hand in left:candidate[seat][hand]=new
            rows=len(StrategyView(game,candidate).keys)
            if rows>max_strategy_rows:continue
            if best is None or score>best['priority_chips']+1e-12:
                best={'mapping':candidate,'seat':seat,'history':history,'group':label,
                      'split_members':left,'priority_chips':score,'grouped_strategy_rows':rows}
    return best


def train_adaptive(game,*,iterations=100,max_splits=12,max_groups_per_seat=8,
                   max_strategy_rows,quality_gate_pct_pot=.5,method='cfr_plus_native'):
    if type(iterations) is not int or not 1<=iterations<=2000 or type(max_splits) is not int or not 0<=max_splits<=32:
        raise ValueError('Bounded iterations and 0–32 splits required.')
    if type(max_groups_per_seat) is not int or not 2<=max_groups_per_seat<=64 or type(max_strategy_rows) is not int or not 1<=max_strategy_rows<=len(game.keys):
        raise ValueError('Explicit group and original strategy-row limits required.')
    if type(quality_gate_pct_pot) not in (float,int) or not math.isfinite(quality_gate_pct_pot) or not 0<quality_gate_pct_pot<=.5:
        raise ValueError('Positive quality threshold at most 0.5% required.')
    if method not in ('cfr_plus_native','cfr_plus_indexed'):raise ValueError('Explicit CFR+ method required.')
    mapping=hand_groups(game,'equity_2');history=[];splits=[];last=None;metrics=None
    for round_index in range(max_splits+1):
        view=StrategyView(game,mapping)
        if len(view.keys)>max_strategy_rows:reason='initial_row_budget';break
        trained=train_native(view,iterations) if method=='cfr_plus_native' else train_indexed(view,iterations)
        last=lift_policy(game,view,trained);metrics=game.measure(last)
        history.append({'round':round_index,'grouped_strategy_rows':len(view.keys),
                        'hand_group_counts':[len(set(m.values())) for m in mapping],
                        'max_unilateral_gain_pct_pot':metrics['max_unilateral_gain_pct_pot']})
        if metrics['max_unilateral_gain_pct_pot']<=quality_gate_pct_pot:reason='quality_passed';break
        if round_index==max_splits:reason='split_budget_exhausted';break
        proposal=propose_split(game,mapping,action_values(game,last),max_groups_per_seat,max_strategy_rows)
        if proposal is None:reason='no_split_within_budget';break
        mapping=proposal.pop('mapping');splits.append(proposal)
    return last,{'status':'ready' if reason=='quality_passed' else 'rejected','reason':reason,
        'history':history,'splits':splits,'metrics_original_game':metrics,
        'original_strategy_rows':len(game.keys),'limits':{'iterations_per_round':iterations,'max_splits':max_splits,
            'max_groups_per_seat':max_groups_per_seat,'max_strategy_rows':max_strategy_rows,'quality_gate_pct_pot':quality_gate_pct_pot},
        'live_advice_allowed':False,'scope':'Offline original-game unilateral-gain gate only. Full deals and tree unchanged.'}
