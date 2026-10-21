import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from fastapi import HTTPException
from app.api import hand
from app.models.poker import ActionType, PlayerActionRequest


class TrainingSessionTests(unittest.TestCase):
    def setUp(self):
        self.previous = hand.profile_states.copy()
        hand.profile_states.clear()
        self.binding = hand.training_owner.set(None)
        self.local_state = hand.current_state

    def tearDown(self):
        hand.profile_states.clear()
        hand.profile_states.update(self.previous)
        hand.training_owner.reset(self.binding)
        hand.current_state = self.local_state

    def as_profile(self, owner, operation, *args, **kwargs):
        binding = hand.training_owner.set(owner)
        try:
            return operation(*args, **kwargs)
        finally:
            hand.training_owner.reset(binding)

    def test_profiles_have_separate_hands_and_resume_their_own_table(self):
        a = self.as_profile('alice', hand.start_hand)
        b = self.as_profile('bob', hand.start_hand, player_count=4)
        self.assertNotEqual(a.hand_id, b.hand_id)
        self.assertEqual(self.as_profile('alice', hand.start_hand).hand_id, a.hand_id)
        self.assertEqual(len(self.as_profile('bob', hand.read_state).players), 4)
        self.as_profile('alice', hand.apply_action, PlayerActionRequest(action=ActionType.FOLD))
        self.assertIsNotNone(self.as_profile('alice', hand.read_state).result)
        self.assertIsNone(self.as_profile('bob', hand.read_state).result)
        self.assertIs(hand.current_state, self.local_state)

    def test_unknown_profile_cannot_read_another_profiles_table(self):
        self.as_profile('alice', hand.start_hand)
        with self.assertRaises(HTTPException) as caught:
            self.as_profile('bob', hand.read_state)
        self.assertEqual(caught.exception.status_code, 404)

    def test_concurrent_requests_keep_context_and_restore_the_local_session(self):
        barrier = Barrier(2)
        def play(owner):
            state = self.as_profile(owner, hand.start_hand)
            barrier.wait(timeout=5)
            self.as_profile(owner, hand.apply_action, PlayerActionRequest(action=ActionType.CALL))
            again = self.as_profile(owner, hand.read_state)
            self.assertEqual(state.hand_id, again.hand_id)
            return again.hand_id
        with ThreadPoolExecutor(max_workers=2) as executor:
            a, b = executor.map(play, ['alice', 'bob'])
        self.assertNotEqual(a, b)
        self.assertIs(hand.current_state, self.local_state)

    def test_capacity_never_evicts_another_active_hand(self):
        now = hand.monotonic()
        hand.profile_states.update({str(i): (None, now) for i in range(hand.MAX_TRAINING_SESSIONS)})
        with self.assertRaises(HTTPException) as caught:
            self.as_profile('new-player', hand.start_hand)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(len(hand.profile_states), hand.MAX_TRAINING_SESSIONS)

    def test_expired_idle_tables_free_capacity(self):
        hand.profile_states['idle'] = (None, hand.monotonic() - hand.TRAINING_IDLE_SECONDS - 1)
        self.as_profile('new-player', hand.start_hand)
        self.assertNotIn('idle', hand.profile_states)
