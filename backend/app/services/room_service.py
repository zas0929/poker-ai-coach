from __future__ import annotations

import asyncio
import json
import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field, StrictInt

from app.models.poker import ActionType, HandState, PlayerStatus
from app.services.poker_engine import PokerEngine

SEAT_IDS = ['hero', 'villain', 'villain_2', 'villain_3', 'villain_4', 'villain_5']


class RoomCommand(BaseModel):
    command_id: str = Field(min_length=1, max_length=80)
    revision: StrictInt
    kind: str
    hand_id: Optional[str] = None
    action: Optional[ActionType] = None
    amount: Optional[StrictInt] = None
    ready: Optional[bool] = None

    class Config:
        extra = 'forbid'


@dataclass
class Member:
    player_id: str
    name: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    ready: bool = False
    sockets: set = field(default_factory=set)
    commands: OrderedDict = field(default_factory=OrderedDict)


@dataclass
class Room:
    code: str
    members: list[Member] = field(default_factory=list)
    revision: int = 0
    hand: Optional[HandState] = None
    engine: PokerEngine = field(default_factory=PokerEngine)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def authenticate(self, token: str) -> Member:
        for member in self.members:
            if secrets.compare_digest(member.token, token):
                return member
        raise ValueError('Seat not found. Open the invitation to join this room.')

    def join(self, name: str) -> Member:
        if self.hand is not None:
            raise ValueError('This table has started. New players can join a new room.')
        if len(self.members) >= 6:
            raise ValueError('This room is full (6 players).')
        member = Member(player_id=SEAT_IDS[len(self.members)], name=name)
        self.members.append(member)
        self.revision += 1
        return member

    def snapshot(self, viewer: Member) -> dict:
        hand = json.loads(self.hand.model_dump_json()) if self.hand else None
        if hand:
            revealed = set()
            for player in hand['players']:
                if player['id'] == viewer.player_id or (
                    hand['result'] and hand['result']['reason'] == 'showdown'
                    and player['status'] != PlayerStatus.FOLDED.value
                ):
                    revealed.add(player['id'])
                else:
                    player['cards'] = []
            if hand['result']:
                for result in hand['result']['player_results']:
                    if result['player_id'] not in revealed:
                        result['hand_strength'] = None
            # Explicitly exclude internal state from the public protocol.
            hand.pop('acted_at_bet', None)
            hand['notes'] = []
        return {
            'type': 'state', 'code': self.code, 'revision': self.revision,
            'viewer_id': viewer.player_id, 'host_id': self.members[0].player_id,
            'members': [{'player_id': m.player_id, 'name': m.name, 'ready': m.ready,
                         'connected': bool(m.sockets)} for m in self.members],
            'hand': hand,
        }

    def command(self, member: Member, command: RoomCommand) -> None:
        fingerprint = command.model_dump_json()
        if command.command_id in member.commands:
            if member.commands[command.command_id] != fingerprint:
                raise ValueError('Command ID has already been used for a different command.')
            return
        if command.revision != self.revision:
            raise ValueError('Table changed. The latest state has been loaded; choose your action again.')
        if command.kind == 'ready':
            if self.hand and not self.hand.result:
                raise ValueError('Finish the current hand first.')
            if command.ready is None:
                raise ValueError('Ready status is required.')
            member.ready = command.ready
        elif command.kind == 'start':
            if member is not self.members[0]:
                raise ValueError('Only the host can deal the next hand.')
            if len(self.members) < 2 or not all(m.ready and m.sockets for m in self.members):
                raise ValueError('At least two players must be connected and everyone must be ready.')
            self.hand = self.engine.start_hand(previous_state=self.hand, player_count=len(self.members))
            for player, seated in zip(self.hand.players, self.members):
                player.name = seated.name
            for seated in self.members:
                seated.ready = False
        elif command.kind == 'action':
            if not self.hand or command.hand_id != self.hand.hand_id:
                raise ValueError('This hand is no longer active.')
            if command.action is None:
                raise ValueError('Choose an action.')
            self.hand = self.engine.apply_action(self.hand, member.player_id, command.action, command.amount)
            # Street transitions belong to the server, never to a particular client.
            while self.hand.current_player_id is None and not self.hand.result:
                self.hand = self.engine.advance(self.hand)
        else:
            raise ValueError('Unknown room command.')
        self.revision += 1
        member.commands[command.command_id] = fingerprint
        while len(member.commands) > 128:
            member.commands.popitem(last=False)

    async def broadcast(self) -> None:
        # Caller holds the room lock: all clients receive snapshots in revision order.
        failed = []
        deliveries = []
        for member in self.members:
            snapshot = self.snapshot(member)
            for socket in list(member.sockets):
                deliveries.append((member, socket, snapshot))
        results = await asyncio.gather(*[
            asyncio.wait_for(socket.send_json(snapshot), timeout=3)
            for _, socket, snapshot in deliveries
        ], return_exceptions=True)
        for (member, socket, _), result in zip(deliveries, results):
            if isinstance(result, BaseException):
                member.sockets.discard(socket)
                failed.append(socket)
        for socket in failed:
            try:
                await socket.close()
            except Exception:
                pass


class RoomStore:
    def __init__(self):
        self.rooms: dict[str, Room] = {}

    def create(self, name: str) -> tuple[Room, Member]:
        if len(self.rooms) >= 200:
            raise ValueError('Room limit reached. Restart the local server to clear old rooms.')
        while True:
            code = secrets.token_hex(4).upper()
            if code not in self.rooms:
                break
        room = Room(code)
        member = room.join(name)
        self.rooms[code] = room
        return room, member

    def get(self, code: str) -> Room:
        room = self.rooms.get(code.upper())
        if room is None:
            raise ValueError('Room not found. Rooms are cleared when the server restarts.')
        return room
