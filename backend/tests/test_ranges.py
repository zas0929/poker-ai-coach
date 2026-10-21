import unittest

from app.models.poker import Card, HandAction, HandState, Player, Rank, Street, Suit
from app.services.decision_engine import DecisionEngine
from app.services.equity_service import EquityService
from app.services.range_service import OpponentRange, RangeService, WeightedCombo


def card(rank, suit):
    return Card(rank=Rank(rank), suit=Suit(suit))


def state_for(hero=None, board=None, history=None):
    board = board or []
    return HandState(
        hand_id="control", street={0: Street.PREFLOP, 3: Street.FLOP, 4: Street.TURN, 5: Street.RIVER}[len(board)],
        pot=100, small_blind=5, big_blind=10, dealer_player_id="hero", current_player_id="hero",
        board=board, history=history or [], players=[
            Player(id="hero", name="You", stack=1000, position="small_blind_button",
                   cards=hero or [card("A", "spades"), card("K", "hearts")]),
            Player(id="villain", name="Opponent", stack=1000, position="big_blind",
                   cards=[card("2", "clubs"), card("3", "clubs")]),
        ],
    )


def action(player, kind, street=Street.PREFLOP):
    return HandAction(player_id=player, action=kind, street=street)


def class_probability(inferred, notation):
    return sum(c.weight for c in inferred.combos if RangeService.notation(c.cards) == notation) / sum(c.weight for c in inferred.combos)


class RangeTest(unittest.TestCase):
    def test_blinds_do_not_reveal_strength(self):
        state = state_for(history=[action("villain", "big_blind")])
        inferred = RangeService().infer(state)
        self.assertEqual(len(inferred.combos), 1225)
        self.assertEqual({c.weight for c in inferred.combos}, {1.0})
        self.assertEqual(inferred.summary.model, "uniform")

    def test_reraise_increases_premium_weight(self):
        state = state_for()
        baseline = RangeService().infer(state)
        state.history = [action("hero", "raise"), action("villain", "raise")]
        raised = RangeService().infer(state)
        self.assertGreater(class_probability(raised, "AA"), class_probability(baseline, "AA"))
        self.assertLess(class_probability(raised, "72o"), class_probability(baseline, "72o"))
        self.assertLess(raised.summary.effective_combos, raised.summary.legal_combos)

    def test_position_changes_opening_range(self):
        state = state_for(history=[action("villain", "raise")])
        big_blind_range = RangeService().infer(state)
        state.players[1].position = "small_blind_button"
        button_range = RangeService().infer(state)
        self.assertGreater(button_range.summary.effective_combos, big_blind_range.summary.effective_combos)

    def test_blockers_remove_known_cards_but_not_hidden_cards(self):
        board = [card("Q", "spades"), card("J", "spades"), card("T", "spades")]
        state = state_for(board=board)
        inferred = RangeService().infer(state)
        blocked = {(c.rank, c.suit) for c in state.players[0].cards + board}
        self.assertEqual(len(inferred.combos), 1081)
        self.assertTrue(all((c.rank, c.suit) not in blocked for combo in inferred.combos for c in combo.cards))
        self.assertTrue(any(card("2", "clubs") in combo.cards for combo in inferred.combos))

    def test_postflop_raise_retains_bluffs_and_favours_value(self):
        state = state_for(board=[card("K", "clubs"), card("7", "diamonds"), card("2", "hearts")],
                          history=[action("villain", "raise", Street.FLOP)])
        inferred = RangeService().infer(state)
        weights = {RangeService.notation(c.cards): c.weight for c in inferred.combos}
        self.assertGreater(weights["77"], weights["Q9o"])
        self.assertGreater(weights["Q9o"], 0)

    def test_action_weight_does_not_see_later_board(self):
        flop = [card("K", "clubs"), card("7", "diamonds"), card("2", "hearts")]
        history = [action("villain", "bet", Street.FLOP)]
        at_flop = RangeService().infer(state_for(board=flop, history=history))
        at_turn = RangeService().infer(state_for(board=flop + [card("Q", "hearts")], history=history))
        # Compare a specific surviving hand before and after a new card is dealt.
        pick = lambda r: next(c.weight for c in r.combos if c.cards == (card("9", "spades"), card("8", "spades")))
        self.assertEqual(pick(at_flop), pick(at_turn))

    def test_rejects_multiway_instead_of_silently_using_one_opponent(self):
        state = state_for()
        state.players.append(Player(id="third", name="Third", stack=100, position="button"))
        with self.assertRaisesRegex(ValueError, "heads-up"):
            RangeService().infer(state)


class EquityTest(unittest.TestCase):
    def test_royal_flush_on_board_is_exact_split(self):
        state = state_for(hero=[card("2", "clubs"), card("3", "clubs")],
                          board=[card(r, "spades") for r in ["A", "K", "Q", "J", "T"]])
        estimate = EquityService().estimate(state)
        self.assertEqual(estimate.equity, 0.5)
        self.assertEqual(estimate.method, "exact_river")
        self.assertEqual(estimate.samples, 990)
        self.assertEqual(estimate.sampling_error, 0)

    def test_weighted_river_matches_analytical_result(self):
        state = state_for(hero=[card("K", "spades"), card("K", "hearts")], board=[
            card("2", "clubs"), card("4", "diamonds"), card("7", "hearts"),
            card("9", "spades"), card("J", "clubs"),
        ])
        inferred = RangeService().infer(state)
        inferred.combos = [
            WeightedCombo((card("A", "clubs"), card("A", "diamonds")), 3.0),
            WeightedCombo((card("Q", "clubs"), card("Q", "diamonds")), 1.0),
        ]
        self.assertEqual(EquityService().estimate(state, opponent_range=inferred).equity, 0.25)

    def test_simulation_is_stable_and_ignores_hidden_cards(self):
        state = state_for(board=[card("Q", "spades"), card("J", "diamonds"), card("T", "clubs")],
                          history=[action("villain", "bet", Street.FLOP)])
        service = EquityService()
        first = service.estimate(state, simulations=250)
        state.players[1].cards = [card("A", "diamonds"), card("A", "hearts")]
        second = service.estimate(state, simulations=250)
        self.assertEqual(first, second)
        self.assertGreater(first.sampling_error, 0)

    def test_aces_versus_kings_preflop_control(self):
        state = state_for(hero=[card("A", "spades"), card("A", "hearts")])
        inferred = RangeService().infer(state)
        inferred.combos = [WeightedCombo((card("K", "clubs"), card("K", "diamonds")), 1.0)]
        estimate = EquityService().estimate(state, opponent_range=inferred, simulations=3000)
        self.assertGreater(estimate.equity, 0.78)
        self.assertLess(estimate.equity, 0.86)

    def test_invalid_cards_and_simulation_count(self):
        service = EquityService()
        with self.assertRaisesRegex(ValueError, "positive"):
            service.estimate(state_for(), simulations=0)
        state = state_for()
        state.board = [state.players[0].cards[0], card("4", "clubs"), card("5", "clubs")]
        with self.assertRaisesRegex(ValueError, "distinct"):
            service.estimate(state)


class DecisionRangeTest(unittest.TestCase):
    def test_all_in_call_does_not_recommend_impossible_raise(self):
        state = state_for(hero=[card("A", "spades"), card("K", "spades")], board=[
            card("Q", "spades"), card("J", "spades"), card("T", "spades"),
            card("3", "hearts"), card("4", "clubs"),
        ])
        state.players[0].stack = 20
        state.players[1].current_bet = 100
        analysis = DecisionEngine().analyze(state)
        self.assertEqual(analysis.recommended_action, "call")

    def test_short_all_in_call_excludes_uncalled_overbet(self):
        state = state_for(board=[card(r, "spades") for r in ["Q", "J", "T"]])
        state.players[0].stack = 20
        state.players[1].current_bet = 100
        state.pot = 140
        analysis = DecisionEngine().analyze(state)
        # 80 of the 100 overbet is returned: call 20 into a contestable pot of 60.
        self.assertEqual(analysis.call_amount, 20)
        self.assertEqual(analysis.required_equity, 0.25)
        self.assertEqual(analysis.ev_call, round(analysis.equity * 80 - 20, 2))
        self.assertIsNotNone(analysis.opponent_range)
        self.assertNotIn("random opponent", " ".join(analysis.notes))


if __name__ == "__main__":
    unittest.main()
