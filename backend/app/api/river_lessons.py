from fastapi import APIRouter, HTTPException, Response
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
