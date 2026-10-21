from __future__ import annotations

import asyncio
import json
import os

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.services.room_service import RoomCommand, RoomStore

router = APIRouter()
store = RoomStore()


class JoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=24)

    @field_validator('name')
    @classmethod
    def clean_name(cls, name):
        name = name.strip()
        if not name or any(ord(char) < 32 for char in name):
            raise ValueError('Enter a name (1–24 printable characters).')
        return name


@router.post('')
async def create_room(request: JoinRequest):
    try:
        room, member = store.create(request.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'code': room.code, 'token': member.token, 'player_id': member.player_id}


@router.post('/{code}/join')
async def join_room(code: str, request: JoinRequest):
    try:
        room = store.get(code)
        async with room.lock:
            member = room.join(request.name)
            await room.broadcast()
            return {'code': room.code, 'token': member.token, 'player_id': member.player_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def allowed_origin(origin: str) -> bool:
    # Configure exact origins for a later HTTPS deployment. No wildcard origins.
    origins = os.environ.get('POKER_ROOM_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000')
    return origin in {entry.strip() for entry in origins.split(',')}


@router.websocket('/{code}/ws')
async def room_socket(websocket: WebSocket, code: str):
    if not allowed_origin(websocket.headers.get('origin', '')):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    room = member = None
    try:
        # The seat secret is sent in the first frame, never in a URL or invitation.
        auth = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        if len(auth) > 2048:
            raise ValueError('Invalid authentication.')
        payload = json.loads(auth)
        if not isinstance(payload, dict) or not isinstance(payload.get('token'), str):
            raise ValueError('Seat token is required.')
        room = store.get(code)
        async with room.lock:
            member = room.authenticate(payload['token'])
            member.sockets.add(websocket)
            await room.broadcast()
        while True:
            raw = await websocket.receive_text()
            if len(raw) > 4096:
                await websocket.close(code=1009)
                break
            async with room.lock:
                try:
                    command = RoomCommand.model_validate_json(raw)
                    room.command(member, command)
                    await room.broadcast()
                    await websocket.send_json({'type': 'ack', 'command_id': command.command_id})
                except (ValueError, ValidationError) as exc:
                    message = 'Invalid command format.' if isinstance(exc, ValidationError) else str(exc)
                    await websocket.send_json({'type': 'error', 'message': message})
                    await websocket.send_json(room.snapshot(member))
    except (ValueError, asyncio.TimeoutError):
        await websocket.close(code=1008)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if room and member:
            async with room.lock:
                member.sockets.discard(websocket)
                await room.broadcast()
