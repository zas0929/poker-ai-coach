import copy
from itertools import combinations
import unittest
from research.wide_range_audit import audit_ranges
from research.exact_range_quotient import compress_ranges
from research.benchmark_expanded import make_case,run_guarded

BOARD=['2c','4d','7h','9s','Jc']


def partition(groups):
    return {frozenset(''.join(sorted((t[:2],t[2:]))) for t in g['members']):g['weight'] for g in groups}


class WideRangeAuditTests(unittest.TestCase):
    def test_compact_signatures_match_independent_exact_method_two_to_six_seats(self):
        for n in range(2,7):
            with self.subTest(seats=n):
                ranges=make_case('test',BOARD,[8]*n,20261024+n)['input']['ranges']
                compact=audit_ranges(BOARD,ranges);reference=compress_ranges(BOARD,ranges)
                self.assertEqual(compact['compressed_widths'],reference['compressed_widths'])
                for a,b in zip(compact['groups'],reference['groups']):self.assertEqual(partition(a),partition(b))

    def test_entire_public_support_cannot_merge_even_using_only_blockers(self):
        deck=[r+s for r in '23456789TJQKA' for s in 'cdhs' if r+s not in BOARD]
        full=[(''.join(pair),1.) for pair in combinations(deck,2)]
        result=audit_ranges(BOARD,[full,full])
        self.assertEqual(result['original_widths'],[1081,1081])
        self.assertEqual(result['blocker_only_widths'],[1081,1081])
        self.assertEqual(result['compressed_widths'],[1081,1081])
        self.assertEqual(result['logical_pair_checks'],2*1081**2)
        self.assertEqual(result['evaluated_pair_relations'],1081**2)
        self.assertEqual(result['unique_relation_tables'],1)
        self.assertFalse(result['within_raw_solver_budget'])
        self.assertFalse(result['live_advice_allowed']);self.assertFalse(result['solver_quality_verified'])

    def test_equivalent_hands_keep_mass_and_folded_seats_without_reading_weights_as_legality(self):
        ranges=[[('AhAd',1.),('AcAs',3.)],[('KhKd',2.),('KcKs',5.)],[]]
        result=audit_ranges(BOARD,ranges,folded=[2])
        self.assertEqual(result['compressed_widths'],[1,1,0])
        self.assertEqual([g[0]['weight'] for g in result['groups'][:2]],[4.,7.])
        changed=copy.deepcopy(ranges);changed[0][0]=('AhAd',100.)
        other=audit_ranges(BOARD,changed,folded=[2])
        self.assertEqual(other['compressed_widths'],result['compressed_widths'])
        self.assertNotEqual(other['groups_sha256'],result['groups_sha256'])

    def test_order_and_card_notation_do_not_change_groups(self):
        ranges=[[('AhAd',1.),('AcAs',3.)],[('KhKd',2.),('KcKs',5.)]]
        original=audit_ranges(BOARD,ranges)
        reordered=[[(t[2:]+t[:2],w) for t,w in reversed(rows)] for rows in ranges]
        self.assertEqual(original,audit_ranges(list(reversed(BOARD)),reordered))

    def test_no_silent_shrinking_or_acceptance_of_invalid_inputs(self):
        ranges=[[('AhAd',1.),('AcAs',3.)],[('KhKd',2.),('KcKs',5.)]]
        with self.assertRaisesRegex(ValueError,'budget'):audit_ranges(BOARD,ranges,max_pair_checks=1)
        for bad in (True,0,36000001):
            with self.assertRaises(ValueError):audit_ranges(BOARD,ranges,max_pair_checks=bad)
        for bad in ([ [('AhAd',0)],ranges[1] ],[ [('AhAd',1),('AdAh',2)],ranges[1] ],[ [('2cAd',1)],ranges[1] ]):
            with self.assertRaises(ValueError):audit_ranges(BOARD,bad)

    def test_real_guarded_worker_reports_audit_without_solver_quality(self):
        result=run_guarded({'board':BOARD,'ranges':[[('AhAd',1.)],[('KhKd',1.)]]},
                           1,10,128,worker_module='research.benchmark_wide_ranges')
        self.assertEqual(result['status'],'audited',result)
        self.assertTrue(result['within_raw_solver_budget'])
        self.assertFalse(result['solver_quality_verified'])
        self.assertNotIn('groups',result)
