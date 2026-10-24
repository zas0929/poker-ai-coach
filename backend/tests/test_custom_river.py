import unittest
from research.custom_river import RiverGame, demo_ranges

BOARD=['2c','4d','7h','9s','Jc']
class CustomRiverTests(unittest.TestCase):
    def test_two_to_six_players_have_zero_sum_payoffs_and_valid_strategies(self):
        for n in range(2,7):
            game=RiverGame(BOARD,[r[:1] for r in demo_ranges(n)])
            policy=game.train(4)
            for row in policy.values():
                self.assertAlmostEqual(sum(row),1)
                self.assertTrue(all(0<=p<=1 for p in row))
            for values in game.utilities.values():self.assertAlmostEqual(sum(values),0)
            self.assertEqual(len(game.ranges),n)
            self.assertTrue(all(len(k)==3 for k in game.keys))

    def test_learning_reduces_exact_best_response_gap_on_two_player_control(self):
        game=RiverGame(BOARD,demo_ranges(2))
        before=game.measure({k:[.5,.5] for k in game.keys})
        after=game.measure(game.train(300))
        self.assertLess(after['nash_conv_chips'],before['nash_conv_chips']/10)
        self.assertAlmostEqual(sum(after['policy_payoffs']),0)

    def test_identical_board_winner_control_is_not_hand_ranking_guess(self):
        game=RiverGame(['As','Ks','Qs','Js','Ts'],[[('2h2d',1)],[('3h3d',1)]])
        result=game.measure(game.train(300))
        self.assertLess(result['nash_conv_chips'],1)

    def test_best_response_does_not_peek_at_opponents_private_cards(self):
        game=RiverGame(BOARD,[[('AhAd',1),('QhQd',1)],[('KhKd',1)]])
        policy={}
        for key in game.keys:
            actor,_,history=key
            policy[key]=[0,1] if not history else ([.5,.5] if history==((0,'BET 50'),) else [1,0])
        result=game.measure(policy)
        # IP cannot choose a different call/fold for AA and QQ: its cards/history match.
        self.assertAlmostEqual(result['best_response_payoffs'][1],0)
        self.assertAlmostEqual(result['policy_payoffs'][1],-25)

    def test_colliding_ranges_and_oversized_games_are_rejected(self):
        for ranges in ([[('AhAh',1)],[('KhKd',1)]],[[('2cAh',1)],[('KhKd',1)]],[[('AhAd',1)],[('AdAh',1)]],[[('AhAd',float('nan'))],[('KhKd',1)]]):
            with self.assertRaises(ValueError):RiverGame(BOARD,ranges)
        with self.assertRaises(ValueError):RiverGame(BOARD,[r*3 for r in demo_ranges(6)])

    def test_chance_is_jointly_conditioned_on_card_collisions(self):
        game=RiverGame(BOARD,[[('AhAd',1),('QhQd',1)],[('AhAd',1),('KhKd',1)]])
        self.assertEqual(len(game.deals),3)
        self.assertTrue(all(abs(weight-1/3)<1e-9 for _,weight,_ in game.deals))

    def test_external_tree_conversion_refuses_nonmatching_action_sets(self):
        from research.compare_custom_policy import convert_policy
        game=RiverGame(BOARD,demo_ranges(2))
        with self.assertRaises(ValueError):convert_policy(game,{'player':1,'actions':['CHECK','BET 100.000000']})

    def test_invalid_card_notations_and_policies_are_rejected(self):
        for ranges in ([[('AhXx',1)],[('KhKd',1)]],[[('A',1)],[('KhKd',1)]]):
            with self.assertRaises(ValueError):RiverGame(BOARD,ranges)
        game=RiverGame(BOARD,demo_ranges(2))
        with self.assertRaises(ValueError):game.measure({})

    def test_external_rows_are_reordered_and_float32_roundoff_normalized(self):
        from research.compare_custom_policy import convert_policy
        game=RiverGame(BOARD,demo_ranges(2),stack=50)
        def external(node):
            if node.actor==-1:return {}
            actions=[a if not a.startswith('BET ') else 'BET 50.000000' for a in node.actions]
            reversed_actions=list(reversed(actions))
            return {'player':1-node.actor,'actions':reversed_actions,'strategy':{'strategy':{hand:[.5,.49999998] for hand,_ in game.ranges[node.actor]}},'childrens':{a:external(child) for a,child in zip(actions,node.children)}}
        policy=convert_policy(game,external(game.root))
        self.assertEqual(set(policy),game.keys)
        self.assertTrue(all(abs(sum(row)-1)<1e-12 for row in policy.values()))
        self.assertAlmostEqual(sum(game.measure(policy)['policy_payoffs']),0)

    def test_plus_has_normalized_policies_for_every_player_count(self):
        for n in range(2,7):
            game=RiverGame(BOARD,[r[:1] for r in demo_ranges(n)])
            policy=game.train(8,method='cfr_plus')
            self.assertEqual(set(policy),game.keys)
            for row in policy.values():
                self.assertAlmostEqual(sum(row),1)
                self.assertTrue(all(0<=v<=1 for v in row))
            self.assertAlmostEqual(sum(game.measure(policy)['policy_payoffs']),0)

    def test_plus_meets_headsup_control_threshold_at_same_iteration_budget(self):
        game=RiverGame(BOARD,demo_ranges(2))
        classic=game.measure(game.train(200))
        improved=game.measure(game.train(200,method='cfr_plus'))
        self.assertLess(improved['max_unilateral_gain_pct_pot'],.1)
        self.assertLess(improved['nash_conv_chips'],classic['nash_conv_chips']/10)

    def test_plus_is_repeatable_and_handles_joint_card_collisions(self):
        game=RiverGame(BOARD,[[('AhAd',1),('QhQd',.2)],[('AhAd',.5),('KhKd',1)]])
        first=game.train(30,method='cfr_plus')
        second=game.train(30,method='cfr_plus')
        self.assertEqual(first,second)
        self.assertAlmostEqual(sum(game.measure(first)['policy_payoffs']),0)
        for bad in (0,True,2001,1.5):
            with self.assertRaises(ValueError):game.train(bad,method='cfr_plus')
        with self.assertRaises(ValueError):game.train(20,method='unknown')


class RiverSizingTests(unittest.TestCase):
    def game(self,n=3,**kwargs):
        return RiverGame(BOARD,[r[:1] for r in demo_ranges(n)],pot=120,
                         bet_sizes=(25,50),raise_sizes=(50,100),max_raises=2,min_bet=10,**kwargs)

    def path(self,game,*actions):
        node=game.root
        for action in actions:node=node.children[node.actions.index(action)]
        return node

    def test_multiple_sizes_reopen_action_for_previous_callers_and_checkers(self):
        game=self.game()
        self.assertEqual(game.root.actions,('CHECK','BET 25','BET 50'))
        node=self.path(game,'CHECK','BET 25','CALL','RAISE 50')
        self.assertEqual(node.actor,1)
        self.assertEqual(node.actions,('FOLD','CALL','RAISE 100'))
        node=self.path(game,'CHECK','BET 25','CALL','RAISE 50','CALL')
        self.assertEqual(node.actor,2) # caller of the first bet must respond again
        self.assertIn('RAISE 100',node.actions)

    def test_minimum_increment_short_allin_and_raise_cap(self):
        game=RiverGame(BOARD,demo_ranges(2),stack=90,bet_sizes=(40,),
                       raise_sizes=(60,80,90),max_raises=2,min_bet=10)
        node=self.path(game,'BET 40')
        self.assertEqual(node.actions,('FOLD','CALL','RAISE 80','RAISE 90'))
        self.assertEqual(self.path(game,'BET 40','RAISE 80').actions,('FOLD','CALL','RAISE 90'))
        self.assertEqual(self.path(game,'BET 40','RAISE 80','RAISE 90').actions,('FOLD','CALL'))
        capped=RiverGame(BOARD,demo_ranges(2),bet_sizes=(25,),raise_sizes=(50,100),max_raises=1)
        self.assertEqual(self.path(capped,'BET 25','RAISE 50').actions,('FOLD','CALL'))
        three=RiverGame(BOARD,demo_ranges(2),bet_sizes=(10,),raise_sizes=(20,40,80),max_raises=3)
        self.assertEqual(self.path(three,'BET 10','RAISE 20','RAISE 40','RAISE 80').actions,('FOLD','CALL'))

    def test_every_expanded_branch_matches_production_betting_and_payoffs(self):
        from app.models.poker import ActionType,HandState,Player,Street
        from app.services.poker_engine import PokerEngine
        from research.river_reference import cards
        engine=PokerEngine()
        # Exhaustive paths for 2–4 players, including folds after a raise/all-in.
        games=[self.game(n) for n in (2,3,4)]
        games.append(RiverGame(BOARD,[r[:1] for r in demo_ranges(3)],pot=120,stack=90,
                               bet_sizes=(40,),raise_sizes=(60,80,90),max_raises=2,min_bet=10))
        for game in games:
            n=game.n;stack=game.stack
            state=HandState(hand_id='research',street=Street.RIVER,pot=120,
                            small_blind=5,big_blind=10,board=cards(''.join(BOARD)),
                            players=[Player(id=str(i),name=str(i),stack=stack,position='',
                                            cards=cards(game.ranges[i][0][0])) for i in range(n)],
                            current_player_id='0',dealer_player_id=str(n-1),last_full_raise=10,
                            contributions={str(i):120//n for i in range(n)})
            def visit(node,state):
                if node.actor==-1:
                    if state.result is None:engine.advance(state)
                    self.assertIsNotNone(state.result)
                    for i,player in enumerate(state.players):
                        self.assertAlmostEqual(player.stack-stack-120/n,game.utilities[(id(node),0)][i])
                    return
                self.assertEqual(state.current_player_id,str(node.actor))
                for action,child in zip(node.actions,node.children):
                    parts=action.split();next_state=state.model_copy(deep=True)
                    engine.apply_action(next_state,str(node.actor),ActionType(parts[0].lower()),
                                        int(parts[1]) if len(parts)>1 else None)
                    visit(child,next_state)
            visit(game.root,state)

    def test_arbitrary_action_counts_train_and_measure_for_two_to_six_players(self):
        for n in range(2,7):
            game=RiverGame(BOARD,[r[:1] for r in demo_ranges(n)],bet_sizes=(25,50),
                           raise_sizes=(100,),max_raises=1,min_bet=10)
            for method in ('cfr','cfr_plus'):
                policy=game.train(2,method=method)
                self.assertTrue(all(len(row)==game.action_counts[k] for k,row in policy.items()))
                self.assertAlmostEqual(sum(game.measure(policy)['policy_payoffs']),0)
            invalid={k:[.5,.5] for k in game.keys}
            with self.assertRaises(ValueError):game.measure(invalid)

    def test_expanded_best_response_groups_hidden_hands_at_repeated_decisions(self):
        game=RiverGame(BOARD,[[('AhAd',1),('QhQd',1)],[('KhKd',1)]],
                       bet_sizes=(25,50),raise_sizes=(100,),max_raises=1)
        # OOP bets 25 with both hands. IP folds/calls equally, never raises.
        policy={}
        for k,m in game.action_counts.items():
            actions=next(node.actions for node in game.nodes if node.actor==k[0] and node.history==k[2])
            row=[0.]*m
            if k[0]==0:row[actions.index('BET 25') if not k[2] else 0]=1
            elif k[2]==((0,'BET 25'),):row[0]=row[1]=.5
            else:row[0]=1
            policy[k]=row
        result=game.measure(policy)
        # Raising wins vs both because OOP folds: IP can improve to +75,
        # but cannot condition its response on which of AA/QQ OOP holds.
        self.assertAlmostEqual(result['best_response_payoffs'][1],75)

    def test_explicit_limits_and_invalid_sizes(self):
        for kwargs in ({'bet_sizes':()}, {'bet_sizes':(True,)}, {'bet_sizes':(25,25)},
                       {'bet_sizes':(101,)}, {'min_bet':30,'bet_sizes':(25,)},
                       {'raise_sizes':(1.5,)}, {'max_raises':4}, {'max_raises':True},
                       {'max_nodes':5}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                RiverGame(BOARD,demo_ranges(2),**kwargs)
