import contextlib
import copy
import io
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from app.services.decision_engine import DecisionEngine
from research.custom_river import RiverGame
from research.river_snapshot import build_river_from_snapshot
from research.river_reference import cards
from research.benchmark_midriver_ranges import make_case
from research.compare_coach import (decision_state,root_action_values,subset_equity,compare_hand,worker,benchmark)


class CoachComparisonTests(unittest.TestCase):
    def game(self):
        return RiverGame(['2c','4d','7h','9s','Jc'],[[('AhAd',1)],[('KhKd',1),('AcAs',3)]],
            pot=100,stacks=(100,100),initial_contributions=(50,50),dealer=0,min_bet=10,
            river_actions=((1,'bet',40),),bet_sizes=(40,),max_raises=0)

    def test_conditional_equity_and_incremental_action_ev(self):
        game=self.game();policy=game.train(3,method='cfr_plus_indexed')
        self.assertEqual(game.root.actions,('FOLD','CALL'))
        equity,count=subset_equity(game,'AhAd')
        self.assertAlmostEqual(equity,.625);self.assertEqual(count,2)
        values,mass=root_action_values(game,policy,'AhAd',best_response=True)
        self.assertEqual(mass,1);self.assertEqual(values,[0,72.5])
        analyses={'test':NS(recommended_action='fold',equity=.625,required_equity=.1,equity_method='fixture')}
        row=compare_hand(game,policy,'AhAd',analyses)
        self.assertEqual(row['coach']['test']['one_decision_loss_chips'],72.5)
        self.assertEqual(row['best_response_continuation_actions'],['CALL'])
        with self.assertRaises(ValueError):root_action_values(game,policy,'QhQd')

    def test_unrepresented_size_is_explicit_and_never_snapped(self):
        game=self.game();policy=game.train(2,method='cfr_plus_indexed')
        analysis=NS(recommended_action='raise',recommended_amount=81,equity=.8,required_equity=.1,equity_method='fixture')
        row=compare_hand(game,policy,'AhAd',{'test':analysis})['coach']['test']
        self.assertEqual(row['action'],'RAISE 81')
        self.assertFalse(row['represented_exactly'])
        self.assertIsNone(row['action_ev_chips']);self.assertIsNone(row['one_decision_loss_chips'])

    def test_best_response_chooses_after_aggregation_not_hidden_deal(self):
        a=NS(actor=-1);b=NS(actor=-1)
        future=NS(actor=0,children=(a,b));root=NS(actor=0,children=(future,))
        g=NS(root=root,root_state=NS(invested=(0,0)),initial_contributions=(0,0),
             deals=[(('AhAd','KhKd'),.5,None),(('AhAd','QhQd'),.5,None)],
             utilities={(id(a),0):(10,-10),(id(a),1):(-10,10),
                        (id(b),0):(-10,10),(id(b),1):(10,-10)},key=lambda n,d:'future')
        values,_=root_action_values(g,{'future':[.5,.5]},'AhAd',best_response=True)
        self.assertEqual(values,[0]) # clairvoyant per-deal choice would incorrectly yield 10

    def test_public_reconstruction_only_adds_own_probe_cards(self):
        case=make_case('fixture',3,[2]*3,10)
        game,_=build_river_from_snapshot(case['snapshot'],case['selected_hands'],**case['input'])
        hand=next(d[0][game.root.actor] for d in game.deals)
        state=decision_state(case['snapshot'],game,hand)
        actor=case['snapshot']['actor_id']
        self.assertEqual(sum(len(p.cards) for p in state.players),2)
        self.assertTrue(all(not p.cards for p in state.players if p.id!=actor))
        self.assertEqual(state._deck,[])
        first=DecisionEngine().analyze(state,actor)
        for p in state.players:
            if p.id!=actor:p.cards=cards('AsKs')
        state._deck=cards('QsJsTs');state.notes=['secret']
        second=DecisionEngine().analyze(state,actor)
        self.assertEqual(first.recommended_action,second.recommended_action)
        self.assertEqual(first.equity,second.equity)

    def test_worker_represents_real_coach_size_and_both_arms(self):
        case=make_case('fixture',2,[2]*2,11)
        with contextlib.redirect_stdout(io.StringIO()):result=worker(case,3,'cfr_plus_indexed')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(set(result['comparison_summary']),{'current_full_ranges','same_subset_rules'})
        for row in result['comparisons']:
            self.assertTrue(all(a['represented_exactly'] for a in row['coach'].values()))
            self.assertEqual(len(row['action_ev_chips']),len(row['actions']))
            self.assertTrue(all(a<=b+1e-8 for a,b in zip(row['fixed_policy_action_ev_chips'],row['action_ev_chips'])))
        self.assertAlmostEqual(sum(row['conditional_mass'] for row in result['comparisons']),1)
        bad=copy.deepcopy(case);bad['snapshot']['pot']+=1
        with contextlib.redirect_stdout(io.StringIO()):result=worker(bad,3,'cfr_plus_indexed')
        self.assertEqual(result['status'],'rejected');self.assertNotIn('comparisons',result)

    def test_unknown_or_duplicate_corpus_selection_is_rejected(self):
        for names in ([],['missing'],['dry_2','dry_2']):
            with patch('research.compare_coach.run_guarded') as runner:
                with self.assertRaises(ValueError):benchmark(names=names)
                runner.assert_not_called()
