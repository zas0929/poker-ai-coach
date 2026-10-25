"""Explicit small models of a saved, completed trainer decision. No final cards."""
from copy import deepcopy
import random

from app.models.poker import HandState
from app.services.solver_snapshot import prepare_solver_snapshot, card_text
from research.analysis_contract import validate_request, expected_root_actions
from research.river_snapshot import build_river_from_snapshot, combo_key, digest

MODEL_VERSION = 'completed_river_subset_v1'


def source(saved):
    state = HandState.model_validate(saved['hand'])
    if state.result is not None or state.street.value != 'river' or state.current_player_id != 'hero':
        raise ValueError('An original river decision is required.')
    # Defence in depth: discard any opponent cards even if a legacy payload has them.
    for player in state.players:
        if player.id != 'hero':
            player.cards = []
    hero = next(p for p in state.players if p.id == 'hero')
    if len(hero.cards) != 2:
        raise ValueError('The saved own hand is unavailable.')
    snapshot = prepare_solver_snapshot(state)
    hand = ''.join(card_text(c) for c in hero.cards)
    # Preserve the public range's canonical ordering for the own-hand probe.
    hand = next(r['cards'] for r in next(p for p in snapshot['players'] if p['id']=='hero')['range'] if combo_key(r['cards']) == combo_key(hand))
    version = digest({'model': MODEL_VERSION, 'decision_id': saved['decision_id'], 'snapshot': snapshot,
                      'own_hand': hand, 'chosen_action': saved['chosen_action'], 'amount': saved['amount']})
    selected = {}; used = set()
    for player in snapshot['players']:
        if player['status'] == 'folded':
            continue
        # Suggestions depend on public data only, never the opponent's dealt hand
        # or hero's cards. The actor's own probe is inserted only in their range.
        rng = random.Random(snapshot['information_key']+player['id'])
        selected[player['id']] = []
        for _ in range(2):
            choices = sorted(row['cards'] for row in player['range'] if not set(combo_key(row['cards'])) & used)
            choice = rng.choice(choices); selected[player['id']].append(choice); used.update(combo_key(choice))
    # Insert known cards only after suggestions for ALL other seats are fixed.
    if hand not in selected['hero']:
        selected['hero'][0] = hand
    ceiling = max(p['stack']+p['street_committed'] for p in snapshot['players'] if p['status']!='folded')
    bets = sorted({min(ceiling,state.big_blind),min(ceiling,max(state.big_blind,state.pot//2))})
    current = max(p.current_bet for p in state.players)
    facing = current > hero.current_bet
    minimum = state.betting.min_raise_to if state.betting else None
    raises = [min(ceiling,minimum or current+max(state.last_full_raise,state.big_blind))] if facing else []
    if saved['chosen_action']=='bet' and saved['amount'] is not None:
        bets=sorted({bets[0],saved['amount']})
    if saved['chosen_action']=='raise' and saved['amount'] is not None:
        raises=sorted({*raises,saved['amount']})
    model = {'selected_hands':selected,'bet_sizes':bets,'raise_sizes':raises,'max_raises':int(bool(raises))}
    return snapshot, hand, version, model


def assess(saved, snapshot, hand, version, model):
    selected=deepcopy(model['selected_hands'])
    view={'id':f"decision-{saved['decision_id']}", 'opponents':snapshot['live_player_count']-1,
          'board':snapshot['board'],'own_hand':hand,'actor_id':snapshot['actor_id'],
          'button_id':snapshot['button_id'],'pot':snapshot['pot'],'small_blind':snapshot['small_blind'],
          'big_blind':snapshot['big_blind'],'players':[{k:v for k,v in p.items() if k!='range'} for p in snapshot['players']], 'actions':[],
          'tree':{'bet_sizes':model['bet_sizes'],'raise_sizes':model['raise_sizes'],'max_raises':model['max_raises']}}
    output={'source_version':version,'lesson':view,'model':deepcopy(model),'coverage':[],
            'supported':False,'reason':None,'chosen_action':saved['chosen_action'],'chosen_amount':saved['amount'],
            'decision_id':saved['decision_id'],'hand_id':saved['hand']['hand_id'],
            'completed_at':saved['completed_at'], 'version':None,
            'heuristic_action':saved['analysis'].get('recommended_action'),
            'heuristic_amount':saved['analysis'].get('recommended_amount')}
    live={p['id'] for p in snapshot['players'] if p['status']!='folded'}
    if set(selected)!=live or any(type(v) is not list or len(v)!=2 for v in selected.values()):
        output['reason']='HISTORY_SELECT_TWO_HANDS';return output,None
    canonical={}
    for player in snapshot['players']:
        public={combo_key(r['cards']):r for r in player.get('range',[])}
        rows=[]
        if player['id'] in live:
            try:
                keys=[combo_key(c) for c in selected[player['id']]]
                if len(set(keys))!=2 or any(k not in public for k in keys):
                    raise ValueError('Invalid range selection.')
                rows=[public[k] for k in keys]
                canonical[player['id']]=[r['cards'] for r in rows]
            except ValueError:
                output['reason']='HISTORY_INVALID_HANDS';return output,None
            output['coverage'].append({'player_id':player['id'],'public_combos':len(public),'selected_combos':2,
                'weight_share':sum(r['weight'] for r in rows)/sum(r['weight'] for r in public.values())})
        if rows:
            view['players'][player['seat']]['range']=rows
    if hand not in canonical.get('hero',[]):
        output['reason']='HISTORY_OWN_HAND_REQUIRED';return output,None
    request={'snapshot':snapshot,'selected_hands':canonical,'own_hand':hand,
             'input':{**view['tree'],'max_nodes':4000,'max_joint_combos':64,'utility_storage':'compact'}}
    try:
        validate_request(request)
        game, _=build_river_from_snapshot(snapshot,canonical,**request['input'])
        if not any(texts[game.root.actor]==hand for texts,_,_ in game.deals):
            output['reason']='HISTORY_CARD_COLLISIONS';return output,None
        view['actions']=expected_root_actions(request)
    except ValueError as error:
        message=str(error)
        output['reason']=('HISTORY_CARD_COLLISIONS' if 'No positive compatible joint deal' in message else
                          'HISTORY_TREE_TOO_LARGE' if 'node budget' in message or 'one million' in message else
                          'HISTORY_UNSUPPORTED_TREE')
        return output,None
    output.update(supported=True,version=digest(request))
    output['model']['selected_hands']=canonical
    output['joint_deals']=len(game.deals);output['public_nodes']=len(game.nodes)
    return output,request
