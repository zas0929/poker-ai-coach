import copy
import unittest
from research.benchmark_range_sensitivity import summarize
from research.trainer_ranges import select_ranges, cards
from research.river_snapshot import combo_key
from app.services.hand_evaluator import HandEvaluator
from app.services.trainer_solver import public_copy
from backend.tests.test_turn_snapshot import turn
from research.trainer_current import prepare
from research import turn_analysis


class TrainerRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assessment, cls.request = prepare(public_copy(turn(2)))

    def test_strata_cover_strength_quantiles_and_keep_original_weights(self):
        request = self.request
        snapshot, own = request['snapshot'], request['own_hand']
        chosen, players, coverage, model = select_ranges(snapshot, own)
        self.assertEqual(model['raw_joint_combos'], 64)
        self.assertEqual([r['selected_combos'] for r in coverage], [8, 8])
        evaluator = HandEvaluator(); board = cards(''.join(snapshot['board']))
        for p in snapshot['players']:
            rows = sorted(p['range'], key=lambda r: (evaluator.score([*cards(r['cards']), *board]), combo_key(r['cards'])))
            for i, hand in enumerate(chosen[p['id']]):
                group = rows[i*len(rows)//8:(i+1)*len(rows)//8]
                self.assertIn(hand, [r['cards'] for r in group])
            view = next(v for v in players if v['id'] == p['id'])
            self.assertEqual(view['range'], [next(r for r in rows if r['cards'] == h) for h in chosen[p['id']]])
        self.assertFalse(model['reliable_advice'])
        self.assertEqual(model['stability'], 'not_checked')

    def test_reproducible_samples_change_but_opponents_never_read_own_probe(self):
        snapshot, own = self.request['snapshot'], self.request['own_hand']
        first = select_ranges(snapshot, own)
        self.assertEqual(first, select_ranges(snapshot, own))
        self.assertNotEqual(first[0], select_ranges(snapshot, own, trial=1)[0])
        actor = snapshot['actor_id']; opposite = next(p for p in snapshot['players'] if p['id'] != actor)['id']
        other = next(p for p in snapshot['players'] if p['id'] == actor)['range'][-1]['cards']
        altered = select_ranges(snapshot, other)
        self.assertEqual(first[0][opposite], altered[0][opposite])
        self.assertIn(other, altered[0][actor])

    def test_expanded_subsets_are_bounded_before_dispatch(self):
        for n in range(2, 7):
            assessment, request = prepare(public_copy(turn(n)))
            self.assertIsNotNone(request, assessment)
            turn_analysis.validate_request(request)
            self.assertLessEqual(assessment['model']['sampling']['raw_joint_combos'], 64)
        for width in (0, 9, True):
            with self.assertRaises(ValueError):
                select_ranges(self.request['snapshot'], self.request['own_hand'], width=width)
        bad = copy.deepcopy(self.request)
        bad['selected_hands']['hero'].append('AsKs')
        with self.assertRaises(ValueError): turn_analysis.validate_request(bad)

    def test_disagreement_or_missing_run_cannot_be_called_stable(self):
        def row(best, status='ready'):
            return {'status': status, 'action_values': {'actions': ['FOLD', 'CALL'], 'ev_chips': [0, best]}}
        sensitive = summarize([row(1), row(-1), row(2)])
        self.assertEqual(sensitive['status'], 'sensitive')
        self.assertEqual(sensitive['ev_spans']['CALL']['spread'], 3)
        self.assertFalse(sensitive['reliable_advice'])
        refused = summarize([row(1), row(-1), row(0, 'budget_exceeded')])
        self.assertEqual(refused['status'], 'inconclusive')
        self.assertEqual(refused['common_best_actions'], [])
        agreed = summarize([row(1), row(2), row(3)])
        self.assertEqual(agreed['status'], 'agreement_observed')
        self.assertEqual(agreed['common_best_actions'], ['CALL'])
        self.assertFalse(agreed['reliable_advice'])
