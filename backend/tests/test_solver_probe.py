"""The offline adapter must reject inputs before starting any external solver."""
import copy
import unittest
from research.solver_probe import commands, fixtures, summarize, validate, verify_control

class SolverProbeTests(unittest.TestCase):
    def test_fixtures_are_valid_and_only_river_is_requested(self):
        for spec in fixtures():
            validate(spec)
            text=commands(spec,'result.json')
            self.assertIn('set_thread_num 1',text)
            self.assertIn('set_max_iteration 1000',text)
            self.assertNotIn(',flop,',text)
            self.assertNotIn(',turn,',text)

    def test_invalid_board_range_and_amounts(self):
        good=fixtures()[0]
        bad=[]
        for board in (good['board'][:4],['2c']*5,['XX',*good['board'][1:]]):
            spec=copy.deepcopy(good);spec['board']=board;bad.append(spec)
        for ranges in ([('AhAh',1)],[('2cAh',1)],[('AhAd',float('nan'))],[('AhAd',float('inf'))],[('AhAd',-1)],[('AhAd',0)],[('AhAd',2)],[('AhAd',1),('AdAh',1)],[('AhAd\nstart_solve',1)],[]):
            spec=copy.deepcopy(good);spec['oop']=ranges;bad.append(spec)
        for amount in (0,-1,True,1.5,10001):
            spec=copy.deepcopy(good);spec['pot']=amount;bad.append(spec)
        spec=copy.deepcopy(good);spec['ip']=spec['oop'];bad.append(spec)
        for spec in bad:
            with self.subTest(spec=spec),self.assertRaises(ValueError):validate(spec)

    def test_exported_strategy_must_have_legal_probabilities_and_requested_size(self):
        tree={'node_type':'action_node','player':1,'actions':['CHECK','BET 50.000000'],'strategy':{'actions':['CHECK','BET 50.000000'],'strategy':{'AhAd':[.5,.5]}}}
        self.assertEqual(summarize(tree)['strategy_rows'],1)
        for probabilities in ([.4,.4],[-.1,1.1],[float('nan'),1],[1]):
            bad=copy.deepcopy(tree);bad['strategy']['strategy']['AhAd']=probabilities
            with self.subTest(probabilities=probabilities),self.assertRaises(ValueError):summarize(bad)
        bad=copy.deepcopy(tree);bad['actions']=['CHECK','BET 100.000000'];bad['strategy']['actions']=bad['actions']
        with self.assertRaises(ValueError):summarize(bad)

    def test_board_tie_accepts_equally_good_call_or_raise_but_rejects_fold(self):
        tree={'actions':['BET 50.000000'],'childrens':{'BET 50.000000':{'actions':['CALL','RAISE 100.000000','FOLD'],'strategy':{'strategy':{'3h3d':[0,1,0]}}}}}
        verify_control({'name':'board_tie'},tree)
        tree['childrens']['BET 50.000000']['strategy']['strategy']['3h3d']=[1,0,0]
        verify_control({'name':'board_tie'},tree)
        tree['childrens']['BET 50.000000']['strategy']['strategy']['3h3d']=[0,0,1]
        with self.assertRaises(ValueError):verify_control({'name':'board_tie'},tree)

    def test_best_response_cannot_condition_on_hidden_opponent_cards(self):
        from research.river_reference import check_solution
        spec=dict(name='no_peeking',board=['2c','4d','7h','9s','Jc'],pot=100,stack=100,ip=[('KhKd',1)],oop=[('AhAd',1),('QhQd',1)])
        response={'node_type':'action_node','player':0,'actions':['CALL','FOLD'],'strategy':{'actions':['CALL','FOLD'],'strategy':{'KhKd':[.5,.5]}}}
        tree={'node_type':'action_node','player':1,'actions':['BET 50.000000'],'strategy':{'actions':['BET 50.000000'],'strategy':{'AhAd':[1],'QhQd':[1]}},'childrens':{'BET 50.000000':response}}
        result=check_solution(spec,tree)
        self.assertEqual(result['strategy_payoff_ip_oop_chips'],[-25,25])
        self.assertEqual(result['independent_exploitability_percent_pot'],12.5)
