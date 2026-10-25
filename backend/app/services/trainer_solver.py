"""Opt-in training-only current-decision model; no research import while disabled."""
from hashlib import sha256
import json
import logging
import os

_service = None


def position_text(state):
    """Stable wire identity shared with the browser; excludes bots' cards/deck."""
    if state is None:
        return 'null'
    return json.dumps([
        state.hand_id, state.street.value, state.current_player_id, state.dealer_player_id,
        state.small_blind, state.big_blind, state.last_full_raise, state.pot,
        [[c.rank.value, c.suit.value] for c in state.board],
        [[p.id, p.stack, p.current_bet, p.status.value, p.position] for p in state.players],
        [[a.player_id, a.action, a.amount, a.street.value] for a in state.history],
        sorted(state.contributions.items()), sorted(state.acted_at_bet.items()),
        [[[c.rank.value, c.suit.value] for c in p.cards] for p in state.players if p.id == 'hero'],
        state.result is not None,
    ], ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def position_key(state):
    return sha256(position_text(state).encode()).hexdigest()


def public_copy(state):
    data = state.model_dump(exclude={'players': {'__all__': {'cards'}}})
    for original, player in zip(state.players, data['players']):
        player['cards'] = [c.model_dump() for c in original.cards] if original.id == 'hero' else []
    return type(state).model_validate(data)  # Private deck/seed never copied.


def start_trainer_solver():
    global _service
    if _service is not None:
        return True
    from app.services.river_lessons import service
    lessons = service()
    if lessons is None or os.environ.get('POKER_TRAINER_SOLVER_ENABLED', '1') != '1':
        return False
    try:
        from research.trainer_river import TrainerRiver
        _service = TrainerRiver(lessons.executor, lessons.limits)
        return True
    except Exception:
        logging.getLogger(__name__).warning('TRAINER_SOLVER_UNAVAILABLE')
        return False


def stop_trainer_solver():
    global _service
    current, _service = _service, None
    if current is not None:
        current.close()  # Cancels its subscriptions; shared executor is owned by lessons.


def service():
    return _service


def observe(owner, state):
    if _service is not None and owner:
        try:
            _service.observe(owner, position_key(state))
        except Exception:
            logging.getLogger(__name__).warning('TRAINER_SOLVER_OBSERVE_FAILED')
