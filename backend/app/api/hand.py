from __future__ import annotations

from fastapi import APIRouter, HTTPException
from functools import wraps
from threading import RLock
from contextvars import ContextVar
from time import monotonic
from typing import Optional

from app.models.poker import HandAnalysis, HandState, PlayerActionRequest, Street
from app.services.ai_opponent import AIOpponentService
from app.services.decision_engine import DecisionEngine
from app.services.poker_engine import PokerEngine
from app.services import trainer_shadow
from app.services.training_completion import observe_completed

router = APIRouter()

engine = PokerEngine()
decision_engine = DecisionEngine()
ai_opponent = AIOpponentService(profile="balanced")
current_state: HandState | None = None
state_lock = RLock()
# HTTP requests bind an authenticated profile; direct engine calls retain the local test session.
training_owner: ContextVar[Optional[str]] = ContextVar('training_owner', default=None)
profile_states: dict[str, tuple[Optional[HandState], float]] = {}
MAX_TRAINING_SESSIONS = 1000
TRAINING_IDLE_SECONDS = 24 * 60 * 60


def serialized(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        global current_state
        with state_lock:
            owner = training_owner.get()
            if owner is None:
                try:
                    return function(*args, **kwargs)
                finally:
                    trainer_shadow.observe(owner, current_state)
            now = monotonic()
            if owner not in profile_states:
                for key, (_, touched) in list(profile_states.items()):
                    if now - touched > TRAINING_IDLE_SECONDS:
                        del profile_states[key]
                if len(profile_states) >= MAX_TRAINING_SESSIONS:
                    raise HTTPException(status_code=503, detail='Training tables are busy. Please retry later.')
            previous = current_state
            current_state = profile_states.get(owner, (None, now))[0]
            try:
                return function(*args, **kwargs)
            finally:
                observe_completed(owner, current_state)
                trainer_shadow.observe(owner, current_state)
                profile_states[owner] = (current_state, monotonic())
                current_state = previous
    return wrapper


def get_current_state() -> HandState:
    if current_state is None:
        raise HTTPException(status_code=404, detail="No active hand. Start a new hand first.")
    return current_state


@router.post("/start", response_model=HandState)
@serialized
def start_hand(player_count: Optional[int] = None, small_blind: Optional[int] = None, big_blind: Optional[int] = None):
    global current_state
    # Refreshing the browser must not discard a live pot or reset its stacks.
    if player_count is not None and (type(player_count) is not int or not 2 <= player_count <= 6):
        raise HTTPException(status_code=400, detail="Choose 2–6 players.")
    small = small_blind if small_blind is not None else current_state.small_blind if current_state else 5
    big = big_blind if big_blind is not None else current_state.big_blind if current_state else 10
    if (type(small) is not int or type(big) is not int
            or not 1 <= small <= 10000 or not 2 <= big <= 20000 or small >= big):
        raise HTTPException(status_code=400, detail="Blinds must be positive integers with small blind below big blind (maximum 10000/20000).")
    if current_state is not None and current_state.result is None:
        if player_count is not None and player_count != len(current_state.players):
            raise HTTPException(status_code=409, detail="Finish the hand before changing table size.")
        if (small, big) != (current_state.small_blind, current_state.big_blind):
            raise HTTPException(status_code=409, detail="Finish the hand before changing blinds.")
        return current_state
    current_state = engine.start_hand(previous_state=current_state, player_count=player_count,
                                      small_blind=small, big_blind=big)
    return current_state


@router.get("/state", response_model=HandState)
@serialized
def read_state():
    return get_current_state()


@serialized
def analysis_snapshot():
    return get_current_state().model_copy(deep=True)


@router.get("/analyze", response_model=HandAnalysis)
def analyze_hand(player_id: str = "hero", hand_id: Optional[str] = None,
                 history_length: Optional[int] = None, street: Optional[Street] = None):
    # Hold the table lock only while copying. A slow hint must not block play.
    state = analysis_snapshot()
    if ((hand_id is not None and state.hand_id != hand_id)
            or (history_length is not None and len(state.history) != history_length)
            or (street is not None and state.street != street)):
        raise HTTPException(status_code=409, detail="Training table changed. The latest state must be loaded before choosing again.")
    try:
        analysis = decision_engine.analyze(state, player_id=player_id)
        trainer_shadow.capture(training_owner.get(), state, analysis)
        return analysis
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/action", response_model=HandState)
@serialized
def apply_action(request: PlayerActionRequest):
    global current_state
    try:
        current_state = engine.apply_action(
            get_current_state(),
            player_id=request.player_id,
            action=request.action,
            amount=request.amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current_state


@router.post("/ai-action", response_model=HandState)
@serialized
def apply_ai_action(player_id: str = "villain"):
    global current_state
    state = engine.settle_all_in_if_ready(get_current_state())
    current_state = state

    if state.result:
        return state

    if state.current_player_id != player_id:
        raise HTTPException(status_code=400, detail=f"It is not {player_id}'s turn.")

    try:
        current_state = _apply_ai_action_to_state(state, player_id=player_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return current_state


@router.post("/auto-play", response_model=HandState)
@serialized
def auto_play_until_hero():
    global current_state
    state = get_current_state()

    try:
        for _ in range(512):
            state = engine.settle_all_in_if_ready(state)
            current_state = state

            if state.result or state.street == Street.SHOWDOWN or state.current_player_id == "hero":
                break

            if state.current_player_id is not None and state.current_player_id != "hero":
                state = _apply_ai_action_to_state(state, player_id=state.current_player_id)
                current_state = state
                continue

            if state.current_player_id is None:
                state = engine.advance(state)
                current_state = state
                continue

            break
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return state


@router.post("/advance", response_model=HandState)
@serialized
def advance_hand():
    global current_state
    try:
        current_state = engine.advance(get_current_state())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current_state


@router.post("/flop", response_model=HandState)
@serialized
def deal_flop():
    global current_state
    try:
        current_state = engine.deal_flop(get_current_state())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current_state


@router.post("/turn", response_model=HandState)
@serialized
def deal_turn():
    global current_state
    try:
        current_state = engine.deal_turn(get_current_state())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current_state


@router.post("/river", response_model=HandState)
@serialized
def deal_river():
    global current_state
    try:
        current_state = engine.deal_river(get_current_state())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current_state


def _apply_ai_action_to_state(state: HandState, player_id: str) -> HandState:
    if state.current_player_id != player_id:
        raise ValueError(f"It is not {player_id}'s turn.")

    analysis = None if state.street == Street.PREFLOP else decision_engine.analyze(state, player_id=player_id)
    decision = ai_opponent.choose_action(state, analysis, player_id=player_id)

    next_state = engine.apply_action(
        state,
        player_id=player_id,
        action=decision.action,
        amount=decision.amount,
    )
    next_state.notes.append(f"{player_id} chose {decision.action.value}.")
    return next_state
