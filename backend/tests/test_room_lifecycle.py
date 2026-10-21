import unittest
from app.models.poker import ActionType
from app.services.room_service import RoomCommand, RoomStore


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.room, self.host = RoomStore().create('Host')
        self.guest = self.room.join('Guest')
        for member in self.room.members:
            member.sockets.add(object())
        self.counter = 0

    def command(self, member, kind, **data):
        self.counter += 1
        self.room.command(member, RoomCommand(command_id=str(self.counter), revision=self.room.revision, kind=kind, **data))

    def start(self):
        for member in self.room.seated:
            if not member.sitting_out:
                self.command(member, 'ready', ready=True)
        self.command(next(m for m in self.room.members if m.player_id == self.room.host_id), 'start')

    def test_timer_does_not_expire_early_and_cannot_act_twice(self):
        self.start()
        deadline = self.room.deadline
        self.assertFalse(self.room.tick(deadline - .01))
        self.assertTrue(self.room.tick(deadline))
        self.assertTrue(self.host.sitting_out)
        self.assertEqual(self.room.hand.history[-1].action, 'fold')
        self.assertIsNotNone(self.room.hand.result)
        revision = self.room.revision
        self.assertFalse(self.room.tick(deadline + 1))
        self.assertEqual(self.room.revision, revision)
        self.assertIsNone(self.room.deadline_at)

    def test_timeout_checks_when_free_and_skips_future_turns(self):
        self.start()
        self.command(self.host, 'action', action='call', hand_id=self.room.hand.hand_id)
        self.room.tick(self.room.deadline)
        self.assertTrue(self.guest.sitting_out)
        self.assertEqual(self.room.hand.street.value, 'flop')
        self.assertEqual(self.room.hand.current_player_id, self.host.player_id)
        self.assertEqual([a.action for a in self.room.hand.history[-2:]], ['check', 'check'])
        self.assertIsNotNone(self.room.deadline_at)

    def test_sit_out_preserves_timer_for_other_player(self):
        third = self.room.join('Third'); third.sockets.add(object())
        self.start()
        deadline = self.room.deadline
        self.command(third, 'sit_out', sit_out=True)
        self.assertEqual(self.room.deadline, deadline)
        with self.assertRaises(ValueError):
            self.command(third, 'sit_out', sit_out=False)

    def test_both_sit_out_resolves_without_deadlock(self):
        self.start()
        self.command(self.guest, 'sit_out', sit_out=True)
        self.command(self.host, 'sit_out', sit_out=True)
        self.assertIsNotNone(self.room.hand.result)
        self.assertEqual(sum(p.stack for p in self.room.hand.players), 2000)
        with self.assertRaises(ValueError):
            self.command(self.host, 'ready', ready=True)
        self.command(self.host, 'sit_out', sit_out=False)
        self.assertFalse(self.host.sitting_out)

    def test_sit_out_is_excluded_next_hand_and_stacks_survive_roster_change(self):
        third = self.room.join('Third'); third.sockets.add(object())
        self.start()
        while not self.room.hand.result:
            actor = next(m for m in self.room.members if m.player_id == self.room.hand.current_player_id)
            self.command(actor, 'action', action='fold', hand_id=self.room.hand.hand_id)
        stacks = {m.player_id: m.stack for m in self.room.members}
        self.command(self.guest, 'sit_out', sit_out=True)
        self.start()
        self.assertEqual({p.id for p in self.room.hand.players}, {self.host.player_id, third.player_id})
        self.assertEqual(sum(p.stack for p in self.room.hand.players) + self.room.hand.pot,
                         stacks[self.host.player_id] + stacks[third.player_id])
        self.assertEqual(self.guest.stack, stacks[self.guest.player_id])
        self.assertEqual(self.room.hand.dealer_player_id, third.player_id)

    def test_leave_transfers_host_revokes_token_and_releases_seat_between_hands(self):
        self.start()
        command_id = str(self.counter + 1)
        self.command(self.host, 'leave')
        self.assertTrue(self.room.hand.result)
        self.assertEqual(self.room.host_id, self.guest.player_id)
        with self.assertRaises(ValueError):
            self.room.authenticate(self.host.token)
        newcomer = self.room.join('New')
        newcomer.sockets.add(object())
        self.assertEqual(newcomer.seat, self.host.seat)
        self.assertNotEqual(newcomer.player_id, self.host.player_id)
        self.assertEqual(self.room.host_id, self.guest.player_id)
        view = self.room.snapshot(newcomer)
        self.assertTrue(all(p['cards'] == [] for p in view['hand']['players']))
        self.start()
        self.assertEqual(sum(p.stack for p in self.room.hand.players) + self.room.hand.pot, 2005)

    def test_leaving_out_of_turn_does_not_fold_other_players(self):
        third = self.room.join('Third'); third.sockets.add(object())
        self.start()
        actor = self.room.hand.current_player_id
        self.command(third, 'leave')
        self.assertEqual(self.room.hand.current_player_id, actor)
        self.assertFalse(self.room.hand.result)
        self.assertTrue(self.room.snapshot(third)['viewer_left'])
        with self.assertRaises(ValueError):
            self.room.join('Too soon')

    def test_reconnect_does_not_reset_deadline(self):
        self.start()
        deadline = self.room.deadline
        self.host.sockets.clear()
        self.assertIs(self.room.authenticate(self.host.token), self.host)
        self.host.sockets.add(object())
        self.assertEqual(self.room.deadline, deadline)
        self.assertEqual(self.room.snapshot(self.host)['turn_seconds'], 30)


if __name__ == '__main__':
    unittest.main()
