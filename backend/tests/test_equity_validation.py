"""External ranges must not manufacture equity with illegal cards or weights."""
import unittest
from copy import deepcopy
from app.models.poker import Player
from app.services.equity_service import EquityService
from app.services.range_service import RangeService, WeightedCombo
from tests.test_ranges import state_for, card

class EquityValidationTests(unittest.TestCase):
    def test_invalid_ranges_are_rejected_in_heads_up_and_multiway(self):
        for multiway in (False, True):
            for bad in ('negative', 'nan', 'infinity', 'blocked', 'duplicate_card', 'duplicate_combo', 'zero'):
                with self.subTest(multiway=multiway, bad=bad):
                    state = state_for(board=[card('2','clubs'), card('4','diamonds'), card('7','hearts'), card('9','spades'), card('J','clubs')])
                    ranges = [RangeService().infer(state)]
                    combo = (card('Q','clubs'), card('Q','diamonds'))
                    ranges[0].combos = [WeightedCombo(combo, 1)]
                    if bad in ('negative', 'nan', 'infinity', 'zero'):
                        ranges[0].combos += [WeightedCombo((card('T','clubs'),card('T','diamonds')), {'negative':-0.1,'nan':float('nan'),'infinity':float('inf'),'zero':0}[bad])]
                        if bad == 'zero': ranges[0].combos = [WeightedCombo(combo, 0)]
                    elif bad == 'blocked': ranges[0].combos = [WeightedCombo((state.players[0].cards[0], combo[1]), 1)]
                    elif bad == 'duplicate_card': ranges[0].combos = [WeightedCombo((combo[0], combo[0]), 1)]
                    else: ranges[0].combos += [WeightedCombo(tuple(reversed(combo)), 1)]
                    if multiway:
                        state.players.append(Player(id='third',name='Third',stack=1000,position='cutoff',cards=[]))
                        other = deepcopy(ranges[0])
                        other.combos = [WeightedCombo((card('8','spades'),card('8','hearts')),1)]
                        ranges.append(other)
                    with self.assertRaises(ValueError):
                        EquityService().estimate(state, opponent_ranges=ranges, opponent_range=ranges[0], simulations=2)

    def test_simulation_count_is_a_positive_integer(self):
        for count in (0, -1, 1.5, True):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'positive'):
                EquityService().estimate(state_for(), simulations=count)

    def test_zero_weight_legal_combos_are_allowed_when_total_is_positive(self):
        state = state_for()
        inferred = RangeService().infer(state)
        inferred.combos = [WeightedCombo((card('Q','clubs'),card('Q','diamonds')),1), WeightedCombo((card('T','clubs'),card('T','diamonds')),0)]
        self.assertGreaterEqual(EquityService().estimate(state,opponent_range=inferred,simulations=5).equity,0)
