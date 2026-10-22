import asyncio
import json
import unittest

from pydantic import ValidationError

from app.services.room_service import RoomCommand, RoomStore, RoomSettings
from app.models.poker import ActionType


class RoomTests(unittest.TestCase):
    def setUp(self):
        self.store = RoomStore()
        self.room, self.host = self.store.create('Roman', settings=RoomSettings(starting_stack=1000, small_blind=5, big_blind=10, auto_deal=False))
        self.guest = self.room.join('Friend')
        # Connection presence is required to deal, without needing real sockets here.
        self.host.sockets.add(object())
        self.guest.sockets.add(object())
        self.counter = 0

    def command(self, member, kind, **values):
        self.counter += 1
        command = RoomCommand(command_id=str(self.counter), revision=self.room.revision, kind=kind, **values)
        self.room.command(member, command)
        return command

    def start(self):
        for member in self.room.members:
            self.command(member, 'ready', ready=True)
        return self.command(self.host, 'start')

    def test_unique_rooms_and_tokens_and_no_secret_in_snapshot(self):
        other, _ = self.store.create('Other')
        self.assertNotEqual(self.room.code, other.code)
        self.assertNotEqual(self.host.token, self.guest.token)
        with self.assertRaises(ValueError):
            other.authenticate(self.host.token)
        raw = json.dumps(self.room.snapshot(self.host))
        self.assertNotIn(self.host.token, raw)
        self.assertNotIn(self.guest.token, raw)

    def test_private_projection_is_detached_and_training_is_independent(self):
        self.start()
        host = self.room.snapshot(self.host)['hand']
        guest = self.room.snapshot(self.guest)['hand']
        self.assertEqual(len(host['players'][0]['cards']), 2)
        self.assertEqual(host['players'][1]['cards'], [])
        self.assertEqual(guest['players'][0]['cards'], [])
        self.assertEqual(len(guest['players'][1]['cards']), 2)
        self.assertNotIn('_deck', host)
        host['players'][0]['cards'].clear()
        self.assertEqual(len(self.room.hand.players[0].cards), 2)
        other, _ = self.store.create('Other')
        self.assertIsNone(other.hand)

    def test_start_is_host_only_and_requires_ready_connected_players(self):
        with self.assertRaises(ValueError):
            self.command(self.host, 'start')
        self.command(self.host, 'ready', ready=True)
        self.command(self.guest, 'ready', ready=True)
        with self.assertRaises(ValueError):
            self.command(self.guest, 'start')
        self.guest.sockets.clear()
        with self.assertRaises(ValueError):
            self.command(self.host, 'start')
        self.guest.sockets.add(object())
        self.command(self.host, 'start')
        self.assertTrue(all(not member.ready for member in self.room.members))

    def test_duplicate_action_cannot_move_chips_twice(self):
        self.start()
        command = self.command(self.host, 'action', action='call', hand_id=self.room.hand.hand_id)
        before = self.room.hand.model_dump_json()
        revision = self.room.revision
        self.room.command(self.host, command)
        self.assertEqual(before, self.room.hand.model_dump_json())
        self.assertEqual(revision, self.room.revision)
        with self.assertRaises(ValueError):
            self.room.command(self.host, command.model_copy(update={'action': ActionType.FOLD}))

    def test_stale_wrong_turn_wrong_hand_and_spoofed_player_are_rejected(self):
        self.start()
        before = self.room.hand.model_dump_json()
        for member, revision, hand_id in [
            (self.host, self.room.revision - 1, self.room.hand.hand_id),
            (self.guest, self.room.revision, self.room.hand.hand_id),
            (self.host, self.room.revision, 'old-hand'),
        ]:
            with self.assertRaises(ValueError):
                self.room.command(member, RoomCommand(command_id='bad', revision=revision, kind='action', action='fold', hand_id=hand_id))
        self.assertEqual(before, self.room.hand.model_dump_json())
        with self.assertRaises(ValidationError):
            RoomCommand(command_id='bad', revision=self.room.revision, kind='action', player_id='hero')
        with self.assertRaises(ValidationError):
            RoomCommand(command_id='bad', revision=self.room.revision, kind='action', amount=10.5)

    def test_server_advances_streets_and_reveals_only_at_showdown(self):
        self.start()
        members = {member.player_id: member for member in self.room.members}
        for _ in range(30):
            hand = self.room.hand
            if hand.result:
                break
            allowed = hand.betting.legal_actions
            chosen = 'check' if ActionType.CHECK in allowed else 'call'
            self.command(members[hand.current_player_id], 'action', action=chosen, hand_id=hand.hand_id)
            if not self.room.hand.result:
                view = self.room.snapshot(self.host)['hand']
                self.assertEqual(view['players'][1]['cards'], [])
                self.assertIsNotNone(view['current_player_id'])
        self.assertEqual(self.room.hand.result.reason, 'showdown')
        self.assertEqual(len(self.room.snapshot(self.host)['hand']['players'][1]['cards']), 2)
        self.assertEqual(sum(p.stack for p in self.room.hand.players), 2000)

    def test_fold_winner_cards_remain_private_and_reconnect_restores_seat(self):
        self.start()
        self.command(self.host, 'action', action='fold', hand_id=self.room.hand.hand_id)
        view = self.room.snapshot(self.host)
        self.assertEqual(view['hand']['players'][1]['cards'], [])
        self.assertTrue(all(r['hand_strength'] is None for r in view['hand']['result']['player_results'] if r['player_id'] == self.guest.player_id))
        self.guest.sockets.clear()
        self.assertFalse(self.room.snapshot(self.host)['members'][1]['connected'])
        restored = self.room.authenticate(self.guest.token)
        self.assertIs(restored, self.guest)
        self.assertEqual(restored.player_id, 'villain')

    def test_capacity_and_roster_locked_after_first_deal(self):
        for i in range(4):
            member = self.room.join(f'Guest {i}')
            member.sockets.add(object())
        with self.assertRaises(ValueError):
            self.room.join('Seventh')
        self.start()
        self.assertEqual(len(self.room.hand.players), 6)
        with self.assertRaises(ValueError):
            self.room.join('Late')

    def test_two_room_games_do_not_share_a_deck_or_chips(self):
        self.start()
        original_deck = list(self.room.hand._deck)
        original_state = self.room.hand.model_dump_json()
        other, host = self.store.create('Another host')
        guest = other.join('Another friend')
        for member in [host, guest]:
            member.ready = True
            member.sockets.add(object())
        other.command(host, RoomCommand(command_id='start', revision=other.revision, kind='start'))
        other.command(host, RoomCommand(command_id='fold', revision=other.revision, kind='action', action='fold', hand_id=other.hand.hand_id))
        self.assertEqual(self.room.hand._deck, original_deck)
        self.assertEqual(self.room.hand.model_dump_json(), original_state)


if __name__ == '__main__':
    unittest.main()
