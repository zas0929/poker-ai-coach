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
                return function(*args, **kwargs)
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
                profile_states[owner] = (current_state, monotonic())
                current_state = previous
    return wrapper


def get_current_state() -> HandState:
    if current_state is None:
        raise HTTPException(status_code=404, detail="No active hand. Start a new hand first.")
    return current_state


@router.post("/start", response_model=HandState)
@serialized
def start_hand(player_count: Optional[int] = None):
    global current_state
    # Refreshing the browser must not discard a live pot or reset its stacks.
    if player_count is not None and (type(player_count) is not int or not 2 <= player_count <= 6):
        raise HTTPException(status_code=400, detail="Choose 2–6 players.")
    if current_state is not None and current_state.result is None:
        if player_count is not None and player_count != len(current_state.players):
            raise HTTPException(status_code=409, detail="Finish the hand before changing table size.")
        return current_state
    current_state = engine.start_hand(previous_state=current_state, player_count=player_count)
    return current_state


@router.get("/state", response_model=HandState)
@serialized
def read_state():
    return get_current_state()


@router.get("/analyze", response_model=HandAnalysis)
@serialized
def analyze_hand(player_id: str = "hero"):
    try:
        return decision_engine.analyze(get_current_state(), player_id=player_id)
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

    analysis = decision_engine.analyze(state, player_id=player_id)
    decision = ai_opponent.choose_action(state, analysis, player_id=player_id)

    next_state = engine.apply_action(
        state,
        player_id=player_id,
        action=decision.action,
        amount=decision.amount,
    )
    next_state.notes.append(f"{player_id} chose {decision.action.value}.")
    return next_state
