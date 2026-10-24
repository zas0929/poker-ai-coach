"""Bounded merge/project/split experiment; never changes chance or live advice."""
from itertools import combinations
from collections import defaultdict
from research.strategy_abstraction import StrategyView,hand_groups,lift_policy
from research.fused_best_response import evaluate_policy
from research.targeted_strategy import propose_targeted_split
from research.native_cfr import train_native
from research.indexed_cfr import train_indexed


def recover_mapping(game,evidence):
    mapping=hand_groups(game,'equity_2')
    for split in evidence['splits']:
        seat=split['seat'];label=split['group'];suffix=0;new=label+'/split0'
        while new in mapping[seat].values():suffix+=1;new=label+'/split'+str(suffix)
        for hand in split['split_members']:
            if mapping[seat][hand]!=label:raise ValueError('Split trace does not match mapping.')
            mapping[seat][hand]=new
    if evidence['history'] and len(StrategyView(game,mapping).keys)!=evidence['history'][-1]['grouped_strategy_rows']:
        raise ValueError('Recovered row count differs.')
    return mapping


def candidates(game,mapping,policy):
    view=StrategyView(game,mapping);rows=defaultdict(dict)
    for key in sorted(game.keys):
        seat,hand,history=key;label=mapping[seat][hand]
        prior=rows[(seat,label)].get(history)
        if prior is not None and prior!=policy[key]:raise ValueError('Original policy does not respect mapping.')
        rows[(seat,label)][history]=policy[key]
    result=[]
    for seat in range(game.n):
        for a,b in combinations(sorted(set(mapping[seat].values())),2):
            common=rows[(seat,a)].keys() & rows[(seat,b)].keys()
            if not common:continue
            tv=max(sum(abs(x-y) for x,y in zip(rows[(seat,a)][h],rows[(seat,b)][h]))/2 for h in common)
            result.append({'seat':seat,'left':a,'right':b,'max_tv':tv,'freed_rows':len(common)})
    return sorted(result,key=lambda c:(c['max_tv'],-c['freed_rows'],c['seat'],c['left'],c['right']))


def project_merge(game,mapping,policy,candidate):
    seat=candidate['seat'];a=candidate['left'];b=candidate['right']
    if a==b or a not in mapping[seat].values() or b not in mapping[seat].values():raise ValueError('Two existing distinct groups required.')
    merged=[dict(m) for m in mapping]
    for hand,label in merged[seat].items():
        if label==b:merged[seat][hand]=a
    masses=defaultdict(float)
    for texts,w,_ in game.deals:
        for p,t in enumerate(texts):
            if t is not None:masses[(p,t)]+=w
    groups=defaultdict(list)
    for key in sorted(game.keys):groups[(key[0],merged[key[0]][key[1]],key[2])].append(key)
    projected={}
    for group,keys in groups.items():
        mass=sum(masses[(key[0],key[1])] for key in keys)
        count=game.action_counts[keys[0]]
        projected[group]=[sum(masses[(key[0],key[1])]*policy[key][i] for key in keys)/mass for i in range(count)]
    view=StrategyView(game,merged)
    return merged,lift_policy(game,view,projected)


def partition_key(mapping):
    return tuple(tuple(sorted(tuple(sorted(h for h,label in seat.items() if label==g)) for g in set(seat.values()))) for seat in mapping)


def audit_reallocation(game,policy,evidence,*,max_candidates=2,max_tv=.1,method='cfr_plus_native'):
    if type(max_candidates) is not int or not 1<=max_candidates<=4 or type(max_tv) not in (float,int) or not 0<=max_tv<=1:
        raise ValueError('Explicit 1–4 candidate budget and TV 0–1 required.')
    if method not in ('cfr_plus_native','cfr_plus_indexed'):raise ValueError('Explicit CFR+ method required.')
    base_metrics,_=evaluate_policy(game,policy);mapping=recover_mapping(game,evidence)
    ranked=candidates(game,mapping,policy);trials=[]
    for candidate in [c for c in ranked if c['max_tv']<=max_tv][:max_candidates]:
        merged,projected=project_merge(game,mapping,policy,candidate)
        metrics,records=evaluate_policy(game,projected)
        delta=metrics['max_unilateral_gain_pct_pot']-base_metrics['max_unilateral_gain_pct_pot']
        trial={'candidate':candidate,'merged_rows':len(StrategyView(game,merged).keys),
               'merge_metrics':metrics,'merge_gain_delta_pct_pot':delta,'non_worsening':delta<=1e-10}
        # TV is just a prescreen. Never reallocate after a measured regression.
        if delta<=1e-10:
            proposal=propose_targeted_split(game,merged,records,evidence['limits']['max_groups_per_seat'],evidence['limits']['max_strategy_rows'],metrics)
            if proposal is None:trial['resplit_status']='no_split'
            elif partition_key(proposal['mapping'])==partition_key(mapping):trial['resplit_status']='undo_rejected'
            else:
                updated=proposal.pop('mapping');view=StrategyView(game,updated)
                grouped=(train_native if method=='cfr_plus_native' else train_indexed)(view,evidence['limits']['iterations_per_round'])
                lifted=lift_policy(game,view,grouped);after,_=evaluate_policy(game,lifted)
                trial.update(resplit_status='evaluated',resplit=proposal,final_rows=len(view.keys),final_metrics=after,
                    passes_quality_gate=after['max_unilateral_gain_pct_pot']<=evidence['limits']['quality_gate_pct_pot'])
        else:trial['resplit_status']='merge_regression'
        trials.append(trial)
    return {'baseline_metrics':base_metrics,'original_rows':len(StrategyView(game,mapping).keys),
        'ranked_candidates':ranked,'limits':{'max_candidates':max_candidates,'max_tv':max_tv},'trials':trials,
        'live_advice_allowed':False,'scope':'Up to two projected merges and one retraining per candidate; diagnostic, not automatic policy replacement.'}
