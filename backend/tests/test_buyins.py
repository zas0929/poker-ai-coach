import tempfile
import unittest
from pathlib import Path
from app.services.room_service import RoomCommand, RoomStore
from app.services.room_repository import RoomStorageError


class BuyInTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RoomStore(Path(self.temp.name) / 'room.sqlite3'); self.store.open()
        self.room, self.host = self.store.create('Host', 600)
        self.guest = self.store.apply(self.room, lambda: self.room.join('Guest', 200), 'join')
        for member in self.room.members: member.sockets.add(object())
        self.counter = 0

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def command(self, member, kind, **values):
        self.counter += 1
        command = RoomCommand(command_id=str(self.counter), revision=self.room.revision, kind=kind, **values)
        self.store.apply(self.room, lambda: self.room.command(member, command), kind, command.command_id, member.player_id)
        return command

    def start(self):
        for member in self.room.members: self.command(member, 'ready', ready=True)
        self.command(self.host, 'start')

    def test_custom_stacks_reach_engine_without_extra_chips(self):
        self.start()
        self.assertEqual(sum(p.stack for p in self.room.hand.players) + self.room.hand.pot, 800)

    def test_top_up_retries_credit_only_once_and_survive_restart(self):
        command = self.command(self.guest, 'top_up', amount=50)
        self.store.apply(self.room, lambda: self.room.command(self.guest, command), 'top_up')
        self.assertEqual(self.guest.stack, 250)
        code, token = self.room.code, self.guest.token
        self.store.close(); self.store.open()
        self.assertEqual(self.store.get(code).authenticate(token).stack, 250)

    def test_top_up_during_hand_and_invalid_amounts_do_not_move_chips(self):
        for amount in [0, -1, 1000001]:
            with self.assertRaises(ValueError): self.command(self.host, 'top_up', amount=amount)
        self.assertEqual(self.host.stack, 600)
        self.start()
        with self.assertRaises(ValueError): self.command(self.host, 'top_up', amount=50)
        self.assertEqual(sum(p.stack for p in self.room.hand.players) + self.room.hand.pot, 800)

    def test_failed_top_up_is_rolled_back(self):
        self.store.repository.connection.execute("CREATE TRIGGER fail_topup BEFORE INSERT ON room_events BEGIN SELECT RAISE(ABORT,'test failure'); END")
        self.store.repository.connection.commit()
        with self.assertRaises(RoomStorageError): self.command(self.host, 'top_up', amount=50)
        self.assertEqual(self.host.stack, 600)

    def test_invalid_buy_in_does_not_add_a_seat(self):
        for amount in [0, 1, True, 2.5, 1000001]:
            with self.assertRaises(ValueError): self.room.join('Invalid', amount)
        self.assertEqual(len(self.room.members), 2)

    def test_settings_preserve_individual_buy_ins(self):
        self.command(self.host, 'settings', settings=dict(starting_stack=400, small_blind=2, big_blind=4, turn_seconds=30))
        self.assertEqual([m.stack for m in self.room.members], [600, 200])

    def test_top_up_after_completed_hand_is_not_overwritten_by_old_payout(self):
        self.start()
        self.command(self.host, 'action', hand_id=self.room.hand.hand_id, action='fold')
        before = self.host.stack
        self.command(self.host, 'top_up', amount=100)
        self.assertEqual(self.host.stack, before + 100)
        self.command(self.guest, 'ready', ready=True)
        self.assertEqual(self.host.stack, before + 100)
