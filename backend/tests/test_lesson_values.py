import copy
import json
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch

from research import lesson_values as subject
from research.analysis_contract import ResearchLimits
from research.custom_river import RiverGame


def game(own='AhAd', other='KhKd', **kwargs):
    return RiverGame(['2c','4d','7h','9s','Jc'], [[(own,1)],[(other,1)]], pot=20,
                     stacks=[100,100], initial_contributions=[10,10], dealer=1,
                     bet_sizes=[10], min_bet=10, utility_storage='compact', **kwargs)


def strategy(g, select):
    policy = {}
    for node in g.nodes:
        if node.actor == -1:
            continue
        for texts, _, _ in g.deals:
            key = (node.actor, texts[node.actor], node.history)
            chosen = select(node, texts[node.actor])
            policy[key] = [float(action == chosen) for action in node.actions]
    return policy


class LessonValueTests(unittest.TestCase):
    def test_win_loss_fold_uncalled_refund_and_mixed_opponent(self):
        for own, other, called in [('AhAd','KhKd',30.),('KhKd','AhAd',-10.)]:
            g = game(own, other)
            p = strategy(g, lambda n, h: 'CHECK' if 'CHECK' in n.actions else 'CALL')
            self.assertEqual(subject.action_values(g,p,own)['ev_chips'], [20. if called > 0 else 0., called])
            # Betting then everyone folding returns the uncalled bet: gain is pot, not pot+bet.
            p = strategy(g, lambda n, h: 'CHECK' if 'CHECK' in n.actions else 'FOLD')
            self.assertEqual(subject.action_values(g,p,own)['ev_chips'][1],20.)
            response = g.root.children[1]
            p[(response.actor,other,response.history)] = [.75,.25]
            self.assertAlmostEqual(subject.action_values(g,p,own)['ev_chips'][1], .75*20+.25*called)

    def test_fixed_continuation_does_not_choose_best_future_action(self):
        g = game()
        p = strategy(g, lambda n,h: 'BET 10' if n.actor == 1 and 'BET 10' in n.actions else
                     'FOLD' if 'FOLD' in n.actions else 'CHECK')
        # Hero has the winning hand, but the fixed continuation folds to the bet.
        self.assertEqual(subject.action_values(g,p,'AhAd')['ev_chips'], [0.,20.])

    def test_tie_and_side_pot_accounting(self):
        g = RiverGame(['Tc','Jd','Qh','Ks','Ac'], [[('2d3h',1)],[('4s5d',1)]], pot=20,
                      stacks=[100,100],initial_contributions=[10,10],dealer=1,bet_sizes=[10],min_bet=10)
        p = strategy(g, lambda n,h:'CHECK' if 'CHECK' in n.actions else 'CALL')
        self.assertEqual(subject.action_values(g,p,'2d3h')['ev_chips'],[10.,10.])
        g = RiverGame(['2c','4d','7h','9s','Jc'], [[('AhAd',1)],[('KhKd',1)],[('QhQd',1)]], pot=25,
                      stacks=[10,20,0],initial_contributions=[10,10,5],dealer=2,bet_sizes=[10],min_bet=10)
        p = strategy(g, lambda n,h:'CHECK' if 'CHECK' in n.actions else 'CALL')
        self.assertEqual(subject.action_values(g,p,'AhAd')['ev_chips'],[25.,35.])

    def test_existing_street_investment_is_sunk_not_paid_twice(self):
        g = game(raise_sizes=[20],max_raises=1,river_actions=[(0,'bet',10),(1,'raise',20)])
        p = strategy(g, lambda n,h:'CALL' if 'CALL' in n.actions else 'CHECK')
        values = subject.action_values(g,p,'AhAd')
        self.assertEqual(values['sunk_chips'],20)
        self.assertEqual(dict(zip(values['actions'],values['ev_chips']))['FOLD'],0.)
        self.assertEqual(dict(zip(values['actions'],values['ev_chips']))['CALL'],50.)

    def test_joint_weights_condition_on_own_cards_and_exclude_collisions(self):
        g = RiverGame(['2c','4d','7h','9s','Jc'], [[('AhAd',1),('QhQd',50)],
                      [('KhKd',3),('JhJd',1),('AhAs',100)]],pot=20,stacks=[100,100],
                      initial_contributions=[10,10],dealer=1,bet_sizes=[10],min_bet=10)
        p = strategy(g,lambda n,h:'CHECK' if 'CHECK' in n.actions else 'CALL')
        v = subject.action_values(g,p,'AhAd')
        # Opponent KhKd has 3/4 mass, JhJd has 1/4; AhAs is blocked by our hand.
        self.assertAlmostEqual(v['ev_chips'][0],15.)
        self.assertAlmostEqual(v['ev_chips'][1],20.)
        self.assertEqual(v['compatible_deals'],2)
        with self.assertRaises(ValueError):subject.action_values(g,p,'8h8d')

    def test_admission_requires_finite_matching_ev_and_quality(self):
        from research.river_snapshot import build_river_from_snapshot
        original = json.loads((Path(__file__).parents[1]/'research/fixtures/river-lessons-v1.json').read_text())['examples'][0]['request']
        actual, metadata = build_river_from_snapshot(original['snapshot'],original['selected_hands'],**original['input'])
        policy = {k:[1/actual.action_counts[k]]*actual.action_counts[k] for k in actual.keys}
        metrics={'policy_payoffs':[0.]*actual.n,'best_response_payoffs':[0.]*actual.n,
                 'unilateral_gains':[0.]*actual.n,'max_unilateral_gain_pct_pot':0.,'nash_conv_chips':0.}
        with patch.object(subject,'build_river_from_snapshot',return_value=(actual,metadata)), \
             patch.object(actual,'train',return_value=policy) as train,patch.object(actual,'measure',return_value=metrics):
            raw=subject.worker(original,300)
        train.assert_called_once_with(300,method='cfr_plus_native')
        raw.update(wall_seconds=.1,sampled_peak_rss_mib=20.,peak_rss_mib=20.)
        def run(row):
            with patch.object(subject,'run_guarded',return_value=row):return subject.analyze(original,ResearchLimits(iterations=300))
        accepted=run(raw)
        self.assertEqual(accepted['status'],'ready')
        self.assertIn('action_values',accepted)
        for mutate in (
            lambda r:r['action_values']['ev_chips'].__setitem__(0,float('nan')),
            lambda r:r['action_values']['gap_to_best_chips'].__setitem__(0,999),
            lambda r:r['action_values'].update(own_hand='8h8d'),
            lambda r:r['action_values'].update(continuation='best_response'),
            lambda r:r['action_values'].update(policy_ev_chips=999),
            lambda r:r['value_provenance'].update(source_sha256='0'*64),
            lambda r:r.update(request_key='0'*64),
            lambda r:r.update(wall_seconds=11),
            lambda r:r.update(sampled_peak_rss_mib=200),
        ):
            altered=copy.deepcopy(raw);mutate(altered);refused=run(altered)
            self.assertNotEqual(refused['status'],'ready');self.assertIsNone(refused['candidate'])
            self.assertNotIn('action_values',refused)
        altered=copy.deepcopy(raw)
        altered['metrics'].update(best_response_payoffs=[1.]*actual.n,unilateral_gains=[1.]*actual.n,
                                  nash_conv_chips=float(actual.n),max_unilateral_gain_pct_pot=100/original['snapshot']['pot'])
        self.assertEqual(run(altered)['status'],'quality_rejected')
        cancelled=Event();cancelled.set()
        with patch.object(subject,'run_guarded',return_value=raw):
            self.assertEqual(subject.analyze(original,cancel_event=cancelled)['status'],'cancelled')
