from __future__ import annotations

from typing import Optional, Literal
from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, StrictInt

from app.api import hand as live
from app.api.rooms import store as room_store
from app.models.poker import ActionType
from app.services.training_store import TrainingStore

router = APIRouter()
store = TrainingStore(room_store.repository.source)


class SavedAction(BaseModel):
    command_id: str = Field(min_length=1, max_length=80)
    hand_id: str = Field(min_length=1, max_length=80)
    history_length: StrictInt = Field(ge=0)
    action: ActionType
    amount: Optional[StrictInt] = None

    class Config:
        extra = 'forbid'


class ExerciseAnswer(BaseModel):
    question_id: str = Field(min_length=1, max_length=80)
    attempt_id: str = Field(min_length=1, max_length=80)
    percent: Optional[float] = Field(default=None, strict=True, ge=0, le=100, allow_inf_nan=False)
    actions: Optional[list[ActionType]] = Field(default=None, max_length=5)

    class Config:
        extra = 'forbid'


def profile(authorization):
    try:
        token = authorization[7:] if isinstance(authorization, str) and authorization.startswith('Bearer ') else None
        return store.authenticate(token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def private(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Authorization'


@router.post('/profiles')
def create_profile(response: Response):
    private(response)
    return store.create_profile()


@router.get('/progress')
def read_progress(response: Response, authorization: Optional[str] = Header(default=None)):
    private(response)
    return store.progress(profile(authorization))


@router.post('/decision')
@live.serialized
def save_action(request: SavedAction, response: Response, authorization: Optional[str] = Header(default=None)):
    private(response)
    owner = profile(authorization)
    fingerprint = request.model_dump_json()
    with live.state_lock:
        try:
            cached = store.cached_decision(owner, request.command_id, fingerprint)
            if cached:
                if live.current_state is None:
                    raise HTTPException(status_code=409, detail='Training table restarted. Your decision is saved; start a new hand.')
                return {'state': live.current_state, 'review': cached['review'], 'decision_id': cached['decision_id']}
            state = live.get_current_state()
            if state.hand_id != request.hand_id or len(state.history) != request.history_length:
                raise HTTPException(status_code=409, detail='Training table changed. The latest state must be loaded before choosing again.')
            if state.current_player_id != 'hero':
                raise ValueError('It is not your turn.')
            # Validate on a detached copy. A failed database write cannot consume chips.
            following = live.engine.apply_action(state.model_copy(deep=True), 'hero', request.action, request.amount)
            analysis = live.decision_engine.analyze(state, 'hero')
            saved = store.save_decision(owner, request.command_id, fingerprint, state, analysis, request.action, request.amount)
            live.current_state = following
            return {'state': following, 'review': saved['review'], 'decision_id': saved['decision_id']}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/decisions')
def decisions(response: Response, authorization: Optional[str] = Header(default=None),
              before: Optional[int] = Query(default=None, ge=1, le=9223372036854775807)):
    private(response)
    return store.decisions(profile(authorization), before)


@router.get('/exercises/next')
def next_exercise(kind: Literal['call_price', 'legal_actions'], response: Response,
                  authorization: Optional[str] = Header(default=None),
                  exclude: Optional[str] = Query(default=None, max_length=80)):
    private(response)
    try:
        return store.next_question(profile(authorization), kind, exclude)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get('/exercises/{question_id}')
def read_exercise(question_id: str, response: Response, authorization: Optional[str] = Header(default=None)):
    private(response)
    try:
        return store.question(profile(authorization), question_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post('/answers')
def answer(request: ExerciseAnswer, response: Response, authorization: Optional[str] = Header(default=None)):
    private(response)
    try:
        return store.answer(profile(authorization), request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
