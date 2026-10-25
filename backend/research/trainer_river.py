"""Training-only live position adapter around the frozen small-game calculation.

The worker's offline admission is not changed. A separate envelope exposes its
verified numbers as a limited model of the current TRAINING decision, retaining
heuristic advice. No access to opponent cards, deck or archived future cards.
"""
from collections import OrderedDict
from copy import deepcopy
import random
import secrets
from threading import RLock

from app.services.solver_snapshot import card_text, prepare_solver_snapshot
from app.services.trainer_solver import position_key
from research.analysis_contract import validate_request, expected_root_actions, valid_candidate, finite_number
from research.lesson_values import valid_values
from research.river_snapshot import combo_key, digest
from research.river_lessons import LessonError

VERSION = 'trainer_current_river_v1'


def prepare(state):
    key = position_key(state)
    base = {'contract_version': VERSION, 'position_key': key, 'hand_id': state.hand_id,
            'ticket_id': None, 'state': 'unsupported', 'reason': 'RIVER_HERO_TURN_REQUIRED',
            'model': None, 'quality': None, 'actions': None, 'replaces_heuristic': False}
    if state.result is not None or state.street.value != 'river' or state.current_player_id != 'hero':
        return base, None
    try:
        # No other holdings/private deck are allowed even inside this adapter.
        if any(p.cards for p in state.players if p.id != 'hero') or state._deck:
            raise ValueError('Only a sanitized current decision is accepted.')
        snapshot = prepare_solver_snapshot(state)
        hero = next(p for p in state.players if p.id == 'hero')
        known = combo_key(''.join(card_text(c) for c in hero.cards))
        own = next(row['cards'] for p in snapshot['players'] if p['id'] == 'hero'
                   for row in p['range'] if combo_key(row['cards']) == known)
        selected, used = {}, set()
        for player in snapshot['players']:
            if player['status'] == 'folded':
                continue
            rng = random.Random(VERSION + snapshot['information_key'] + player['id'])
            selected[player['id']] = []
            for _ in range(2):
                choices = sorted(row['cards'] for row in player['range']
                                 if not set(combo_key(row['cards'])) & used)
                choice = rng.choice(choices)
                selected[player['id']].append(choice)
                used.update(combo_key(choice))
        # Opponent suggestions are fixed from public data before the known probe.
        if own not in selected['hero']:
            selected['hero'][0] = own
        coverage, players = [], []
        for player in snapshot['players']:
            view = {k: v for k, v in player.items() if k != 'range'}
            if player['status'] != 'folded':
                public = {combo_key(row['cards']): row for row in player['range']}
                rows = [public[combo_key(c)] for c in selected[player['id']]]
                selected[player['id']] = [row['cards'] for row in rows]
                view['range'] = rows
                coverage.append({'player_id': player['id'], 'selected_combos': len(rows),
                                 'public_combos': len(public),
                                 'weight_share': sum(r['weight'] for r in rows) / sum(r['weight'] for r in public.values())})
            players.append(view)
        ceiling = min(10000, max(p['stack'] + p['street_committed'] for p in snapshot['players']
                                 if p['status'] != 'folded'))
        bet = min(ceiling, max(state.big_blind, state.pot // 2))
        current = max(p.current_bet for p in state.players)
        raise_to = min(ceiling, current + max(state.last_full_raise, state.big_blind) if current else 2 * bet)
        tree = {'bet_sizes': [bet], 'raise_sizes': [raise_to] if raise_to > current else [],
                'max_raises': int(raise_to > current), 'max_nodes': 4000,
                'max_joint_combos': 64, 'utility_storage': 'compact'}
        request = {'snapshot': snapshot, 'selected_hands': selected, 'own_hand': own, 'input': tree}
        validate_request(request)
        actions = expected_root_actions(request)
        model = {'version': VERSION, 'board': snapshot['board'], 'own_hand': own, 'actor_id': 'hero',
                 'pot': snapshot['pot'], 'players': players, 'tree': tree, 'actions': actions,
                 'coverage': coverage, 'range_model': snapshot['range_model'],
                 'scope': 'two_hands_per_live_seat_one_future_raise_no_rake_no_icm'}
        return {**base, 'state': 'prepared', 'reason': None, 'model': model}, request
    except (ValueError, KeyError, TypeError, StopIteration, IndexError):
        return {**base, 'reason': 'CURRENT_RIVER_UNSUPPORTED'}, None


class TrainerRiver:
    def __init__(self, executor, limits):
        self.executor, self.limits = executor, limits
        self.owners = OrderedDict()
        self.lock = RLock()

    def submit(self, owner, nonce, assessment, request):
        if not owner:
            raise LessonError('PROFILE_REQUIRED', 401)
        if request is None:
            return assessment
        with self.lock:
            previous = self.owners.get(owner)
            identity = digest(request)
            if previous and not previous.get('invalidated') and previous['assessment']['position_key'] == assessment['position_key'] and previous['identity'] == identity:
                state = self.executor.poll(previous['internal'])['state']
                if state not in ('cancelled', 'stale', 'error', 'expired'):
                    # UI leases share a job. An old DELETE releases only its lease.
                    if nonce not in previous['handles']:
                        if len(previous['handles']) >= 8:
                            return {**assessment, 'state': 'busy', 'reason': 'TRAINER_SOLVER_BUSY'}
                        previous['handles'][nonce] = secrets.token_hex(24)
                    self.owners.move_to_end(owner)
                    return self._view(previous, previous['handles'][nonce])
            if owner not in self.owners:
                while len(self.owners) >= 64:
                    victim = next((p for p, row in self.owners.items()
                                   if self.executor.poll(row['internal'])['state'] not in ('queued', 'running')), None)
                    if victim is None:
                        return {**assessment, 'state': 'busy', 'reason': 'TRAINER_SOLVER_BUSY'}
                    self.owners.pop(victim)
            if previous:
                self.executor.cancel(previous['internal'])
            job = self.executor.submit('trainer-current:' + owner, request, self.limits)
            if not job.get('ticket_id'):
                return {**assessment, 'state': 'busy', 'reason': 'TRAINER_SOLVER_BUSY'}
            item = {'assessment': deepcopy(assessment), 'request': request, 'identity': identity,
                    'internal': job['ticket_id'], 'handles': {nonce: secrets.token_hex(24)}, 'invalidated': False}
            self.owners[owner] = item
            self.owners.move_to_end(owner)
            return self._view(item, item['handles'][nonce])

    def _view(self, item, handle):
        job = self.executor.poll(item['internal'])
        result = job.get('result')
        output = {**deepcopy(item['assessment']), 'ticket_id': handle, 'state': job['state']}
        if job['state'] in ('queued', 'running'):
            return output
        output.update(state=job['state'] if job['state'] != 'completed' else 'unavailable',
                      reason='CURRENT_RIVER_UNAVAILABLE')
        if job['state'] != 'completed' or not isinstance(result, dict):
            return output
        request = item['request']
        if result.get('request_key') != item['identity'] or result.get('source_information_key') != request['snapshot']['information_key']:
            return output
        if result.get('status') != 'ready':
            output['reason'] = (result.get('reasons') or [{'code': 'CURRENT_RIVER_UNAVAILABLE'}])[0]['code']
            return output
        candidate, values, quality = result.get('candidate'), result.get('action_values'), result.get('quality')
        if (not isinstance(quality, dict) or quality.get('passed') is not True
                or not finite_number(quality.get('value')) or not finite_number(quality.get('gate'))
                or quality['gate'] != self.limits.quality_gate_pct_pot or not 0 <= quality['value'] <= quality['gate']
                or result.get('admission') != {'offline_analysis_allowed': True, 'live_advice_allowed': False}
                or not valid_candidate(candidate, request) or not valid_values(values, candidate, request)):
            return output
        output.update(state='ready', reason=None, quality=quality,
                      actions=[{'action': action, 'probability': p, 'ev_chips': value,
                                'gap_chips': gap} for action, p, value, gap in
                               zip(candidate['actions'], candidate['probabilities'], values['ev_chips'], values['gap_to_best_chips'])])
        return output

    def poll(self, owner, handle, key):
        with self.lock:
            item = self.owners.get(owner)
            if item is None or handle not in item['handles'].values():
                raise LessonError('TRAINER_SOLVER_NOT_FOUND', 404)
            if item.get('invalidated') or item['assessment']['position_key'] != key:
                self.executor.cancel(item['internal'])
                return {**deepcopy(item['assessment']), 'ticket_id': handle, 'state': 'stale',
                        'reason': 'STALE_DECISION', 'actions': None, 'quality': None}
            return self._view(item, handle)

    def cancel(self, owner, handle):
        with self.lock:
            item = self.owners.get(owner)
            if item is None or handle not in item['handles'].values():
                raise LessonError('TRAINER_SOLVER_NOT_FOUND', 404)
            nonce = next(nonce for nonce, value in item['handles'].items() if value == handle)
            item['handles'].pop(nonce)
            if not item['handles']:
                self.executor.cancel(item['internal'])
                item['invalidated'] = True
            return {'ticket_id': handle, 'state': 'cancelled'}

    def observe(self, owner, key):
        with self.lock:
            item = self.owners.get(owner)
            if item is not None and item['assessment']['position_key'] != key:
                self.executor.cancel(item['internal'])
                item['invalidated'] = True

    def close(self):
        with self.lock:
            for item in self.owners.values():
                self.executor.cancel(item['internal'])
            self.owners.clear()
