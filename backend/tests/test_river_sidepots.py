import unittest
from research.custom_river import RiverGame,demo_ranges
from research.sidepot_reference import compare_every_path

BOARD=['2c','4d','7h','9s','Jc']


def follow(game,*actions):
    node=game.root
    for action in actions:node=node.children[node.actions.index(action)]
    return node




class RiverSidePotTests(unittest.TestCase):
    def game(self,stacks,**kwargs):
        n=len(stacks)
        return RiverGame(BOARD,[r[:1] for r in demo_ranges(n)],pot=60*n,stacks=stacks,
                         initial_contributions=[60]*n,bet_sizes=(40,),raise_sizes=(80,100),
                         max_raises=2,min_bet=10,**kwargs)

    def test_short_stack_wins_main_and_middle_stack_wins_side(self):
        game=self.game((30,60,100))
        node=follow(game,'CHECK','BET 40','RAISE 80','CALL','CALL')
        awards,refunds,pots=game.settle(node,game.deals[0][2])
        self.assertEqual(refunds,(0,0,20))
        self.assertEqual([p['amount'] for p in pots],[270,60])
        self.assertEqual([p['winners'] for p in pots],[[0],[1]])
        self.assertEqual(awards,(270,60,20))
        self.assertEqual(game.utilities[(id(node),0)],(180,-60,-120))

    def test_single_short_raise_does_not_reopen_previous_actor(self):
        game=self.game((100,45,100))
        node=follow(game,'BET 40','RAISE 45','CALL')
        self.assertEqual(node.actor,0)
        self.assertEqual(node.actions,('FOLD','CALL'))
        # The unacted third player can still make a full raise to 100.
        self.assertIn('RAISE 100',follow(game,'BET 40','RAISE 45').actions)

    def test_cumulative_short_raises_can_reopen_action(self):
        game=self.game((200,60,80,200))
        node=follow(game,'BET 40','RAISE 60','RAISE 80','CALL')
        # Two short raises together increase the bet by a full 40.
        self.assertEqual(node.actor,0)
        # This test uses a cap of 2 raises, so repeat with a third permitted.
        game=RiverGame(BOARD,[r[:1] for r in demo_ranges(4)],stacks=(200,60,80,200),
                       bet_sizes=(40,),raise_sizes=(60,80,120),max_raises=3,min_bet=10)
        self.assertIn('RAISE 120',follow(game,'BET 40','RAISE 60','RAISE 80','CALL').actions)

    def test_short_opening_allin_and_no_dry_side_pot_bet(self):
        game=self.game((5,100,0))
        self.assertEqual(game.root.actions,('CHECK','BET 5'))
        self.assertEqual(follow(game,'BET 5').actions,('FOLD','CALL'))
        self.assertEqual(follow(game,'BET 5','CALL').actor,-1)

    def test_every_path_matches_engine_for_two_to_six_seats(self):
        for n in range(2,7):
            # Small explicit tree; no truncation of paths.
            game=RiverGame(BOARD,[r[:1] for r in demo_ranges(n)],pot=60*n,
                           stacks=tuple([15,30,50,70,90,110][:n]),initial_contributions=[60]*n,
                           bet_sizes=(min(40,[15,30,50,70,90,110][n-1]),),
                           raise_sizes=(min(80,[15,30,50,70,90,110][n-1]),),max_raises=1,min_bet=10)
            with self.subTest(n=n):self.assertGreater(compare_every_path(game)['terminal_deal_checks'],0)

    def test_engine_comparison_for_short_reopening_and_prior_side_pots(self):
        games=[self.game((100,45,100)),self.game((30,60,100)),self.game((5,100,0))]
        games.append(RiverGame(BOARD,demo_ranges(3),pot=150,stacks=(0,100,100),
                               initial_contributions=(30,60,60),bet_sizes=(40,),
                               raise_sizes=(80,),max_raises=1,min_bet=10))
        games.append(RiverGame(BOARD,[r[:1] for r in demo_ranges(4)],pot=240,
                               stacks=(200,60,80,200),initial_contributions=(60,)*4,
                               bet_sizes=(40,),raise_sizes=(60,80,120),max_raises=3,min_bet=10))
        for game in games:self.assertGreater(compare_every_path(game)['terminal_deal_checks'],0)

    def test_odd_chip_and_allin_from_prior_streets(self):
        # Board plays, 3-chip main + 2-chip side. Dealer seat 1: odd chip to seat 2.
        game=RiverGame(['As','Ks','Qs','Js','Ts'],[[('2h2d',1)],[('3h3d',1)],[('4h4d',1)]],
                       pot=5,stacks=(0,0,0),initial_contributions=(2,1,2),dealer=1,bet_sizes=(1,))
        awards,refunds,pots=game.settle(game.root,game.deals[0][2])
        self.assertEqual(awards,(2,1,2))
        self.assertEqual(refunds,(0,0,0))
        compare_every_path(game)
        self.assertEqual(sum(game.measure({})['policy_payoffs']),0)
        self.assertEqual(game.train(2,method='cfr_plus'),{})
        # Unequal split with two winners, one loser supplying odd dead money.
        game=RiverGame(BOARD,[[('AhAd',1)],[('3h3d',1)],[('AcAs',1)]],
                       pot=3,stacks=(0,0,0),initial_contributions=(1,1,1),dealer=0,bet_sizes=(1,))
        awards,_,_=game.settle(game.root,game.deals[0][2])
        self.assertEqual(awards,(1,0,2))
        compare_every_path(game)

    def test_training_validity_with_unequal_stacks(self):
        game=RiverGame(BOARD,demo_ranges(3),pot=180,stacks=(30,60,100),
                       initial_contributions=(60,)*3,bet_sizes=(40,),raise_sizes=(80,),max_raises=1)
        uniform=game.measure({k:[1/m]*m for k,m in game.action_counts.items()})
        for method in ('cfr','cfr_plus'):
            trained=game.measure(game.train(30,method=method))
            self.assertAlmostEqual(sum(trained['policy_payoffs']),0)
            self.assertLess(trained['nash_conv_chips'],uniform['nash_conv_chips'])

    def test_invalid_stacks_and_incomplete_prior_streets(self):
        for kwargs in ({'stacks':(1,)},{'stacks':(True,100)},{'stacks':(-1,100)},
                       {'stacks':(10.5,100)},{'initial_contributions':(20,30)},
                       {'initial_contributions':(-1,101)},{'initial_contributions':(True,99)},
                       {'initial_contributions':(30,70),'stacks':(100,100)}, {'dealer':2}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                RiverGame(BOARD,demo_ranges(2),**kwargs)
