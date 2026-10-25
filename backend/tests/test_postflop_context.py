import unittest
from app.models.poker import ActionType, HandAction, PlayerStatus, Street
from app.services.coach_rules import advise, draw_completions
from app.services.decision_engine import DecisionEngine
from app.services.hand_evaluator import HandEvaluator
from backend.tests.test_ranges import state_for
from backend.tests.test_coach_rules import cards


class PostflopContextTests(unittest.TestCase):
    def state(self, own='Ah Kd', board='As 7c 2h'):
        return state_for(hero=cards(own), board=cards(board))

    def advice(self, state, equity=.8, required=.25, call=0):
        return advise(state, state.players[0], equity, required, call, HandEvaluator())

    def test_flush_and_straight_overlap_counts_distinct_cards(self):
        d=draw_completions(cards('8s 9s'),cards('6s 7h Ks'),HandEvaluator())
        self.assertEqual(d['outs'],15)  # 9 flush + 8 straight - 2 shared cards
        self.assertEqual(d['draws'],['flush draw','straight draw'])
        self.assertAlmostEqual(d['next_card_probability'],15/47)

    def test_wheel_gutshot_and_board_only_draw(self):
        ev=HandEvaluator()
        self.assertEqual(draw_completions(cards('Ah 2d'),cards('3s 4c Kh'),ev)['outs'],4)
        self.assertEqual(draw_completions(cards('2h 3d'),cards('Ts Js Qs Ks'),ev)['outs'],0)
        self.assertEqual(draw_completions(cards('Ah 2d'),cards('3s 4c Kh 8h 9d'),ev)['outs'],0)

    def test_free_draw_is_not_an_automatic_semibluff(self):
        a=self.advice(self.state('8s 9s','6s 7h Ks'),.7)
        self.assertEqual(a['action'],'check')
        self.assertIn('semi-bluff',a['reason'])

    def test_pure_draw_cannot_assume_two_free_cards_but_allin_can_use_showdown_equity(self):
        s=self.state('Ah 2h','Kh 7h 3c')
        a=self.advice(s,.4,.25,50)
        self.assertEqual(a['action'],'fold')
        self.assertEqual(a['purpose'],'Avoid chasing a draw')
        s.players[0].stack=50
        self.assertEqual(self.advice(s,.4,.25,50)['action'],'call')
        s.players[0].stack=1000;s.players[1].stack=0
        self.assertEqual(self.advice(s,.4,.25,50)['action'],'call')

    def test_position_changes_marginal_call_and_pair_value(self):
        s=self.state()
        self.assertEqual(self.advice(s,.64)['action'],'bet')
        s.dealer_player_id='villain'
        self.assertEqual(self.advice(s,.64)['action'],'check')
        self.assertEqual(self.advice(s,.27,.25,10)['action'],'fold')
        s.dealer_player_id='hero'
        self.assertEqual(self.advice(s,.27,.25,10)['action'],'call')

    def test_previous_aggressor_avoids_automatic_one_pair_donk(self):
        s=self.state();s.dealer_player_id='villain'
        s.history=[HandAction(player_id='villain',action='raise',street=Street.PREFLOP)]
        a=self.advice(s)
        self.assertEqual(a['action'],'check')
        self.assertIn('previous aggressor',a['reason'])
        s.history[0].player_id='hero'
        self.assertEqual(self.advice(s)['action'],'bet')

    def test_one_pair_under_late_street_pressure_needs_more_than_raw_price(self):
        s=self.state('Ah Kd','As 7c 2h 3s')
        self.assertEqual(self.advice(s,.3,.25,40)['action'],'fold')
        s.players[0].stack=40
        self.assertEqual(self.advice(s,.3,.25,40)['action'],'call')

    def test_raise_history_prevents_reraising_a_set_but_not_near_nut_hand(self):
        s=self.state('7h 7d','Ks 7c 2h')
        self.assertEqual(self.advice(s,.9,.25,10)['action'],'raise')
        s.history=[HandAction(player_id='villain',action='raise',street=Street.FLOP)]
        self.assertEqual(self.advice(s,.9,.25,10)['action'],'call')
        s.players[0].cards=cards('Kh Kd');s.board=cards('Ks 7c 7h')
        self.assertEqual(self.advice(s,.95,.25,10)['action'],'raise')

    def test_sizes_follow_texture_and_effective_stack_and_remain_legal(self):
        for own,board,eq,expected in [('Ah Kd','As 7c 2h',.8,34),('Ah Kd','As 7c 6c',.8,50),('7h 7d','Ks 7c 2h',.8,67),('7h 7d','Ks 7c 6c',.8,75)]:
            with self.subTest(board=board,own=own):
                a=self.advice(self.state(own,board),eq)
                self.assertEqual(a['amount'],expected)
        s=self.state('7h 7d','Ks 7c 2h');s.players[1].stack=40
        a=self.advice(s,.9)
        self.assertEqual(a['amount'],40)
        self.assertEqual(a['context']['stack_to_pot'],.4)
        s.players[0].stack=5
        self.assertEqual(self.advice(s,.9)['amount'],5)

    def test_folded_seats_and_hidden_cards_do_not_change_advice(self):
        s=self.state('8s 9s','6s 7h Ks');before=self.advice(s,.5,.2,10)
        s.players[1].cards=cards('Ac Ad');s._deck=cards('2h 3d')
        folded=s.players[1].model_copy(deep=True);folded.id='folded';folded.status=PlayerStatus.FOLDED;folded.stack=1
        s.players.append(folded)
        self.assertEqual(before,self.advice(s,.5,.2,10))

    def test_engine_uses_one_consistent_draw_profile_and_legal_size(self):
        s=self.state('8s 9s','6s 7h Ks')
        a=DecisionEngine().analyze(s)
        self.assertEqual(a.draw_profile.outs,15)
        self.assertEqual(a.rule_advice['version'],'postflop_rules_v2')
        self.assertEqual(a.coach_summary,a.rule_advice['reason'])
        self.assertEqual(a.recommended_amount,a.rule_advice['amount'])
        self.assertEqual(a.recommended_action,a.rule_advice['action'])

    def test_multiway_value_is_tighter_and_allin_seats_do_not_define_position(self):
        s=self.state()
        other=s.players[1].model_copy(deep=True);other.id='other';s.players.append(other)
        self.assertEqual(self.advice(s,.8)['action'],'check')
        s.dealer_player_id='other';s.players[1].stack=0;s.players[1].status=PlayerStatus.ALL_IN
        self.assertEqual(self.advice(s)['context']['position_label'],'Out of position')
        s.players[2].status=PlayerStatus.FOLDED
        self.assertEqual(self.advice(s)['context']['position_label'],'Out of position')

    def test_engine_keeps_recommendations_legal_on_all_streets_two_to_six_players(self):
        from app.services.poker_engine import PokerEngine
        from app.services.betting_rules import betting_options
        for count in range(2,7):
            engine=PokerEngine();state=engine.start_hand(player_count=count)
            seen=set()
            for _ in range(80):
                if state.result:
                    break
                if state.current_player_id is None:
                    state=engine.advance(state)
                    continue
                actor=state.current_player_id;options=betting_options(state,actor)
                if state.street in (Street.FLOP,Street.TURN,Street.RIVER) and state.street not in seen:
                    seen.add(state.street)
                    a=DecisionEngine().analyze(state,actor)
                    with self.subTest(count=count,street=state.street):
                        self.assertIn(a.recommended_action,options.legal_actions)
                        if a.recommended_action in ('bet','raise'):
                            self.assertIsNotNone(a.recommended_amount)
                            self.assertGreaterEqual(a.recommended_amount,options.min_bet if a.recommended_action=='bet' else options.min_raise_to)
                            self.assertLessEqual(a.recommended_amount,options.max_raise_to)
                state=engine.apply_action(state,actor,ActionType.CALL if options.call_amount else ActionType.CHECK)
            self.assertEqual(seen,{Street.FLOP,Street.TURN,Street.RIVER})
