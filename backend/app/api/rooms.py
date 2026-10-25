from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Header, Query, Response
from pydantic import BaseModel, Field, StrictInt, ValidationError, field_validator

from app.services.room_service import RoomCommand, RoomStore, RoomSettings
from app.services.room_repository import RoomStorageError

router = APIRouter()
database_url = os.environ.get('POKER_DATABASE_URL')
if os.environ.get('RENDER') == 'true' and not database_url:
    raise RuntimeError('POKER_DATABASE_URL is required on Render; local SQLite storage is ephemeral.')
if database_url and not database_url.startswith(('postgres://', 'postgresql://')):
    raise RuntimeError('POKER_DATABASE_URL must be a PostgreSQL connection URL.')
store = RoomStore(database_url or os.environ.get('POKER_DB_PATH', str(Path(__file__).resolve().parents[2] / '.data' / 'poker.sqlite3')))


class JoinRequest(BaseModel):
    buy_in: Optional[StrictInt] = Field(default=None, ge=1, le=1000000)
    name: str = Field(min_length=1, max_length=24)

    @field_validator('name')
    @classmethod
    def clean_name(cls, name):
        name = name.strip()
        if not name or any(ord(char) < 32 for char in name):
            raise ValueError('Enter a name (1–24 printable characters).')
        return name


class CreateRequest(JoinRequest):
    settings: Optional[RoomSettings] = None


@router.get('')
async def public_rooms(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return {'rooms': [{'code': room.code, 'players': len(room.seated),
                      'small_blind': room.settings.small_blind, 'big_blind': room.settings.big_blind,
                      'starting_stack': room.settings.starting_stack,
                      'hand_in_progress': bool(room.hand and not room.hand.result),
                      'seats_available': 6 - len(room.occupied_seats),
                      'can_join': len(room.occupied_seats) < 6}
                     for room in list(store.rooms.values()) if room.settings.visibility == 'public' and room.seated][:50]}


@router.post('')
async def create_room(request: CreateRequest):
    try:
        room, member = store.create(request.name, request.buy_in, request.settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'code': room.code, 'token': member.token, 'player_id': member.player_id}


@router.post('/{code}/join')
async def join_room(code: str, request: JoinRequest):
    try:
        room = store.get(code)
        async with room.lock:
            member = store.apply(room, lambda: room.join(request.name, request.buy_in), 'join')
            await room.broadcast()
            return {'code': room.code, 'token': member.token, 'player_id': member.player_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def history_member(code, authorization):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Seat authentication is required.')
    try:
        room = store.get(code)
        member = room.authenticate(authorization[7:])
    except ValueError as exc:
        raise HTTPException(status_code=401, detail='Seat authentication failed.') from exc
    if not store.repository:
        raise HTTPException(status_code=503, detail='Hand history storage is unavailable.')
    return room, member


@router.get('/{code}/history')
async def read_history(code: str, response: Response, authorization: Optional[str] = Header(default=None),
                       limit: int = Query(default=20, ge=1, le=50),
                       before: Optional[int] = Query(default=None, ge=1, le=9223372036854775807)):
    room, member = history_member(code, authorization)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Authorization'
    return store.repository.history_page(room.code, member.player_id, limit, before)


@router.get('/{code}/history/{hand_id}')
async def read_archived_hand(code: str, hand_id: str, response: Response, authorization: Optional[str] = Header(default=None)):
    room, member = history_member(code, authorization)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Authorization'
    try:
        return store.repository.archived_hand(room.code, hand_id, member.player_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail='Archived hand not found.') from exc


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
                    store.apply(room, lambda: room.command(member, command), command.kind, command.command_id, member.player_id)
                    await room.broadcast()
                    await websocket.send_json({'type': 'ack', 'command_id': command.command_id})
                except (ValueError, ValidationError, RoomStorageError) as exc:
                    message = 'Invalid command format.' if isinstance(exc, ValidationError) else str(exc)
                    await websocket.send_json({'type': 'error', 'message': message})
                    await room.broadcast()
    except (ValueError, asyncio.TimeoutError):
        await websocket.close(code=1008)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if room and member:
            async with room.lock:
                member.sockets.discard(websocket)
                await room.broadcast()
