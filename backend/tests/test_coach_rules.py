import unittest
from app.models.poker import Card, Street, PlayerStatus
from app.services.coach_rules import classify, advise
from app.services.hand_evaluator import HandEvaluator
from backend.tests.test_ranges import state_for, card

SUITS={'s':'spades','h':'hearts','d':'diamonds','c':'clubs'}
def cards(text):return [Card(rank=v[0],suit=SUITS[v[1]]) for v in text.split()]

class CoachRuleTests(unittest.TestCase):
    def test_hand_classification_uses_hole_cards_not_just_evaluator_category(self):
        ev=HandEvaluator()
        for own,board,label in [
            ('Ah Kd','As 7c 2h','Top pair, good kicker'),('Ah 3d','As 7c 2h','Top pair, weak kicker'),
            ('Qh Qd','Js 7c 2h','Overpair'),('3h 3d','Js 7c 4h','Underpair'),
            ('7h Ad','Ks 7c 2h','Middle pair'),('2d Ad','Ks 7c 2h','Bottom pair'),
            ('7h 7d','Ks 7c 2h','Set'),('Ah 3d','Ks Kc Kh 8s 2c','Trips on the board'),
            ('Ah 3d','Ks Kc 8h 8s 2c','Two pair with a board pair'),
            ('2h 3d','As Kc Qh Js Tc','Board-only hand')]:
            with self.subTest(own=own,board=board):self.assertEqual(classify(cards(own),cards(board),ev)[0],label)

    def advice(self,own,board,equity,call=10,required=.25,multi=False):
        state=state_for(hero=cards(own),board=cards(board))
        state.street=Street.RIVER if len(state.board)==5 else Street.TURN if len(state.board)==4 else Street.FLOP
        if multi:
            other=state.players[1].model_copy(deep=True);other.id='other';state.players.append(other)
        return advise(state,state.players[0],equity,required,call,HandEvaluator())

    def test_high_equity_alone_does_not_trigger_a_raise(self):
        self.assertEqual(self.advice('Ah 3d','As 7c 2h',.8)['action'],'call')
        self.assertEqual(self.advice('7h Ad','Ks 7c 2h',.8)['action'],'call')
        self.assertEqual(self.advice('7h Ad','Ks 7c 2h',.8,call=0)['action'],'check')
        self.assertEqual(self.advice('7h 7d','Ks 7c 2h',.8)['action'],'raise')

    def test_board_only_and_four_flush_do_not_get_automatic_value_bets(self):
        self.assertEqual(self.advice('2h 3d','As Kc Qh Js Tc',1,call=0)['action'],'check')
        a=self.advice('Ah Ad','Ks 7s 2s 3s',.8,call=0)
        self.assertEqual(a['action'],'check');self.assertIn('Flush possible',a['board_texture'])

    def test_actual_live_opponents_control_multiway_rules(self):
        a=self.advice('Ah Kd','As 7c 2h',.8,call=0,multi=True)
        self.assertEqual(a['action'],'check');self.assertEqual(a['live_opponents'],2)
        state=state_for(hero=cards('Ah Kd'),board=cards('As 7c 2h'))
        folded=state.players[1].model_copy(deep=True);folded.id='folded';folded.status=PlayerStatus.FOLDED
        state.players.append(folded)
        self.assertEqual(advise(state,state.players[0],.8,.25,0,HandEvaluator())['action'],'bet')

    def test_call_price_and_borderline_note(self):
        self.assertEqual(self.advice('Ah 3d','As 7c 2h',.15)['action'],'fold')
        self.assertTrue(self.advice('Ah 3d','As 7c 2h',.26)['close_price'])

    def test_engine_uses_rule_explanation_and_respects_legal_allin_call(self):
        from app.services.decision_engine import DecisionEngine
        state=state_for(hero=cards('As Ks'),board=cards('Qs Js Ts 3h 4c'))
        state.players[0].stack=20;state.players[1].current_bet=100
        analysis=DecisionEngine().analyze(state)
        self.assertEqual(analysis.recommended_action,'call')
        self.assertEqual(analysis.rule_advice['action'],'call')
        self.assertEqual(analysis.coach_summary,analysis.rule_advice['reason'])
        self.assertIsNone(analysis.recommended_amount)
