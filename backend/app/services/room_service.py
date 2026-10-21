from __future__ import annotations

import asyncio
import json
import secrets
import time
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
    sit_out: Optional[bool] = None

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
    sitting_out: bool = False
    leaving: bool = False
    seat: int = 0
    stack: int = 1000


@dataclass
class Room:
    code: str
    members: list[Member] = field(default_factory=list)
    revision: int = 0
    hand: Optional[HandState] = None
    engine: PokerEngine = field(default_factory=PokerEngine)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    host_player_id: Optional[str] = None
    used_ids: set = field(default_factory=set)
    button_seat: int = -1
    turn_seconds: int = 30
    deadline: Optional[float] = None
    deadline_at: Optional[float] = None
    turn_key: Optional[tuple] = None

    @property
    def seated(self):
        return sorted((m for m in self.members if not m.leaving), key=lambda m: m.seat)

    @property
    def host_id(self):
        return next((m.player_id for m in self.seated if m.player_id == self.host_player_id),
                    self.seated[0].player_id if self.seated else None)

    def authenticate(self, token: str) -> Member:
        for member in self.members:
            if not member.leaving and secrets.compare_digest(member.token, token):
                return member
        raise ValueError('Seat not found. Open the invitation to join this room.')

    def join(self, name: str) -> Member:
        if self.hand is not None and not self.hand.result:
            raise ValueError('Wait until the hand finishes before joining.')
        if len(self.seated) >= 6:
            raise ValueError('This room is full (6 players).')
        seat = next(i for i in range(6) if all(m.seat != i for m in self.seated))
        player_id = SEAT_IDS[seat]
        if player_id in self.used_ids:
            player_id = 'seat_' + secrets.token_hex(12)
        self.used_ids.add(player_id)
        member = Member(player_id=player_id, name=name, seat=seat)
        if self.host_id is None:
            self.host_player_id = member.player_id
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
            'viewer_id': viewer.player_id, 'host_id': self.host_id,
            'viewer_left': viewer.leaving, 'turn_seconds': self.turn_seconds,
            'deadline_at': self.deadline_at, 'server_now': time.time() * 1000,
            'members': [{'player_id': m.player_id, 'name': m.name, 'ready': m.ready,
                         'connected': bool(m.sockets), 'sitting_out': m.sitting_out,
                         'seat': m.seat, 'stack': m.stack} for m in self.seated],
            'hand': hand,
        }

    def command(self, member: Member, command: RoomCommand) -> None:
        fingerprint = command.model_dump_json()
        if command.command_id in member.commands:
            if member.commands[command.command_id] != fingerprint:
                raise ValueError('Command ID has already been used for a different command.')
            return
        self.tick()
        if member.leaving:
            raise ValueError('You have left this room. Join again for a new seat.')
        if command.revision != self.revision:
            raise ValueError('Table changed. The latest state has been loaded; choose your action again.')
        if command.kind == 'ready':
            if self.hand and not self.hand.result:
                raise ValueError('Finish the current hand first.')
            if command.ready is None:
                raise ValueError('Ready status is required.')
            if member.sitting_out:
                raise ValueError('Return from sit-out before getting ready.')
            member.ready = command.ready
        elif command.kind == 'sit_out':
            if command.sit_out is None:
                raise ValueError('Sit-out status is required.')
            if not command.sit_out and self.hand and not self.hand.result:
                raise ValueError('You can return after this hand finishes.')
            member.sitting_out = command.sit_out
            member.ready = False
        elif command.kind == 'leave':
            member.leaving = True
            self.host_player_id = self.host_id
            member.sitting_out = True
            member.ready = False
        elif command.kind == 'start':
            if member.player_id != self.host_id:
                raise ValueError('Only the host can deal the next hand.')
            if self.hand and not self.hand.result:
                raise ValueError('Finish the current hand first.')
            playing = [m for m in self.seated if not m.sitting_out]
            if len(playing) < 2 or not all(m.ready and m.sockets for m in playing):
                raise ValueError('At least two active players must be connected and ready.')
            # Keep physical seats and clockwise button movement across roster changes.
            button = next((m for m in playing if m.seat > self.button_seat), playing[0])
            offset = playing.index(button)
            playing = playing[offset:] + playing[:offset]
            stacks = [m.stack + (1000 if m.stack < 10 else 0) for m in playing]
            self.hand = self.engine.start_hand(player_count=len(playing), starting_stacks=stacks)
            mapping = {p.id: m.player_id
                       for p, m in zip(self.hand.players, playing)}
            for player, seated in zip(self.hand.players, playing):
                player.id = seated.player_id
                player.name = seated.name
            self.hand.current_player_id = mapping.get(self.hand.current_player_id)
            self.hand.dealer_player_id = mapping[self.hand.dealer_player_id]
            self.hand.contributions = {mapping[k]: v for k, v in self.hand.contributions.items()}
            self.hand.acted_at_bet = {mapping[k]: v for k, v in self.hand.acted_at_bet.items()}
            for action in self.hand.history:
                action.player_id = mapping[action.player_id]
            self.engine._refresh_betting(self.hand)
            self.button_seat = button.seat
            for seated in self.members:
                seated.ready = False
        elif command.kind == 'action':
            if not self.hand or command.hand_id != self.hand.hand_id:
                raise ValueError('This hand is no longer active.')
            if command.action is None:
                raise ValueError('Choose an action.')
            self.hand = self.engine.apply_action(self.hand, member.player_id, command.action, command.amount)
        else:
            raise ValueError('Unknown room command.')
        self._settle()
        self.revision += 1
        member.commands[command.command_id] = fingerprint
        while len(member.commands) > 128:
            member.commands.popitem(last=False)

    def _settle(self):
        if self.hand:
            while not self.hand.result:
                if self.hand.current_player_id is None:
                    self.hand = self.engine.advance(self.hand)
                    continue
                actor = next(m for m in self.members if m.player_id == self.hand.current_player_id)
                if not actor.sitting_out and not actor.leaving:
                    break
                self._auto_action(actor)
            if self.hand.result:
                for player in self.hand.players:
                    member = next(m for m in self.members if m.player_id == player.id)
                    member.stack = player.stack
        self._sync_clock()

    def _auto_action(self, actor):
        options = self.hand.betting
        action = ActionType.CHECK if ActionType.CHECK in options.legal_actions else ActionType.FOLD
        self.hand = self.engine.apply_action(self.hand, actor.player_id, action)

    def _sync_clock(self):
        key = (self.hand.hand_id, len(self.hand.history), self.hand.current_player_id) if self.hand and not self.hand.result else None
        if key != self.turn_key:
            self.turn_key = key
            self.deadline = time.monotonic() + self.turn_seconds if key else None
            self.deadline_at = (time.time() + self.turn_seconds) * 1000 if key else None

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        if self.deadline is None or now < self.deadline or not self.hand or self.hand.result:
            return False
        actor = next(m for m in self.members if m.player_id == self.hand.current_player_id)
        actor.sitting_out = True
        actor.ready = False
        self._auto_action(actor)
        self._settle()
        self.revision += 1
        return True

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

    async def run_timers(self):
        async def check(room):
            async with room.lock:
                if room.tick():
                    await room.broadcast()
        while True:
            await asyncio.gather(*(check(room) for room in list(self.rooms.values())))
            await asyncio.sleep(0.25)

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
