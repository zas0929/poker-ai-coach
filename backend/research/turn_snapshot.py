"""Strict public schema-v1 current-turn adapter. No HandState or private deck."""
import math
from app.services.solver_snapshot import UnsupportedSolverState
from research.analysis_contract import RANGE_VERSION, validate_request
from research.river_snapshot import combo_key, digest
from research.turn_reference import TurnGame


def build_turn_from_snapshot(snapshot, selected_hands, **tree):
    try:
        return _build(snapshot, selected_hands, tree)
    except UnsupportedSolverState:
        raise
    except (ValueError, KeyError, TypeError, IndexError) as error:
        raise UnsupportedSolverState('Unsupported turn model: ' + str(error)) from error


def _build(snapshot, selected, tree):
    actor = snapshot['actor_id']
    # Reuse only the exact PUBLIC envelope whitelist, not river-only admission.
    probe = selected[actor][0]
    validate_request({'snapshot': snapshot, 'selected_hands': selected, 'own_hand': probe, 'input': {}})
    if snapshot['information_key'] != digest({k:v for k,v in snapshot.items() if k != 'information_key'}):
        raise ValueError('Public snapshot digest mismatch.')
    if type(snapshot['schema_version']) is not int or snapshot['schema_version'] != 1 or snapshot['street'] != 'turn' or snapshot['range_model'] != RANGE_VERSION:
        raise ValueError('Schema-v1 turn decision required.')
    players = snapshot['players']; n = len(players); ids = [p['id'] for p in players]
    if (not 2 <= n <= 6 or any(type(pid) is not str or not 1 <= len(pid) <= 80 for pid in ids)
            or len(set(ids)) != n or [p['seat'] for p in players] != list(range(n))
            or any(type(p['seat']) is not int for p in players)
            or snapshot['dealt_player_count'] != n or snapshot['button_id'] not in ids or actor not in ids):
        raise ValueError('Original seats, button and actor required.')
    folded = [i for i,p in enumerate(players) if p['status'] == 'folded']
    live_ids = {p['id'] for p in players if p['status'] != 'folded'}
    if len(live_ids) < 2 or snapshot['live_player_count'] != len(live_ids) or set(selected) != live_ids:
        raise ValueError('Explicit subsets must cover exactly the live seats.')
    for p in players:
        if (p['status'] not in ('active','all_in','folded') or type(p['stack']) is not int or p['stack'] < 0
                or type(p['street_committed']) is not int or p['street_committed'] < 0
                or type(p['total_committed']) is not int or p['total_committed'] < p['street_committed']
                or (p['status'] == 'active' and p['stack'] == 0) or (p['status'] == 'all_in' and p['stack'] != 0)):
            raise ValueError('Public statuses and commitments disagree.')
    if type(snapshot['pot']) is not int or sum(p['total_committed'] for p in players) != snapshot['pot']:
        raise ValueError('Complete public contributions required.')
    if any(type(snapshot[k]) is not int for k in ('small_blind','big_blind')) or not 0 < snapshot['small_blind'] < snapshot['big_blind']:
        raise ValueError('Invalid blinds.')
    button = ids.index(snapshot['button_id'])
    order = [ids[(button+i)%n] for i in range(1,n+1) if ids[(button+i)%n] in live_ids]
    if snapshot['postflop_order'] != order:
        raise ValueError('Postflop order disagrees with original seats.')
    streets = {'preflop':0,'flop':1,'turn':2}; last = 0; folders = []
    for a in snapshot['history']:
        if (a['street'] not in streets or streets[a['street']] < last or a['player_id'] not in ids
                or a['action'] not in ('small_blind','big_blind','check','call','bet','raise','fold')
                or (a['amount_added'] is not None and (type(a['amount_added']) is not int or a['amount_added'] < 0))):
            raise ValueError('Invalid, unordered or future public history.')
        last = streets[a['street']]
        if a['action'] == 'fold': folders.append(ids.index(a['player_id']))
    if len(set(folders)) != len(folders) or set(folders) != set(folded):
        raise ValueError('Fold history disagrees with statuses.')
    ranges, counts = [], []
    for i,p in enumerate(players):
        if i in folded:
            if 'range' in p: raise ValueError('Folded holdings are not modelled.')
            ranges.append([]); counts.append({'id':p['id'],'public':0,'selected':0}); continue
        public = {}
        for row in p['range']:
            key = combo_key(row['cards']); weight = row['weight']
            if (key in public or set(key).intersection(snapshot['board']) or type(weight) not in (int,float)
                    or not math.isfinite(weight) or weight <= 0):
                raise ValueError('Unique legal positively weighted public ranges required.')
            public[key] = (row['cards'], weight)
        chosen = [combo_key(text) for text in selected[p['id']]]
        if not chosen or len(set(chosen)) != len(chosen) or any(key not in public for key in chosen):
            raise ValueError('Explicit selection is outside the public range.')
        ranges.append([public[key] for key in chosen])
        counts.append({'id':p['id'],'public':len(public),'selected':len(chosen)})
    actions = [(ids.index(a['player_id']),a['action'],a['amount_added']) for a in snapshot['history'] if a['street'] == 'turn']
    spec = {'board':snapshot['board'],'ranges':ranges,
            'pot':sum(p['total_committed']-p['street_committed'] for p in players),
            'initial_contributions':[p['total_committed']-p['street_committed'] for p in players],
            'stacks':[p['stack']+p['street_committed'] for p in players],
            'dealer':button,'folded':folded,'turn_actions':actions,'min_bet':snapshot['big_blind'],**tree}
    # Reject overrides of public state even when called directly, outside HTTP.
    if set(tree) - {'turn_bet_sizes','river_bet_sizes','turn_raise_sizes','river_raise_sizes',
                    'turn_max_raises','river_max_raises','max_joint_combos','max_outcomes','max_work','max_nodes'}:
        raise ValueError('Only explicit tree sizes and bounded resource configuration may be overridden.')
    game = TurnGame(**spec)
    if (game.root.actor < 0 or ids[game.root.actor] != actor
            or game.root_state.invested != tuple(p['street_committed'] for p in players)
            or game.decision_pot != snapshot['pot']):
        raise ValueError('Replayed turn does not match the current public decision.')
    return game, {'source_information_key':snapshot['information_key'],'task_key':digest(spec),
                  'model_version':game.model_version,'seat_ids':ids,'actor_id':actor,'range_counts':counts,
                  'observed_raises':game.root_state.raises,'last_full_raise':game.root_state.increment,
                  'future_raise_caps':{'turn':game.turn_max_raises,'river':game.river_max_raises},
                  'prior_pot':game.pot,'decision_pot':game.decision_pot,
                  'folded_card_bunching_modelled':False,'future_river_source':'all_compatible_cards',
                  'scope':'bounded_current_turn_public_subsets_not_full_range_gto'}
