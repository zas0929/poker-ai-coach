"""Offline current-coach vs bounded river policy. Never changes live advice.
Own hands are explicit public-subset probes; opponent holdings are never supplied.
"""
import argparse
import json
import sys
import time
from app.models.poker import HandState,Player,HandAction,Street,PlayerStatus
from app.services.decision_engine import DecisionEngine
from app.services.equity_service import EquityEstimate
from research.river_reference import cards
from research.river_snapshot import build_river_from_snapshot
from research.benchmark_capacity import peak_rss_mib
from research.benchmark_expanded import run_guarded
from research.benchmark_midriver_ranges import scenarios,make_case


def decision_state(snapshot,game,own_hand):
    """Reconstruct public state plus ONE acting player's explicit probe hand."""
    actor=snapshot['actor_id'];ids=[p['id'] for p in snapshot['players']]
    return HandState(hand_id='offline-'+snapshot['information_key'],street=Street.RIVER,
        board=cards(''.join(snapshot['board'])),pot=snapshot['pot'],
        small_blind=snapshot['small_blind'],big_blind=snapshot['big_blind'],
        dealer_player_id=snapshot['button_id'],current_player_id=actor,
        players=[Player(id=p['id'],name=p['id'],position=p['position'],stack=p['stack'],
                        status=PlayerStatus(p['status']),current_bet=p['street_committed'],
                        cards=cards(own_hand) if p['id']==actor else []) for p in snapshot['players']],
        history=[HandAction(player_id=a['player_id'],action=a['action'],amount=a['amount_added'],street=Street(a['street'])) for a in snapshot['history']],
        contributions={p['id']:p['total_committed'] for p in snapshot['players']},
        last_full_raise=game.root_state.increment,
        acted_at_bet={ids[i]:v for i,v in enumerate(game.root_state.acted) if v is not None})


def conditional_deals(game,hand):
    actor=game.root.actor
    rows=[(d,w) for d,(texts,w,_) in enumerate(game.deals) if texts[actor]==hand]
    mass=sum(w for _,w in rows)
    if not mass:raise ValueError('Probe hand has no compatible joint deal.')
    return [(d,w/mass) for d,w in rows],mass


def subset_equity(game,hand):
    rows,_=conditional_deals(game,hand);actor=game.root.actor;equity=0.
    for d,w in rows:
        scores=game.deals[d][2];best=max(scores[p] for p in game.live)
        if scores[actor]==best:equity+=w/sum(scores[p]==best for p in game.live)
    return equity,len(rows)


class SubsetEquity:
    """Controlled experiment only: unchanged coach rules, exact subset showdown share."""
    def __init__(self,value,samples):self.value=value;self.samples=samples
    def estimate(self,*args,**kwargs):
        return EquityEstimate(round(self.value,4),'research_exact_subset_river',self.samples,0.)


def action_label(analysis):
    label=analysis.recommended_action.upper()
    return label+' '+str(analysis.recommended_amount) if label in ('BET','RAISE') else label


def root_action_values(game,policy,hand,best_response=False):
    """Own hand conditional EV; optional optimal future replies, never per-deal max."""
    rows,mass=conditional_deals(game,hand);actor=game.root.actor
    sunk=game.initial_contributions[actor]+game.root_state.invested[actor]
    def value(node,weights):
        if node.actor==-1:
            return sum(w*(game.utilities[(id(node),d)][actor]+sunk) for d,w in weights)
        if node.actor==actor:
            values=[value(child,weights) for child in node.children]
            if best_response:return max(values)
            strategy=policy[game.key(node,weights[0][0])]
            return sum(p*v for p,v in zip(strategy,values))
        return sum(value(child,[(d,w*policy[game.key(node,d)][a]) for d,w in weights])
                   for a,child in enumerate(node.children))
    return [value(child,rows) for child in game.root.children],mass


def compare_hand(game,policy,hand,analyses):
    fixed,mass=root_action_values(game,policy,hand)
    values,_=root_action_values(game,policy,hand,best_response=True)
    strategy=policy[(game.root.actor,hand,game.root.history)];best=max(values)
    arms={}
    for name,analysis in analyses.items():
        action=action_label(analysis)
        represented=action in game.root.actions
        arms[name]={'action':action,'equity':analysis.equity,'equity_method':analysis.equity_method,
                    'equity_samples':getattr(analysis,'equity_samples',None),
                    'equity_sampling_error':getattr(analysis,'equity_sampling_error',None),
                    'required_equity':analysis.required_equity,'represented_exactly':represented,
                    'action_ev_chips':values[game.root.actions.index(action)] if represented else None,
                    'one_decision_loss_chips':max(0.,best-values[game.root.actions.index(action)]) if represented else None}
    return {'own_hand':hand,'conditional_mass':mass,'actions':game.root.actions,
            'action_ev_chips':values,'fixed_policy_action_ev_chips':fixed,'solver_policy':strategy,'best_response_continuation_actions':[a for a,v in zip(game.root.actions,values) if abs(v-best)<1e-8],
            'solver_mixture_ev_chips':sum(p*v for p,v in zip(strategy,fixed)),
            'best_response_continuation_ev_chips':best,'coach':arms}


def worker(case,iterations=100,method='cfr_plus_native'):
    def progress(phase):print(json.dumps({'phase':phase,'observed_peak_rss_mib':peak_rss_mib()}),flush=True)
    started=time.perf_counter();snapshot=case['snapshot'];progress('validate')
    try:base,metadata=build_river_from_snapshot(snapshot,case['selected_hands'],**case['input'])
    except ValueError as error:return {'status':'rejected','reason':str(error),'peak_rss_mib':peak_rss_mib()}
    progress('coach');coach=DecisionEngine();analyses={};targets={'BET':set(case['input']['bet_sizes']),'RAISE':set(case['input']['raise_sizes'])}
    for hand,_ in base.ranges[base.root.actor]:
        try:equity,samples=subset_equity(base,hand)
        except ValueError:continue
        state=decision_state(snapshot,base,hand)
        analyses[hand]={'current_full_ranges':coach.analyze(state,snapshot['actor_id']),
                        'same_subset_rules':DecisionEngine(equity_service=SubsetEquity(equity,samples)).analyze(state,snapshot['actor_id'])}
        for analysis in analyses[hand].values():
            if analysis.recommended_action in ('bet','raise'):
                targets[analysis.recommended_action.upper()].add(analysis.recommended_amount)
    coach_seconds=time.perf_counter()-started
    config={**case['input'],'bet_sizes':sorted(targets['BET']),'raise_sizes':sorted(targets['RAISE'])}
    progress('build');start=time.perf_counter()
    try:game,metadata=build_river_from_snapshot(snapshot,case['selected_hands'],**config)
    except ValueError as error:return {'status':'rejected','reason':str(error),'peak_rss_mib':peak_rss_mib()}
    build=time.perf_counter()-start
    progress('train');start=time.perf_counter();policy=game.train(iterations,method=method);train=time.perf_counter()-start
    progress('measure');start=time.perf_counter();metrics=game.measure(policy)
    rows=[compare_hand(game,policy,hand,analysis) for hand,analysis in analyses.items()]
    summary={}
    for arm in ('current_full_ranges','same_subset_rules'):
        mapped=[r for r in rows if r['coach'][arm]['represented_exactly']]
        summary[arm]={'probes':len(rows),'exactly_represented':len(mapped),
            'weighted_one_decision_loss_chips':sum(r['conditional_mass']*r['coach'][arm]['one_decision_loss_chips'] for r in mapped) if len(mapped)==len(rows) else None,
            'best_action_matches':sum(r['coach'][arm]['action'] in r['best_response_continuation_actions'] for r in mapped)}
    return {'status':'completed','method':method,'coach_and_validation_seconds':coach_seconds,'build_seconds':build,
        'train_seconds':train,'measure_seconds':time.perf_counter()-start,'peak_rss_mib':peak_rss_mib(),
        'public_nodes':len(game.nodes),'joint_deals':len(game.deals),'metadata':metadata,'effective_config':config,
        'metrics':metrics,'passes_quality_gate':metrics['max_unilateral_gain_pct_pot']<=.5,
        'comparisons':rows,'comparison_summary':summary}


def corpus():
    names={'dry_2','dry_3','dry_4','dry_5','dry_6','river_fold_4','prior_allin_3','short_reopened_4'}
    for case in scenarios():
        if case['name'] in names:yield case
    yield make_case('checked_to_3',3,[5]*3,20261046,actions=[('check',None)])


def benchmark(iterations=100,names=None):
    cases=list(corpus())
    if names is not None:
        if not names or len(set(names))!=len(names) or set(names)-{c['name'] for c in cases}:raise ValueError('Distinct known nonempty case names required.')
        cases=[c for c in cases if c['name'] in names]
    rows=[]
    for case in cases:
        print('Starting '+case['name'],file=sys.stderr,flush=True)
        result=run_guarded(case,iterations,60,128,method='cfr_plus_native',worker_module='research.compare_coach')
        rows.append({'name':case['name'],'seed':case['seed'],'source_information_key':case['snapshot']['information_key'],
                     'selected_public_weights':case['selected_public_weights'],**result})
        print(case['name']+': '+result['status'],file=sys.stderr,flush=True)
    completed=[r for r in rows if r['status']=='completed']
    return {'iterations':iterations,'scope':'Offline current full-range coach and controlled same-subset rules vs bounded native policy. First-action constraint loss with optimal own future replies vs learned opponent continuations; not exploitability of the coach or evidence of full-game superiority.',
            'timeout_seconds':60,'memory_mib':128,'quality_gate_pct_decision_pot':.5,'results':rows,
            'summary':{'total':len(rows),'completed':len(completed),'quality_passed':sum(r['passes_quality_gate'] for r in completed)}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--worker',action='store_true')
    parser.add_argument('--iterations',type=int,default=100);parser.add_argument('--method',default='cfr_plus_native',choices=['cfr_plus_native','cfr_plus_indexed'])
    parser.add_argument('--cases',nargs='+');args=parser.parse_args()
    if not 1<=args.iterations<=2000:parser.error('1–2000 iterations required.')
    result=worker(json.load(sys.stdin),args.iterations,args.method) if args.worker else benchmark(args.iterations,args.cases)
    print(json.dumps(result,indent=None if args.worker else 2),flush=True)
