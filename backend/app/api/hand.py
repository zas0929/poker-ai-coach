from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.poker import ActionType, HandAnalysis, HandState, PlayerActionRequest
from app.services.decision_engine import DecisionEngine
from app.services.poker_engine import PokerEngine

router = APIRouter()

engine = PokerEngine()
decision_engine = DecisionEngine()
current_state: HandState | None = None


def get_current_state() -> HandState:
    if current_state is None:
        raise HTTPException(status_code=404, detail="No active hand. Start a new hand first.")
    return current_state


@router.post("/start", response_model=HandState)
def start_hand():
    global current_state
    current_state = engine.start_hand()
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
    state = get_current_state()

    if state.current_player_id != player_id:
        raise HTTPException(status_code=400, detail=f"It is not {player_id}'s turn.")

    try:
        analysis = decision_engine.analyze(state, player_id=player_id)
        highest_bet = max(player.current_bet for player in state.players)
        amount = None

        if analysis.recommended_action == "bet":
            amount = max(state.big_blind, state.pot // 2)
        elif analysis.recommended_action == "raise":
            amount = max(highest_bet + state.big_blind, highest_bet * 2)

        current_state = engine.apply_action(
            state,
            player_id=player_id,
            action=ActionType(analysis.recommended_action),
            amount=amount,
        )
        current_state.notes.append(
            f"AI chose {analysis.recommended_action} with {analysis.equity:.1%} equity."
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return current_state


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
