from __future__ import annotations

import asyncio
import json
import secrets
import time
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field, StrictInt, model_validator

from app.models.poker import ActionType, Card, HandState
from app.services.poker_engine import PokerEngine
from app.services.hand_projection import project_hand
from app.services.room_repository import RoomRepository, RoomStorageError

TURN_GRACE_SECONDS = 10

SEAT_IDS = ['hero', 'villain', 'villain_2', 'villain_3', 'villain_4', 'villain_5']


class RoomSettings(BaseModel):
    starting_stack: StrictInt = Field(default=400, ge=100, le=1000000)
    small_blind: StrictInt = Field(default=1, ge=1, le=10000)
    big_blind: StrictInt = Field(default=2, ge=2, le=20000)
    turn_seconds: StrictInt = Field(default=30, ge=10, le=120)
    visibility: str = Field(default="private", pattern="^(private|public)$")
    auto_deal: bool = Field(default=True, strict=True)

    @model_validator(mode='after')
    def validate_structure(self):
        if self.small_blind >= self.big_blind:
            raise ValueError('Small blind must be less than big blind.')
        if self.starting_stack < 20 * self.big_blind:
            raise ValueError('Starting stack must be at least 20 big blinds.')
        return self

    class Config:
        extra = 'forbid'


class RoomCommand(BaseModel):
    command_id: str = Field(min_length=1, max_length=80)
    revision: StrictInt
    kind: str
    request_id: Optional[str] = Field(default=None, min_length=1, max_length=80)
    hand_id: Optional[str] = None
    action: Optional[ActionType] = None
    amount: Optional[StrictInt] = None
    ready: Optional[bool] = None
    sit_out: Optional[bool] = None
    auto_deal: Optional[bool] = Field(default=None, strict=True)
    settings: Optional[RoomSettings] = None

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
    stack: int = 400
    session_buy_in: int = 400
    session_top_ups: int = 0
    session_partial: bool = False


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
    settled_hand_id: Optional[str] = None
    next_hand_at: Optional[float] = None
    settings: RoomSettings = field(default_factory=RoomSettings)
    revealed_folds: set[str] = field(default_factory=set)
    top_up_requests: list[dict] = field(default_factory=list)

    @property
    def turn_seconds(self):
        return self.settings.turn_seconds
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

    def join(self, name: str, buy_in: int | None = None) -> Member:
        if self.hand is not None and not self.hand.result:
            raise ValueError('Wait until the hand finishes before joining.')
        if len(self.seated) >= 6:
            raise ValueError('This room is full (6 players).')
        chips = self.settings.starting_stack if buy_in is None else buy_in
        if type(chips) is not int or not self.settings.big_blind <= chips <= 1000000:
            raise ValueError('Buy-in must cover the big blind and be at most 1000000 chips.')
        seat = next(i for i in range(6) if all(m.seat != i for m in self.seated))
        player_id = SEAT_IDS[seat]
        if player_id in self.used_ids:
            player_id = 'seat_' + secrets.token_hex(12)
        self.used_ids.add(player_id)
        member = Member(player_id=player_id, name=name, seat=seat, stack=chips, session_buy_in=chips, ready=self.settings.auto_deal)
        if self.host_id is None:
            self.host_player_id = member.player_id
        self.members.append(member)
        self.revision += 1
        return member

    def snapshot(self, viewer: Member) -> dict:
        hand = project_hand(self.hand, viewer.player_id) if self.hand else None
        if hand:
            for player in hand['players']:
                if player['id'] in self.revealed_folds and player['status'] == 'folded':
                    player['cards'] = next(p for p in self.hand.players if p.id == player['id']).model_dump(mode='json')['cards']
        if hand and self.hand.result:
            for player in hand['players']:
                player['stack'] = next(m.stack for m in self.members if m.player_id == player['id'])
        return {
            'type': 'state', 'revealed_folds': sorted(self.revealed_folds), 'code': self.code, 'revision': self.revision,
            'viewer_id': viewer.player_id, 'host_id': self.host_id,
            'viewer_left': viewer.leaving, 'turn_seconds': self.turn_seconds,
            'turn_grace_seconds': TURN_GRACE_SECONDS,
            'settings': self.settings.model_dump(), 'saved': True,
            'next_hand_at': self.next_hand_at, 'deadline_at': self.deadline_at, 'server_now': time.time() * 1000,
            'members': [{'player_id': m.player_id, 'name': m.name, 'ready': m.ready,
                         'connected': bool(m.sockets), 'sitting_out': m.sitting_out,
                         'seat': m.seat, 'stack': m.stack,
                         'session_buy_in': m.session_buy_in, 'session_top_ups': m.session_top_ups,
                         'session_partial': m.session_partial} for m in self.seated],
            'hand': hand,
            'top_up_requests': [dict(request) for request in self.top_up_requests],
        }

    def command(self, member: Member, command: RoomCommand) -> None:
        fingerprint = command.model_dump_json()
        if command.command_id in member.commands:
            if member.commands[command.command_id] != fingerprint:
                raise ValueError('Command ID has already been used for a different command.')
            return
        if (self.hand and not self.hand.result) or (self.next_hand_at is not None and time.time() * 1000 >= self.next_hand_at):
            self.tick()
        if member.leaving:
            raise ValueError('You have left this room. Join again for a new seat.')
        if command.revision != self.revision:
            raise ValueError('Table changed. The latest state has been loaded; choose your action again.')
        if command.kind == 'show_fold':
            player = next((p for p in self.hand.players if p.id == member.player_id), None) if self.hand else None
            if not player or player.status.value != 'folded' or command.hand_id != self.hand.hand_id:
                raise ValueError('Only your folded cards from this hand can be shown.')
            self.revealed_folds.add(member.player_id)
        elif command.kind == 'ready':
            if self.hand and not self.hand.result:
                raise ValueError('Finish the current hand first.')
            if command.ready is None:
                raise ValueError('Ready status is required.')
            if member.sitting_out:
                raise ValueError('Return from sit-out before getting ready.')
            member.ready = command.ready
        elif command.kind == 'top_up':
            self._validate_top_up(member, command.amount)
            if any(r['player_id'] == member.player_id and r['status'] == 'pending' for r in self.top_up_requests):
                raise ValueError('You already have a pending chip request.')
            self.top_up_requests = [r for r in self.top_up_requests if r['status'] == 'pending'] + [
                r for r in self.top_up_requests if r['status'] != 'pending'][-24:]
            self.top_up_requests.append({'request_id': secrets.token_hex(16), 'player_id': member.player_id,
                                         'name': member.name, 'amount': command.amount, 'status': 'pending'})
            self.next_hand_at = None
        elif command.kind in ('approve_top_up', 'decline_top_up'):
            if member.player_id != self.host_id:
                raise ValueError('Only the host can review chip requests.')
            request = next((r for r in self.top_up_requests if r['request_id'] == command.request_id), None)
            if request is None or request['status'] != 'pending':
                raise ValueError('This chip request has already been reviewed or is unavailable.')
            if command.kind == 'approve_top_up':
                recipient = next(m for m in self.seated if m.player_id == request['player_id'])
                self._validate_top_up(recipient, request['amount'])
                was_short = recipient.stack < self.settings.big_blind
                recipient.stack += request['amount']
                recipient.session_top_ups += request['amount']
                if was_short and recipient.stack >= self.settings.big_blind and self.settings.auto_deal and not recipient.sitting_out:
                    recipient.ready = True
            request['status'] = 'approved' if command.kind == 'approve_top_up' else 'declined'
            request['reviewed_by'] = member.player_id
        elif command.kind == 'auto_deal':
            if member.player_id != self.host_id:
                raise ValueError('Only the host can change table settings.')
            if self.hand and not self.hand.result:
                raise ValueError('Finish the current hand first.')
            if command.auto_deal is None:
                raise ValueError('Automatic dealing status is required.')
            self.settings = self.settings.model_copy(update={'auto_deal': command.auto_deal})
            self.next_hand_at = None
            for seated in self.seated:
                seated.ready = command.auto_deal and not seated.sitting_out and seated.stack >= self.settings.big_blind
        elif command.kind == 'settings':
            if member.player_id != self.host_id:
                raise ValueError('Only the host can change table settings.')
            if self.hand is not None:
                raise ValueError('Settings are locked after the first deal. Create a new room to change them.')
            if command.settings is None:
                raise ValueError('Table settings are required.')
            self.settings = command.settings
            for seated in self.members:
                seated.ready = self.settings.auto_deal and not seated.sitting_out
        elif command.kind == 'sit_out':
            if command.sit_out is None:
                raise ValueError('Sit-out status is required.')
            if not command.sit_out and self.hand and not self.hand.result:
                raise ValueError('You can return after this hand finishes.')
            member.sitting_out = command.sit_out
            member.ready = self.settings.auto_deal and not command.sit_out
        elif command.kind == 'leave':
            for request in self.top_up_requests:
                if request['player_id'] == member.player_id and request['status'] == 'pending':
                    request['status'] = 'cancelled'
            member.leaving = True
            self.host_player_id = self.host_id
            member.sitting_out = True
            member.ready = False
        elif command.kind == 'start':
            if member.player_id != self.host_id:
                raise ValueError('Only the host can deal the next hand.')
            if self.hand and not self.hand.result:
                raise ValueError('Finish the current hand first.')
            self._deal()
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

    def _validate_top_up(self, member, amount):
        if self.hand and not self.hand.result and any(player.id == member.player_id for player in self.hand.players):
            raise ValueError('Add chips between hands only.')
        if type(amount) is not int or amount <= 0 or member.stack + amount > 1000000:
            raise ValueError('Add a positive whole number without exceeding 1000000 chips.')

    def _deal(self):
        if any(r['status'] == 'pending' for r in self.top_up_requests):
            raise ValueError('Review pending chip requests before dealing.')
        self.next_hand_at = None
        playing = [m for m in self.seated if not m.sitting_out and m.stack >= self.settings.big_blind]
        if len(playing) < 2 or not all(m.ready and m.sockets for m in playing):
            raise ValueError('At least two active players must be connected and ready.')
        # Keep physical seats and clockwise button movement across roster changes.
        button = next((m for m in playing if m.seat > self.button_seat), playing[0])
        offset = playing.index(button)
        playing = playing[offset:] + playing[:offset]
        if any(m.stack < self.settings.big_blind for m in playing):
            raise ValueError('Add chips or sit out before the next hand.')
        stacks = [m.stack for m in playing]
        self.revealed_folds.clear()
        self.hand = self.engine.start_hand(player_count=len(playing), starting_stacks=stacks,
                                           small_blind=self.settings.small_blind, big_blind=self.settings.big_blind)
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
            seated.ready = self.settings.auto_deal and not seated.sitting_out

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
            if self.hand.result and self.settled_hand_id != self.hand.hand_id:
                self.settled_hand_id = self.hand.hand_id
                for player in self.hand.players:
                    member = next(m for m in self.members if m.player_id == player.id)
                    member.stack = player.stack
                    if self.settings.auto_deal:
                        member.ready = not member.sitting_out and player.stack >= self.settings.big_blind
        self._sync_clock()

    def _auto_action(self, actor):
        options = self.hand.betting
        action = ActionType.CHECK if ActionType.CHECK in options.legal_actions else ActionType.FOLD
        self.hand = self.engine.apply_action(self.hand, actor.player_id, action)

    def _sync_clock(self):
        key = (self.hand.hand_id, len(self.hand.history), self.hand.current_player_id) if self.hand and not self.hand.result else None
        if key != self.turn_key:
            self.turn_key = key
            self.deadline = time.monotonic() + TURN_GRACE_SECONDS + self.turn_seconds if key else None
            self.deadline_at = (time.time() + TURN_GRACE_SECONDS + self.turn_seconds) * 1000 if key else None

    def tick(self, now=None):
        if self.settings.auto_deal and (not self.hand or self.hand.result):
            playing = [m for m in self.seated if not m.sitting_out and m.stack >= self.settings.big_blind]
            can_deal = not any(r['status'] == 'pending' for r in self.top_up_requests) and len(playing) >= 2 and all(m.ready and m.sockets for m in playing)
            if not can_deal:
                if self.next_hand_at is None: return False
                self.next_hand_at = None
                self.revision += 1
                return True
            if self.next_hand_at is None:
                self.next_hand_at = time.time() * 1000 + 8000
                self.revision += 1
                return True
            if time.time() * 1000 < self.next_hand_at: return False
            self._deal()
            self._settle()
            self.revision += 1
            return True
        now = time.monotonic() if now is None else now
        if self.deadline is None or now < self.deadline or not self.hand or self.hand.result:
            return False
        actor = next(m for m in self.members if m.player_id == self.hand.current_player_id)
        if ActionType.CHECK not in self.hand.betting.legal_actions:
            actor.sitting_out = True
            actor.ready = False
        self._auto_action(actor)
        self._settle()
        self.revision += 1
        return True

    def to_record(self):
        hand = json.loads(self.hand.model_dump_json()) if self.hand else None
        if hand is not None:
            hand['_deck'] = [card.model_dump(mode='json') for card in self.hand._deck]
        return {
            'revealed_folds': sorted(self.revealed_folds),
            'top_up_requests': [dict(request) for request in self.top_up_requests],
            'schema_version': 1, 'settled_hand_id': self.settled_hand_id, 'code': self.code, 'revision': self.revision,
            'host_player_id': self.host_player_id, 'used_ids': sorted(self.used_ids),
            'button_seat': self.button_seat, 'settings': self.settings.model_dump(),
            'next_hand_at': self.next_hand_at, 'deadline_at': self.deadline_at, 'hand': hand,
            'members': [{key: getattr(m, key) for key in (
                'player_id', 'name', 'token', 'ready', 'sitting_out', 'leaving', 'seat', 'stack',
                'session_buy_in', 'session_top_ups', 'session_partial'
            )} | {'commands': [list(entry) for entry in m.commands.items()]} for m in self.members],
        }

    def restore(self, record):
        if record['schema_version'] != 1:
            raise ValueError('Unsupported room database version.')
        self.revealed_folds = set(record.get('revealed_folds', []))
        self.top_up_requests = [dict(request) for request in record.get('top_up_requests', [])]
        self.revision = record['revision']
        self.host_player_id = record['host_player_id']
        self.used_ids = set(record['used_ids'])
        self.button_seat = record['button_seat']
        self.settings = RoomSettings.model_validate({'auto_deal': False, **record['settings']})
        self.next_hand_at = record.get('next_hand_at')
        existing = {m.player_id: m for m in self.members}
        members = []
        for values in record['members']:
            values = dict(values)
            commands = values.pop('commands')
            if 'session_buy_in' not in values:
                # Old records do not retain complete buy-in history. Start an explicit baseline.
                values.update(session_buy_in=values['stack'], session_top_ups=0, session_partial=True)
            member = existing.get(values['player_id']) or Member(**values)
            for key, value in values.items():
                setattr(member, key, value)
            member.commands = OrderedDict(commands)
            members.append(member)
        self.members = members
        hand = record['hand']
        self.hand = HandState.model_validate({k: v for k, v in hand.items() if k != '_deck'}) if hand else None
        if self.hand:
            self.hand._deck = [Card.model_validate(c) for c in hand['_deck']]
        self.settled_hand_id = record.get('settled_hand_id', self.hand.hand_id if self.hand and self.hand.result else None)
        self.turn_key = (self.hand.hand_id, len(self.hand.history), self.hand.current_player_id) if self.hand and not self.hand.result else None
        self.deadline_at = record['deadline_at'] if self.turn_key else None
        self.deadline = time.monotonic() + max(0, min(TURN_GRACE_SECONDS + self.turn_seconds, self.deadline_at / 1000 - time.time())) if self.deadline_at else None

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
    def __init__(self, database_path=None):
        self.rooms: dict[str, Room] = {}
        self.repository = RoomRepository(database_path) if database_path else None

    def open(self):
        if self.repository:
            self.repository.open()
            for record in self.repository.load():
                room = Room(record['code'])
                room.restore(record)
                self.rooms[room.code] = room

    def close(self):
        if self.repository:
            self.repository.close()

    def apply(self, room, operation, kind, command_id=None, player_id=None):
        before = room.to_record()
        deadline = room.deadline
        try:
            result = operation()
        except ValueError:
            # A late command may first process an expired turn; persist that timeout.
            self._persist_or_restore(room, before, deadline, 'timeout', command_id, player_id)
            raise
        except Exception:
            room.restore(before)
            room.deadline = deadline
            raise
        self._persist_or_restore(room, before, deadline, kind, command_id, player_id)
        return result

    def _persist_or_restore(self, room, before, deadline, kind, command_id, player_id):
        if not self.repository or room.revision == before['revision']:
            return
        try:
            self.repository.save(room.to_record(), kind, command_id, player_id)
        except Exception as exc:
            room.restore(before)
            room.deadline = deadline
            raise RoomStorageError('Could not save the table. No action was confirmed; reconnect and retry.') from exc


    async def run_timers(self):
        async def check(room):
            async with room.lock:
                try:
                    if self.apply(room, room.tick, 'timer'):
                        await room.broadcast()
                except RoomStorageError:
                    logging.getLogger(__name__).exception('Could not persist room timeout')
        while True:
            await asyncio.gather(*(check(room) for room in list(self.rooms.values())))
            await asyncio.sleep(0.25)

    def create(self, name: str, buy_in: int | None = None, settings: RoomSettings | None = None) -> tuple[Room, Member]:
        if len(self.rooms) >= 200:
            raise ValueError('Room limit reached (200 rooms).')
        while True:
            code = secrets.token_hex(4).upper()
            if code not in self.rooms:
                break
        room = Room(code, settings=settings or RoomSettings())
        member = room.join(name, buy_in)
        if self.repository:
            try:
                self.repository.save(room.to_record(), 'create', player_id=member.player_id)
            except Exception as exc:
                raise RoomStorageError('Could not save the new room. Please retry.') from exc
        self.rooms[code] = room
        return room, member

    def get(self, code: str) -> Room:
        room = self.rooms.get(code.upper())
        if room is None:
            raise ValueError('Room not found. Check the invitation code.')
        return room
