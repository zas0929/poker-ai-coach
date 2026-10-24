"""Equivalent adaptive loop using fused evaluation and indexed split selection.
The frozen reference remains in adaptive_strategy.py for paired validation.
"""
import math
from research.strategy_abstraction import StrategyView,hand_groups,lift_policy
from research.indexed_split import propose_split_indexed as propose_split
from research.fused_best_response import evaluate_policy
from research.indexed_cfr import train_indexed
from research.native_cfr import train_native


def train_adaptive_indexed(game,*,iterations=100,max_splits=12,max_groups_per_seat=8,
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
        last=lift_policy(game,view,trained);metrics,records=evaluate_policy(game,last)
        history.append({'round':round_index,'grouped_strategy_rows':len(view.keys),
                        'hand_group_counts':[len(set(m.values())) for m in mapping],
                        'max_unilateral_gain_pct_pot':metrics['max_unilateral_gain_pct_pot']})
        if metrics['max_unilateral_gain_pct_pot']<=quality_gate_pct_pot:reason='quality_passed';break
        if round_index==max_splits:reason='split_budget_exhausted';break
        proposal=propose_split(game,mapping,records,max_groups_per_seat,max_strategy_rows)
        if proposal is None:reason='no_split_within_budget';break
        mapping=proposal.pop('mapping');splits.append(proposal)
    return last,{'status':'ready' if reason=='quality_passed' else 'rejected','reason':reason,
        'history':history,'splits':splits,'metrics_original_game':metrics,
        'original_strategy_rows':len(game.keys),'limits':{'iterations_per_round':iterations,'max_splits':max_splits,
            'max_groups_per_seat':max_groups_per_seat,'max_strategy_rows':max_strategy_rows,'quality_gate_pct_pot':quality_gate_pct_pot},
        'live_advice_allowed':False,'scope':'Offline original-game unilateral-gain gate only. Full deals and tree unchanged.'}
