from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.poker import HandAnalysis, HandState, PlayerActionRequest, Street
from app.services.ai_opponent import AIOpponentService
from app.services.decision_engine import DecisionEngine
from app.services.poker_engine import PokerEngine

router = APIRouter()

engine = PokerEngine()
decision_engine = DecisionEngine()
ai_opponent = AIOpponentService(profile="balanced")
current_state: HandState | None = None


def get_current_state() -> HandState:
    if current_state is None:
        raise HTTPException(status_code=404, detail="No active hand. Start a new hand first.")
    return current_state


@router.post("/start", response_model=HandState)
def start_hand():
    global current_state
    # Refreshing the browser must not discard a live pot or reset its stacks.
    if current_state is not None and current_state.result is None:
        return current_state
    current_state = engine.start_hand(previous_state=current_state)
    return current_state


@router.get("/state", response_model=HandState)
def read_state():
    return get_current_state()


@router.get("/analyze", response_model=HandAnalysis)
def analyze_hand(player_id: str = "hero"):
    try:
        return decision_engine.analyze(get_current_state(), player_id=player_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/action", response_model=HandState)
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
def auto_play_until_hero():
    global current_state
    state = get_current_state()

    try:
        for _ in range(12):
            state = engine.settle_all_in_if_ready(state)
            current_state = state

            if state.result or state.street == Street.SHOWDOWN or state.current_player_id == "hero":
                break

            if state.current_player_id == "villain":
                state = _apply_ai_action_to_state(state, player_id="villain")
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
def advance_hand():
    global current_state
    try:
        current_state = engine.advance(get_current_state())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current_state


@router.post("/flop", response_model=HandState)
def deal_flop():
    global current_state
    try:
        current_state = engine.deal_flop(get_current_state())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current_state


@router.post("/turn", response_model=HandState)
def deal_turn():
    global current_state
    try:
        current_state = engine.deal_turn(get_current_state())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current_state


@router.post("/river", response_model=HandState)
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
    next_state.notes.append(
        f"AI chose {decision.action.value} with {analysis.equity:.1%} equity. {decision.reason}"
    )
    return next_state
