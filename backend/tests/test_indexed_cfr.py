import unittest
from research.custom_river import RiverGame,demo_ranges
from research.benchmark_capacity import scenarios

BOARD=['2c','4d','7h','9s','Jc']


class IndexedCfrTests(unittest.TestCase):
    def assert_equivalent(self,game,iterations):
        reference=game.train(iterations,method='cfr_plus')
        indexed=game.train(iterations,method='cfr_plus_indexed')
        self.assertEqual(set(reference),set(indexed))
        for key,row in reference.items():
            for a,value in enumerate(row):self.assertAlmostEqual(value,indexed[key][a],places=12)
        left=game.measure(reference);right=game.measure(indexed)
        for metric in ('policy_payoffs','best_response_payoffs','unilateral_gains'):
            for a,b in zip(left[metric],right[metric]):self.assertAlmostEqual(a,b,places=10)
        self.assertAlmostEqual(left['nash_conv_chips'],right['nash_conv_chips'],places=10)
        return indexed

    def test_two_to_six_seats_with_multiple_actions_and_repeated_decisions(self):
        for n in range(2,7):
            ranges=demo_ranges(n) if n<=3 else [r[:1] for r in demo_ranges(n)]
            game=RiverGame(BOARD,ranges,bet_sizes=(25,50),raise_sizes=(50,100),max_raises=1)
            self.assert_equivalent(game,4)

    def test_weighted_colliding_ranges_never_split_public_information_sets(self):
        game=RiverGame(BOARD,[[('AhAd',1),('QhQd',.2)],[('AhAd',.5),('KhKd',1)]],
                       bet_sizes=(25,50),raise_sizes=(100,),max_raises=1)
        self.assert_equivalent(game,80)

    def test_sidepots_short_raises_and_folded_seats(self):
        games=[RiverGame(BOARD,demo_ranges(3),pot=180,stacks=(30,60,100),initial_contributions=(60,)*3,
                         bet_sizes=(40,),raise_sizes=(80,),max_raises=1),
               RiverGame(BOARD,[[],*demo_ranges(2)],pot=150,stacks=(500,45,100),
                         initial_contributions=(30,60,60),folded=(0,),dealer=0,
                         bet_sizes=(40,),raise_sizes=(80,100),max_raises=2)]
        games.append(RiverGame(BOARD,[r[:1] for r in demo_ranges(4)],pot=240,
                               stacks=(200,60,80,200),initial_contributions=(60,)*4,
                               bet_sizes=(40,),raise_sizes=(60,80,120),max_raises=3,min_bet=10))
        for game in games:self.assert_equivalent(game,20)

    def test_allin_terminal_and_deterministic_repeated_training(self):
        game=RiverGame(BOARD,demo_ranges(2),pot=100,stacks=(0,0),initial_contributions=(50,50))
        self.assertEqual(self.assert_equivalent(game,3),{})
        game=RiverGame(BOARD,demo_ranges(2))
        self.assertEqual(game.train(10,method='cfr_plus_indexed'),game.train(10,method='cfr_plus_indexed'))
        for bad in (0,True,1.5,2001):
            with self.assertRaises(ValueError):game.train(bad,method='cfr_plus_indexed')

    def test_wider_reference_scenarios_at_short_budget(self):
        for case in list(scenarios())[:4]:
            self.assert_equivalent(RiverGame(**case['input']),3)


class IndexedBenchmarkTests(unittest.TestCase):
    def result(self):
        return {'status':'completed','policy':[[[0,'AhAd',[]],[.25,.75]]],
                'metrics':{'policy_payoffs':[1,-1],'best_response_payoffs':[2,0],
                           'unilateral_gains':[1,1]},'train_seconds':1,'wall_seconds':2}

    def test_comparison_requires_same_information_sets_and_probabilities(self):
        from research.benchmark_indexed import compare
        left=self.result();right=self.result()
        self.assertTrue(compare(left,right)['equivalent'])
        right['policy'][0][1]=[.3,.7]
        self.assertFalse(compare(left,right)['equivalent'])
        right=self.result();right['policy'][0][0][1]='KhKd'
        self.assertFalse(compare(left,right)['equivalent'])
        right=self.result();right['metrics']['best_response_payoffs'][0]+=1
        self.assertFalse(compare(left,right)['equivalent'])
        self.assertFalse(compare(left,{'status':'timed_out'})['equivalent'])
