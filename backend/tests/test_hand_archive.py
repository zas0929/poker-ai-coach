import json
import random
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from app.api import rooms as room_api
from app.models.poker import ActionType
from app.services.hand_archive import replay_hand
from app.services.room_service import RoomCommand, RoomStore, RoomSettings


class HandArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = RoomStore(Path(self.directory.name) / 'archive.sqlite3')
        self.store.open()
        self.room, self.host = self.store.create('Host', settings=RoomSettings(starting_stack=1000, small_blind=5, big_blind=10, auto_deal=False))
        self.guest = self.store.apply(self.room, lambda: self.room.join('Guest'), 'join')
        for member in self.room.members:
            member.sockets.add(object())
        self.counter = 0
        self.original_store = room_api.store
        room_api.store = self.store

    def tearDown(self):
        room_api.store = self.original_store
        self.store.close()
        self.directory.cleanup()

    def command(self, member, kind, **data):
        self.counter += 1
        cmd = RoomCommand(command_id=str(self.counter), revision=self.room.revision, kind=kind, **data)
        self.store.apply(self.room, lambda: self.room.command(member, cmd), kind)

    def start(self):
        for member in self.room.seated:
            self.command(member, 'ready', ready=True)
        self.command(self.host, 'start')

    def action(self, kind, amount=None):
        hand = self.room.hand
        actor = next(m for m in self.room.members if m.player_id == hand.current_player_id)
        self.command(actor, 'action', action=kind, amount=amount, hand_id=hand.hand_id)

    def archive(self, viewer=None):
        return self.store.repository.archived_hand(self.room.code, self.room.hand.hand_id,
                                                   (viewer or self.host).player_id)

    def finish_checkdown(self):
        while not self.room.hand.result:
            self.action('check' if ActionType.CHECK in self.room.hand.betting.legal_actions else 'call')

    def test_fold_summary_uses_net_and_never_reveals_winner_cards(self):
        self.start(); self.action('fold')
        page = self.store.repository.history_page(self.room.code, self.host.player_id)
        self.assertEqual(len(page['items']), 1)
        self.assertEqual(page['items'][0]['net'], -5)
        self.assertEqual(page['items'][0]['committed'], 5)
        self.assertEqual(page['items'][0]['amount_won'], 0)
        review = self.archive()
        self.assertIsNone(review['warning'])
        self.assertEqual(len(review['frames']), 2)
        self.assertEqual(review['hand']['players'][1]['cards'], [])
        self.assertEqual(review['frames'][0]['decision']['call_amount'], 5)
        self.assertEqual(review['frames'][0]['decision']['committed_by_action'], 0)
        self.assertEqual(self.archive(self.guest)['hand']['players'][1]['cards'],
                         self.room.hand.players[1].model_dump(mode='json')['cards'])

    def test_replay_reaches_all_streets_without_future_board_or_cards(self):
        self.start(); self.finish_checkdown()
        review = self.archive()
        self.assertIsNone(review['warning'])
        self.assertEqual(review['frames'][0]['hand']['board'], [])
        board_lengths = {len(f['hand']['board']) for f in review['frames']}
        self.assertEqual(board_lengths, {0, 3, 4, 5})
        for frame in review['frames'][:-1]:
            self.assertFalse(frame['hand']['result'])
            self.assertEqual(frame['hand']['players'][1]['cards'], [])
            self.assertNotIn('_deck', frame['hand'])
        self.assertEqual(len(review['frames'][-1]['hand']['players'][1]['cards']), 2)
        self.assertAlmostEqual(review['frames'][0]['decision']['break_even_equity'], .25)
        self.assertTrue(any(f['decision'] and f['decision']['made_hand'] for f in review['frames']))

    def test_raise_reconstruction_uses_total_raise_not_committed_increment(self):
        self.start(); self.action('raise', 50); self.action('call'); self.finish_checkdown()
        review = self.archive()
        self.assertIsNone(review['warning'])
        self.assertEqual(review['frames'][0]['decision']['description'], 'raise to 50')
        self.assertEqual(review['frames'][0]['decision']['committed_by_action'], 45)
        self.assertEqual(review['frames'][1]['hand']['pot'], 60)

    def test_short_all_in_and_uncalled_returns_preserve_review_accounting(self):
        self.host.stack = 1000; self.guest.stack = 100
        self.start(); self.action('raise', 1000); self.action('call')
        review = self.archive()
        self.assertIsNone(review['warning'])
        self.assertEqual(sum(p['stack'] for p in review['hand']['players']), 1100)
        self.assertEqual(review['hand']['result']['pot_awarded'], 200)
        page = self.store.repository.history_page(self.room.code, self.guest.player_id)
        self.assertEqual(page['items'][0]['committed'], 100)
        self.assertEqual(page['items'][0]['net'], page['items'][0]['amount_won'] - 100)

    def test_side_pots_and_folded_cards_remain_correct(self):
        third = self.store.apply(self.room, lambda: self.room.join('Third'), 'join')
        third.sockets.add(object())
        self.host.stack, self.guest.stack, third.stack = 100, 200, 300
        self.start(); self.action('raise', 100); self.action('raise', 200); self.action('call')
        review = self.archive()
        self.assertIsNone(review['warning'])
        self.assertEqual([p['amount'] for p in review['hand']['result']['pots']], [300, 200])
        self.assertIsNone(review['frames'][0]['decision']['break_even_equity'])
        self.assertIn('Side-pot', review['frames'][0]['decision']['note'])
        for frame in review['frames'][:-1]:
            self.assertTrue(all(not p['cards'] for p in frame['hand']['players'] if p['id'] != self.host.player_id))

    def test_pagination_is_stable_when_new_hand_finishes(self):
        for _ in range(4):
            self.start(); self.action('fold')
        first = self.store.repository.history_page(self.room.code, self.host.player_id, 2)
        self.assertEqual(len(first['items']), 2)
        self.assertIsNotNone(first['next_cursor'])
        self.start(); self.action('fold')
        second = self.store.repository.history_page(self.room.code, self.host.player_id, 2, first['next_cursor'])
        self.assertEqual(len(second['items']), 2)
        self.assertIsNone(second['next_cursor'])
        self.assertFalse(set(i['hand_id'] for i in first['items']) & set(i['hand_id'] for i in second['items']))

    def test_new_member_cannot_read_hands_played_before_they_joined(self):
        self.start(); self.action('fold')
        old_id = self.room.hand.hand_id
        newcomer = self.store.apply(self.room, lambda: self.room.join('New'), 'join')
        self.assertEqual(self.store.repository.history_page(self.room.code, newcomer.player_id)['items'], [])
        with self.assertRaises(ValueError):
            self.store.repository.archived_hand(self.room.code, old_id, newcomer.player_id)

    def test_room_boundary_and_missing_or_revoked_tokens(self):
        self.start(); self.action('fold')
        other, stranger = self.store.create('Stranger')
        for auth in [None, '', 'Bearer wrong', 'Bearer ' + stranger.token]:
            with self.assertRaises(HTTPException) as error:
                room_api.history_member(self.room.code, auth)
            self.assertEqual(error.exception.status_code, 401)
        with self.assertRaises(ValueError):
            self.store.repository.archived_hand(other.code, self.room.hand.hand_id, stranger.player_id)
        self.assertEqual(room_api.history_member(self.room.code, 'Bearer ' + self.host.token)[1], self.host)
        self.command(self.host, 'leave')
        with self.assertRaises(HTTPException):
            room_api.history_member(self.room.code, 'Bearer ' + self.host.token)

    def test_replacement_seat_does_not_inherit_previous_occupants_archive(self):
        self.start(); self.action('fold')
        old_hand = self.room.hand.hand_id
        self.command(self.host, 'leave')
        replacement = self.store.apply(self.room, lambda: self.room.join('Replacement'), 'join')
        self.assertEqual(replacement.seat, self.host.seat)
        self.assertNotEqual(replacement.player_id, self.host.player_id)
        self.assertEqual(self.store.repository.history_page(self.room.code, replacement.player_id)['items'], [])
        with self.assertRaises(ValueError):
            self.store.repository.archived_hand(self.room.code, old_hand, replacement.player_id)

    def test_folded_opponent_cards_and_strength_stay_hidden_at_showdown(self):
        third = self.store.apply(self.room, lambda: self.room.join('Third'), 'join')
        third.sockets.add(object())
        self.start(); self.action('fold'); self.finish_checkdown()
        review = self.archive(self.guest)
        self.assertIsNone(review['warning'])
        hidden = next(p for p in review['hand']['players'] if p['id'] == self.host.player_id)
        self.assertEqual(hidden['cards'], [])
        hidden_result = next(p for p in review['hand']['result']['player_results'] if p['player_id'] == self.host.player_id)
        self.assertIsNone(hidden_result['hand_strength'])

    def test_live_hands_have_no_archive_and_reading_is_read_only(self):
        self.start()
        with self.assertRaises(ValueError):
            self.archive()
        self.action('fold')
        before = self.room.to_record()
        events = self.store.repository.connection.execute('SELECT count(*) FROM room_events').fetchone()
        review = self.archive()
        self.store.repository.history_page(self.room.code, self.host.player_id)
        self.assertEqual(self.room.to_record(), before)
        self.assertEqual(self.store.repository.connection.execute('SELECT count(*) FROM room_events').fetchone(), events)
        self.assertNotIn(self.host.token, json.dumps(review))
        self.assertNotIn(self.guest.token, json.dumps(review))
        self.assertNotIn('_deck', json.dumps(review))

    def test_archive_survives_restart_and_corrupt_replay_uses_saved_result(self):
        self.start(); self.finish_checkdown()
        review = self.archive()
        path = self.store.repository.path
        self.store.close(); self.store = RoomStore(path); self.store.open()
        restored = self.store.repository.archived_hand(self.room.code, self.room.hand.hand_id, self.host.player_id)
        self.assertEqual(restored, review)
        raw = self.room.to_record()['hand']; raw['history'][2]['amount'] = 900
        fallback = replay_hand(raw, self.host.player_id)
        self.assertTrue(fallback['warning'])
        self.assertEqual(len(fallback['frames']), 1)
        self.assertEqual(fallback['hand']['result'], review['hand']['result'])

    def test_80_random_multiway_hands_replay_to_exact_saved_payouts(self):
        rng = random.Random(84922)
        from app.services.poker_engine import PokerEngine
        for number in range(80):
            count = rng.randint(2, 6)
            engine = PokerEngine()
            hand = engine.start_hand(player_count=count, starting_stacks=[rng.randint(1, 20) * 10 for _ in range(count)])
            for _ in range(600):
                if hand.result:
                    break
                allowed = hand.betting
                action = rng.choice(allowed.legal_actions)
                amount = None
                if action == ActionType.BET:
                    amount = rng.choice([allowed.min_bet, allowed.max_raise_to])
                if action == ActionType.RAISE:
                    amount = rng.choice([allowed.min_raise_to, allowed.max_raise_to])
                hand = engine.apply_action(hand, hand.current_player_id, action, amount)
                while not hand.current_player_id and not hand.result:
                    hand = engine.advance(hand)
            self.assertTrue(hand.result)
            raw = hand.model_dump(mode='json'); raw['_deck'] = [c.model_dump(mode='json') for c in hand._deck]
            review = replay_hand(raw, hand.players[0].id)
            self.assertIsNone(review['warning'], f'Hand {number}: {hand.history}')
            self.assertEqual(review['frames'][-1]['hand']['result'], raw['result'])


if __name__ == '__main__':
    unittest.main()
