"""Current-turn preparation plus the unchanged current-river preparation."""
import random
from dataclasses import asdict

from app.services.solver_snapshot import card_text, prepare_solver_snapshot
from app.services.trainer_solver import position_key
from research import turn_analysis
from research.analysis_contract import finite_number, valid_quality
from research.lesson_values import valid_values
from research.river_snapshot import combo_key, digest
from research.trainer_river import prepare as prepare_river

VERSION = 'trainer_current_turn_v1'


def prepare(state):
    if state.street.value != 'turn':
        return prepare_river(state)
    base = {'contract_version': VERSION, 'position_key': position_key(state), 'hand_id': state.hand_id,
            'ticket_id': None, 'state': 'unsupported', 'reason': 'TURN_HERO_TURN_REQUIRED',
            'model': None, 'quality': None, 'actions': None, 'replaces_heuristic': False}
    if state.result is not None or state.current_player_id != 'hero':
        return base, None
    try:
        if any(p.cards for p in state.players if p.id != 'hero') or state._deck:
            raise ValueError('Only sanitized public decision data accepted.')
        snapshot = prepare_solver_snapshot(state)
        hero = next(p for p in state.players if p.id == 'hero')
        known = combo_key(''.join(card_text(c) for c in hero.cards))
        own = next(r['cards'] for p in snapshot['players'] if p['id'] == 'hero'
                   for r in p['range'] if combo_key(r['cards']) == known)
        selected, used = {}, set()
        for p in snapshot['players']:
            if p['status'] == 'folded':
                continue
            rng = random.Random(VERSION + snapshot['information_key'] + p['id'])
            selected[p['id']] = []
            for _ in range(2):
                choices = sorted(r['cards'] for r in p['range'] if not set(combo_key(r['cards'])) & used)
                choice = rng.choice(choices)
                selected[p['id']].append(choice); used.update(combo_key(choice))
        if own not in selected['hero']:
            selected['hero'][0] = own
        players, coverage = [], []
        for p in snapshot['players']:
            view = {k:v for k,v in p.items() if k != 'range'}
            if p['status'] != 'folded':
                public = {combo_key(r['cards']):r for r in p['range']}
                rows = [public[combo_key(c)] for c in selected[p['id']]]
                selected[p['id']] = [r['cards'] for r in rows]
                view['range'] = rows
                coverage.append({'player_id':p['id'], 'selected_combos':len(rows),
                                 'public_combos':len(public),
                                 'weight_share':sum(r['weight'] for r in rows)/sum(r['weight'] for r in public.values())})
            players.append(view)
        ceiling = min(10000, max(p['stack'] + p['street_committed'] for p in snapshot['players'] if p['status'] != 'folded'))
        bet = max(state.big_blind, min(ceiling, state.pot//2))
        current = max(p.current_bet for p in state.players)
        raise_to = min(ceiling, current + max(state.last_full_raise, state.big_blind) if current else 2*bet)
        # Fixed, visible preset; never retry with truncated ranges/tree after refusal.
        tree = {'turn_bet_sizes':[bet], 'turn_raise_sizes':[raise_to] if raise_to > current else [],
                'turn_max_raises':int(raise_to > current), 'river_bet_sizes':[bet],
                'river_raise_sizes':[], 'river_max_raises':0,
                'max_nodes':1500, 'max_joint_combos':64, 'max_outcomes':3072, 'max_work':200000}
        request = {'snapshot':snapshot, 'selected_hands':selected, 'own_hand':own, 'input':tree}
        turn_analysis.validate_request(request)
        actions = turn_analysis.expected_root_actions(request)
        if not actions:
            raise ValueError('No current turn decision.')
        model = {'version':VERSION, 'street':'turn', 'board':snapshot['board'],
                 'own_hand':own, 'actor_id':'hero', 'pot':snapshot['pot'],
                 'players':players, 'tree':tree, 'actions':actions, 'coverage':coverage,
                 'range_model':snapshot['range_model'],
                 'scope':'two_hands_per_live_seat_all_compatible_rivers_one_turn_raise_no_river_raises_no_rake_no_icm'}
        return {**base, 'state':'prepared', 'reason':None, 'model':model}, request
    except (ValueError, KeyError, TypeError, StopIteration, IndexError):
        return {**base, 'reason':'CURRENT_TURN_UNSUPPORTED'}, None


def valid_turn_result(result, request, limits):
    if (result.get('contract_version') != turn_analysis.CONTRACT_VERSION
            or result.get('scope') != turn_analysis.SCOPE
            or result.get('provenance') != turn_analysis.provenance()
            or result.get('limits') != asdict(limits)
            or result.get('request_key') != digest(request)
            or result.get('source_information_key') != request['snapshot']['information_key']
            or result.get('admission') != {'offline_analysis_allowed':True,'live_advice_allowed':False}
            or result.get('fallback',{}).get('retain_current_advice') is not True):
        return False
    timing = result.get('timing')
    if (not isinstance(timing,dict) or
            any(not finite_number(timing.get(k)) or timing[k] < 0 for k in
                ('wall_seconds','peak_rss_mib','sampled_peak_rss_mib')) or
            timing['wall_seconds'] > limits.wall_seconds or
            max(timing['peak_rss_mib'],timing['sampled_peak_rss_mib']) > limits.memory_mib):
        return False
    model, quality = result.get('model'), result.get('quality')
    if (not isinstance(model,dict) or model.get('source_information_key') != request['snapshot']['information_key']
            or model.get('model_version') != 'bounded-turn-reference-v2'
            or not turn_analysis.valid_tree(model.get('tree'),request)
            or not isinstance(quality,dict) or quality.get('passed') is not True
            or quality.get('metric') != 'max_unilateral_gain_pct_decision_pot'
            or not finite_number(quality.get('value')) or quality.get('gate') != limits.quality_gate_pct_pot
            or not 0 <= quality['value'] <= quality['gate']
            or not valid_quality(quality.get('evidence'),len(request['snapshot']['players']),request['snapshot']['pot'])
            or quality['value'] != quality['evidence']['max_unilateral_gain_pct_pot']):
        return False
    return (turn_analysis.valid_candidate(result.get('candidate'),request)
            and valid_values(result.get('action_values'),result.get('candidate'),request))
