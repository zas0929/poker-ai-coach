from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api import hand
from app.services import trainer_solver

router = APIRouter()


class CurrentModelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    position: str = Field(min_length=2, max_length=65536)
    nonce: str = Field(min_length=1, max_length=80)


def invoke(operation):
    if not hand.training_owner.get():
        raise HTTPException(401, 'PROFILE_REQUIRED')
    service = trainer_solver.service()
    if service is None:
        return {'state': 'disabled', 'ticket_id': None, 'reason': 'TRAINER_SOLVER_DISABLED', 'actions': None}
    try:
        return operation(service)
    except Exception as error:
        if hasattr(error, 'code') and hasattr(error, 'status'):
            raise HTTPException(error.status, error.code) from error
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(503, 'TRAINER_SOLVER_UNAVAILABLE') from error


@hand.serialized
def current(position=None):
    state = hand.get_current_state()
    if position is not None and trainer_solver.position_text(state) != position:
        raise HTTPException(409, 'STALE_DECISION')
    return trainer_solver.public_copy(state)


@hand.serialized
def enqueue(service, body, assessment, request):
    if trainer_solver.position_text(hand.get_current_state()) != body.position:
        raise HTTPException(409, 'STALE_DECISION')
    return service.submit(hand.training_owner.get(), body.nonce, assessment, request)


@router.post('')
def submit(body: CurrentModelRequest):
    def operation(service):
        state = current(body.position)
        # Range preparation is outside the game lock; CFR runs in a child process.
        from research.trainer_current import prepare
        assessment, request = prepare(state)
        return enqueue(service, body, assessment, request)
    return invoke(operation)


@router.get('/{handle}')
@hand.serialized
def poll(handle: str):
    return invoke(lambda service: service.poll(hand.training_owner.get(), handle,
                   trainer_solver.position_key(hand.current_state)))


@router.delete('/{handle}')
def cancel(handle: str):
    return invoke(lambda service: service.cancel(hand.training_owner.get(), handle))
