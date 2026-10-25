from fastapi import APIRouter, HTTPException, Response, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.hand import training_owner
from app.services import river_lessons

router = APIRouter()


class LessonRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    lesson_id: str = Field(min_length=1, max_length=32)
    version: str = Field(pattern='^[0-9a-f]{64}$')


def invoke(method, *args):
    owner = training_owner.get()
    if not owner:
        raise HTTPException(401, 'PROFILE_REQUIRED')
    service = river_lessons.service()
    if service is None:
        raise HTTPException(503, 'LESSON_NOT_ENABLED')
    try:
        return getattr(service, method)(owner, *args)
    except Exception as error:
        # Domain errors expose stable codes; unknown internals do not cross HTTP.
        if hasattr(error, 'code') and hasattr(error, 'status'):
            raise HTTPException(error.status, error.code) from error
        raise HTTPException(503, 'LESSON_ENGINE_UNAVAILABLE') from error


@router.get('')
def catalog(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return river_lessons.catalog()


@router.post('/jobs')
def submit(body: LessonRequest):
    return invoke('submit', body.lesson_id, body.version)


@router.get('/jobs/{ticket_id}')
def poll(ticket_id: str):
    return invoke('poll', ticket_id)


@router.delete('/jobs/{ticket_id}')
def cancel(ticket_id: str):
    return invoke('cancel', ticket_id)


class HistoryModelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: str = Field(pattern='^[0-9a-f]{64}$')
    selected_hands: dict[str, list[str]] = Field(max_length=6)
    bet_sizes: list[int] = Field(min_length=1, max_length=2)
    raise_sizes: list[int] = Field(max_length=2)
    max_raises: int = Field(ge=0, le=1)

    @classmethod
    def validate_sizes(cls, body):
        # Kept server-side even though callers may bypass a browser form.
        if any(not 1 <= v <= 10000 for v in body.bet_sizes+body.raise_sizes):
            raise HTTPException(422,'HISTORY_INVALID_SIZES')
        if any(len(pid)>80 or len(hands)!=2 or any(len(h)!=4 for h in hands)
               for pid,hands in body.selected_hands.items()):
            raise HTTPException(422,'HISTORY_SELECT_TWO_HANDS')
        return {k:v for k,v in body.model_dump().items() if k!='version'}


@router.get('/history')
def history(before: int = Query(default=None, ge=1, le=9223372036854775807)):
    return invoke('history',before)


@router.get('/history/{decision_id}')
def history_detail(decision_id: int):
    return invoke('history_detail',decision_id)


@router.post('/history/{decision_id}/jobs')
def history_submit(decision_id: int, body: HistoryModelRequest):
    return invoke('submit_history',decision_id,HistoryModelRequest.validate_sizes(body),body.version)
