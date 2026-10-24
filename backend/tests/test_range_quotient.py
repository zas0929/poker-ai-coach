import copy
import unittest
from research.custom_river import RiverGame
from research.exact_range_quotient import compress_ranges,lift_policy,verify_quotient
from research.benchmark_expanded import make_case

BOARD=['2c','4d','7h','9s','Jc']


def game(ranges,**kwargs):
    return RiverGame(BOARD,ranges,pot=100,stacks=[100]*len(ranges),bet_sizes=[20],raise_sizes=[],max_raises=0,max_joint_combos=4096,**kwargs)


class RangeQuotientTests(unittest.TestCase):
    def test_merge_keeps_exact_mass_and_lifted_best_response(self):
        ranges=[[('AhAd',1.),('AcAs',3.)],[('KhKd',2.),('KcKs',5.)]]
        q=compress_ranges(BOARD,ranges)
        self.assertEqual(q['compressed_widths'],[1,1])
        self.assertEqual([r[0][1] for r in q['ranges']],[4.,7.])
        full=game(ranges);reduced=game(q['ranges'])
        self.assertEqual(len(full.deals),4);self.assertEqual(len(reduced.deals),1)
        self.assertTrue(verify_quotient(full,reduced,q)['verified'])
        policy=reduced.train(30,method='cfr_plus_indexed')
        a=reduced.measure(policy);b=full.measure(lift_policy(full,policy,q))
        for key in ('policy_payoffs','best_response_payoffs','unilateral_gains'):
            for x,y in zip(a[key],b[key]):self.assertAlmostEqual(x,y,places=9)
        self.assertFalse(q['live_advice_allowed'])

    def test_same_strength_hands_with_different_blockers_cannot_merge(self):
        ranges=[[('AhAd',1.),('AcAs',1.)],[('AhKd',1.),('AcKs',3.)]]
        q=compress_ranges(BOARD,ranges)
        self.assertEqual(q['compressed_widths'],[2,2])
        full=game(ranges);reduced=game(q['ranges'])
        self.assertEqual(len(full.deals),2)
        self.assertTrue(verify_quotient(full,reduced,q)['verified'])

    def test_verifier_checks_illegal_lineups_even_when_normalized_mass_would_match(self):
        ranges=[[('AhAd',1.),('AcAs',1.)],[('AhKd',1.),('AcKs',1.)]]
        full=game(ranges)
        # This incorrect quotient keeps total weight and all legal showdown
        # outcomes, but hides the two blocked original lineups.
        small=game([[('AhAd',2.)],[('AcKs',2.)]])
        wrong={'mapping':[{'AhAd':'AhAd','AcAs':'AhAd'},{'AhKd':'AcKs','AcKs':'AcKs'}]}
        with self.assertRaisesRegex(ValueError,'compatibility'):
            verify_quotient(full,small,wrong)

    def test_same_category_different_showdown_relation_cannot_merge(self):
        ranges=[[('AhAd',1.),('QhQd',2.)],[('KhKd',1.)]]
        self.assertEqual(compress_ranges(BOARD,ranges)['compressed_widths'],[2,1])

    def test_ties_odd_chips_sidepots_and_folded_seats(self):
        board=['Ts','Js','Qs','Ks','As']
        ranges=[[('2c3d',1.),('2h3c',2.)],[('4c5d',3.),('4h5c',1.)],[('6c7d',1.)],[]]
        spec=dict(board=board,pot=19,stacks=[20,20,0,0],initial_contributions=[5,5,4,5],
                  dealer=3,folded=[3],bet_sizes=[3],raise_sizes=[],max_raises=0,max_joint_combos=4096)
        q=compress_ranges(board,ranges,folded=[3]);self.assertEqual(q['compressed_widths'],[1,1,1,0])
        full=RiverGame(ranges=ranges,**spec);small=RiverGame(ranges=q['ranges'],**spec)
        self.assertEqual(verify_quotient(full,small,q)['max_utility_error_chips'],0.)
        policy=small.train(20,method='cfr_plus_indexed')
        a=small.measure(policy);b=full.measure(lift_policy(full,policy,q))
        for x,y in zip(a['best_response_payoffs'],b['best_response_payoffs']):self.assertAlmostEqual(x,y)

    def test_seeded_ranges_two_to_six_seats_preserve_all_terminal_utilities(self):
        for n in range(2,7):
            with self.subTest(seats=n):
                spec=make_case('test',BOARD,[2]*n,100+n)['input']
                spec.update(raise_sizes=[],max_raises=0)
                q=compress_ranges(BOARD,spec['ranges']);full=RiverGame(**spec)
                reduced=RiverGame(**{**spec,'ranges':q['ranges']})
                self.assertTrue(verify_quotient(full,reduced,q)['verified'])

    def test_fail_closed_on_budget_bad_inputs_or_wrong_tree(self):
        ranges=[[('AhAd',1.),('AcAs',3.)],[('KhKd',2.),('KcKs',5.)]]
        with self.assertRaisesRegex(ValueError,'Pair budget'):compress_ranges(BOARD,ranges,max_pair_checks=1)
        for bad in ([ [('AhAd',0)],ranges[1] ],[ [('AhAd',1),('AdAh',2)],ranges[1] ],[ [('2cAd',1)],ranges[1] ]):
            with self.assertRaises(ValueError):compress_ranges(BOARD,bad)
        q=compress_ranges(BOARD,ranges);full=game(ranges);small=game(q['ranges'])
        with self.assertRaisesRegex(ValueError,'budget'):verify_quotient(full,small,q,max_terminal_checks=1)
        with self.assertRaisesRegex(ValueError,'trees'):
            verify_quotient(full,RiverGame(BOARD,q['ranges'],bet_sizes=[40]),q)
        broken=copy.deepcopy(q);broken['mapping'][0]['AhAd']='2h3h'
        with self.assertRaisesRegex(ValueError,'illegal'):verify_quotient(full,small,broken)
