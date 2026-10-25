import unittest
from app.models.poker import ActionType, HandAction, Street, PlayerStatus
from app.services.poker_engine import PokerEngine
from app.services.preflop_rules import advise, expand, OPEN
from app.services.decision_engine import DecisionEngine
from backend.tests.test_coach_rules import cards

class PreflopRulesTests(unittest.TestCase):
    def state(self,n=6,own='Ah Jd',seat=3,stack=1000):
        state=PokerEngine().start_hand(player_count=n,starting_stacks=[stack]*n)
        player=state.players[seat];player.cards=cards(own);state.current_player_id=player.id
        PokerEngine()._refresh_betting(state)
        return state,player

    def result(self,s,p,equity=.6):
        return advise(s,p,equity,.25,min(p.stack,max(x.current_bet for x in s.players)-p.current_bet))

    def raised(self,own='Ah Jd',opener=3,seat=2,total=30,stack=1000):
        s,p=self.state(6,own,seat,stack)
        raiser=s.players[opener];raiser.stack-=total-raiser.current_bet;raiser.current_bet=total
        s.history.append(HandAction(player_id=raiser.id,action='raise',amount=total,street=Street.PREFLOP))
        s.last_full_raise=total-s.big_blind
        PokerEngine()._refresh_betting(s)
        return s,p

    def test_expansion_and_position_change_the_opening_decision(self):
        self.assertEqual(expand('TT+ AJs+'),{'TT','JJ','QQ','KK','AA','AJs','AQs','AKs'})
        s,p=self.state();self.assertEqual(self.result(s,p)['action'],'fold')
        s,p=self.state(seat=0);self.assertEqual(self.result(s,p)['action'],'raise')
        self.assertTrue(OPEN['early'] < OPEN['button'])

    def test_one_raise_response_depends_on_opener_position(self):
        s,p=self.raised();a=self.result(s,p);self.assertEqual(a['action'],'fold')
        s,p=self.raised(opener=0);a=self.result(s,p);self.assertEqual(a['action'],'call')
        self.assertEqual(a['opener_position'],'button')

    def test_limpers_and_callers_change_scenario_and_size(self):
        s,p=self.state(own='Ah Kd',seat=0)
        base=self.result(s,p)
        s.history.append(HandAction(player_id=s.players[3].id,action='call',amount=10,street=Street.PREFLOP))
        a=self.result(s,p);self.assertEqual(a['scenario'],'Limped pot');self.assertGreater(a['amount'],base['amount'])
        s,p=self.raised(own='Ah Ad');s.history.append(HandAction(player_id=s.players[4].id,action='call',amount=30,street=Street.PREFLOP))
        self.assertEqual(self.result(s,p)['scenario'],'Raise and callers')

    def test_short_stack_removes_speculative_opens_and_other_private_cards_do_not_matter(self):
        s,p=self.state(own='5h 4h',seat=0);self.assertEqual(self.result(s,p)['action'],'raise')
        short,q=self.state(own='5h 4h',seat=0,stack=150);self.assertEqual(self.result(short,q)['action'],'fold')
        a=self.result(s,p)
        for other in s.players:
            if other.id!=p.id:other.cards=cards('2c 3d')
        s._deck.reverse();self.assertEqual(self.result(s,p),a)

    def test_folded_short_seat_does_not_shorten_reference_stack(self):
        s,p=self.state(seat=0);s.players[3].stack=1;s.players[3].status=PlayerStatus.FOLDED
        self.assertEqual(self.result(s,p)['effective_stack_bb'],100)

    def test_threebet_and_allin_are_marked_as_fallback_without_automatic_raise(self):
        s,p=self.raised(own='Ah Ad');s.history.append(HandAction(player_id=s.players[4].id,action='raise',amount=90,street=Street.PREFLOP))
        a=self.result(s,p);self.assertFalse(a['range_covered']);self.assertNotEqual(a['action'],'raise')
        s,p=self.raised(own='Ah Ad');s.players[3].stack=0
        a=self.result(s,p);self.assertFalse(a['range_covered']);self.assertIsNone(a['amount'])

    def test_small_pairs_need_position_stack_and_price(self):
        s,p=self.raised(own='3h 3d',opener=3,seat=0);self.assertEqual(self.result(s,p)['action'],'call')
        s,p=self.raised(own='3h 3d',opener=3,seat=0,stack=300);self.assertEqual(self.result(s,p)['action'],'fold')
        s,p=self.raised(own='Ah Qh',total=120);self.assertEqual(self.result(s,p)['action'],'fold')

    def test_raises_are_legal_and_use_a_total_not_an_increment(self):
        for count in range(2,7):
            for seat in range(count):
                s,p=self.state(count,'Ah Ad',seat)
                analysis=DecisionEngine().analyze(s,p.id)
                self.assertIn(analysis.recommended_action,s.betting.legal_actions)
                if analysis.recommended_action=='raise':
                    self.assertGreaterEqual(analysis.recommended_amount,s.betting.min_raise_to)
                    self.assertLessEqual(analysis.recommended_amount,s.betting.max_raise_to)
                self.assertEqual(analysis.rule_advice['action'],analysis.recommended_action)
                self.assertEqual(analysis.rule_advice['reason'],analysis.coach_summary)
