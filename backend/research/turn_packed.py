"""Factored storage and native bridge for the SAME exact turn/river game.

No dense node/outcome key matrix. Public histories stay distinct; every compatible
private deal and river remains present. Terminal rows reuse only identical public
contributions/alive sets and identical showdown order, including ties.
"""
from array import array
from collections.abc import Mapping
import ctypes as C
import math

from research.build_turn_kernel import load_library
from research.turn_reference import TERMINAL

VERSION = 'factored-turn-native-v1'
INT_FIELDS = 'p n d r k t root slots button edge_count'.split()
PTR_FIELDS = 'actor at child street mask prune paid base hands own river rank ranks term state_paid state_mask initial'.split()


class Input(C.Structure):
    _fields_ = [(name,C.c_int32) for name in INT_FIELDS] + [(name,C.POINTER(C.c_int32)) for name in PTR_FIELDS] + [('chance',C.POINTER(C.c_double)),('utility',C.POINTER(C.c_int32))]


def freeze(value):
    return tuple(freeze(v) for v in value) if isinstance(value,(list,tuple)) else value


class UtilityView(Mapping):
    def __init__(self,game):
        self.game=game;self.nodes={id(n):n for n in game.nodes if n.actor==TERMINAL}
    def __getitem__(self,key):
        node,deal=key;node=self.nodes[node]
        if type(deal) is not int or not 0<=deal<len(self.game.outcomes):raise KeyError(key)
        awards,_,_=self.game.settle(node,self.game.outcomes[deal][3])
        return tuple(awards[p]-node.invested[p]-self.game.initial_contributions[p] for p in range(self.game.n))
    def __iter__(self):
        for node in self.nodes:
            for d in range(len(self.game.outcomes)):yield node,d
    def __len__(self):return len(self.nodes)*len(self.game.outcomes)


class InfoView(Mapping):
    def __init__(self,game):
        self.game=game
        self.nodes={(n.actor,n.history):n for n in game.nodes if n.actor>=0}
        self.signals=[set() for _ in range(game.n)]
        for hands,river,_,_ in game.outcomes:
            for p,hand in enumerate(hands):self.signals[p].add((hand,river))
    def __iter__(self):
        for node in self.nodes.values():
            signals=self.signals[node.actor]
            if node.street=='turn':signals={(hand,None) for hand,_ in signals}
            for hand,river in sorted(signals):yield node.actor,hand,node.history,river
    def __getitem__(self,key):
        p,hand,history,river=key;node=self.nodes[(p,history)]
        if ((river is None and node.street!='turn') or
                (river is not None and (node.street!='river' or (hand,river) not in self.signals[p])) or
                not any(h==hand for h,_ in self.signals[p])):raise KeyError(key)
        return len(node.actions)
    def __len__(self):
        return sum(len({h for h,_ in self.signals[n.actor]}) if n.street=='turn' else len(self.signals[n.actor])
                   for n in self.nodes.values())


class Policy(Mapping):
    def __init__(self,game,data):
        self.game=game;self._data=data;self.metrics=None;self.roots={}
    @property
    def data(self):return memoryview(self._data).toreadonly()
    def __iter__(self):return iter(self.game.action_counts)
    def __len__(self):return len(self.game.action_counts)
    def __getitem__(self,key):
        count=self.game.action_counts[key]
        if count==1:return [1.]
        p,hand,history,river=key;layout=self.game.packed
        n=layout['node_index'][id(self.game.action_counts.nodes[(p,history)])]
        signal=0 if river is None else layout['rivers'].index(river)*layout['counts'][p]
        start=layout['arrays']['base'][n]+(signal+layout['hand_ids'][p][hand])*count
        return list(self._data[start:start+count])


def initialize(game,max_entries):
    if not game.integer_payouts:
        raise ValueError('Factored turn storage requires explicit integer contributions.')
    nodes=game.nodes;index={id(n):i for i,n in enumerate(nodes)}
    rivers=sorted({r for _,r,_,_ in game.outcomes})
    hand_ids=[{hand:i for i,(hand,_) in enumerate(game.ranges[p])} or {None:0} for p in range(game.n)]
    counts=[len(row) for row in hand_ids];rank_ids={};ranks=[];rank_index=[]
    for _,_,_,scores in game.outcomes:
        scores=freeze(scores);ordered=sorted(set(s for s in scores if s is not None))
        code=tuple(ordered.index(s) if s is not None else -1 for s in scores)
        if code not in rank_ids:rank_ids[code]=len(rank_ids);ranks.extend(code)
        rank_index.append(rank_ids[code])
    states={};state_paid=[];state_mask=[];terminal=[]
    for node in nodes:
        if node.actor!=TERMINAL:terminal.append(-1);continue
        key=node.invested,node.alive
        if key not in states:
            states[key]=len(states);state_paid.extend(node.invested);state_mask.append(sum(1<<p for p in node.alive))
        terminal.append(states[key])
    bases=[];slots=0
    for node in nodes:
        if node.actor<0 or len(node.actions)==1:bases.append(-1);continue
        bases.append(slots)
        slots+=len(node.actions)*counts[node.actor]*(len(rivers) if node.street=='river' else 1)
    payoff_cells=len(states)*len(rank_ids)*game.n
    if payoff_cells+slots>max_entries:
        raise ValueError('Factored storage budget exceeded; no model truncation.')
    arrays={
        'actor':array('i',(n.actor for n in nodes)),
        'at':array('i',[0]),'child':array('i'),
        'street':array('i',(int(n.street=='river') for n in nodes)),
        'mask':array('i',(sum(1<<p for p in n.alive) for n in nodes)),
        'prune':array('i',(sum(1<<p for p in range(game.n) if p not in n.alive
                              and n.invested[p]<=max(n.invested[q] for q in range(game.n) if q!=p)) for n in nodes)),
        'paid':array('i',(v for n in nodes for v in n.invested)),
        'base':array('i',bases),'hands':array('i',counts),
        'own':array('i',(hand_ids[p][h] for hands,_,_,_ in game.outcomes for p,h in enumerate(hands))),
        'river':array('i',(rivers.index(r) for _,r,_,_ in game.outcomes)),
        'rank':array('i',rank_index),'ranks':array('i',ranks),
        'term':array('i',terminal),'state_paid':array('i',state_paid),
        'state_mask':array('i',state_mask),'initial':array('i',game.initial_contributions)}
    for node in nodes:
        arrays['child'].extend(index[id(c)] for c in node.children)
        arrays['at'].append(len(arrays['child']))
    chance=array('d',(w for _,_,w,_ in game.outcomes))
    utility=array('i',[0])*payoff_cells
    dimensions=(game.n,len(nodes),len(game.outcomes),len(rivers),len(rank_ids),len(states),index[id(game.root)],slots,game.dealer,len(arrays['child']))
    pointers=[(C.c_int32*len(arrays[name])).from_buffer(arrays[name]) for name in PTR_FIELDS]
    doubles=[(C.c_double*len(chance)).from_buffer(chance),
             (C.c_int32*len(utility)).from_buffer(utility)]
    native=Input(*dimensions,*pointers,*doubles)
    game.packed={'native':native,'arrays':arrays,'chance':chance,'utility':utility,'pointers':pointers+doubles,
                 'node_index':index,'rivers':rivers,'hand_ids':hand_ids,'counts':counts,'slots':slots,
                 'storage_entries':payoff_cells+slots,'terminal_states':len(states),'rank_orders':len(rank_ids),
                 'utility_ready':False,'training_visits':None,'measurement_visits':None}
    game.utilities=UtilityView(game);game.action_counts=InfoView(game);game.keys=game.action_counts.keys()


def library(game):
    lib=load_library()
    lib.poker_turn_utilities.argtypes=[C.POINTER(Input)];lib.poker_turn_utilities.restype=C.c_int
    lib.poker_turn_train.argtypes=[C.POINTER(Input),C.c_int,C.c_uint64,C.POINTER(C.c_double),C.POINTER(C.c_uint64)]
    lib.poker_turn_train.restype=C.c_int
    lib.poker_turn_measure.argtypes=[C.POINTER(Input),C.POINTER(C.c_double),C.c_int,C.c_uint64,C.POINTER(C.c_double),C.POINTER(C.c_uint64)]
    lib.poker_turn_measure.restype=C.c_int
    if not game.packed['utility_ready']:
        code=lib.poker_turn_utilities(C.byref(game.packed['native']))
        if code:raise RuntimeError('Turn payoff kernel rejected input: '+str(code))
        game.packed['utility_ready']=True
    return lib



def uniform(game):
    data=array('d',[0.])*game.packed['slots']
    for node in game.nodes:
        if node.actor<0 or len(node.actions)==1:continue
        i=game.packed['node_index'][id(node)];count=len(node.actions)
        size=count*game.packed['counts'][node.actor]*(len(game.packed['rivers']) if node.street=='river' else 1)
        start=game.packed['arrays']['base'][i]
        data[start:start+size]=array('d',[1/count])*size
    return Policy(game,data)


def train(game,iterations,max_visits):
    lib=library(game);data=array('d',[0.])*game.packed['slots'];visits=C.c_uint64()
    output=(C.c_double*len(data)).from_buffer(data)
    code=lib.poker_turn_train(C.byref(game.packed['native']),iterations,max_visits,output,C.byref(visits))
    game.packed['training_visits']=visits.value
    if code==4:raise ValueError('Actual traversal budget exceeded; no partial result.')
    if code:raise RuntimeError('Turn CFR kernel rejected input: '+str(code))
    return Policy(game,data)


def evaluate(game,policy,probe=-1):
    if not isinstance(policy,Policy) or policy.game is not game or len(policy._data)!=game.packed['slots']:
        raise ValueError('Matching immutable packed policy required.')
    lib=library(game);count=len(game.root.actions) if game.root.actor>=0 and probe>=0 else 0
    result=array('d',[0.])*(2*game.n+count+1);visits=C.c_uint64()
    data=(C.c_double*len(policy._data)).from_buffer(policy._data)
    output=(C.c_double*len(result)).from_buffer(result)
    code=lib.poker_turn_measure(C.byref(game.packed['native']),data,probe,200000000,output,C.byref(visits))
    game.packed['measurement_visits']=visits.value
    if code==4:raise ValueError('Measurement traversal budget exceeded; no partial result.')
    if code==5:raise ValueError('Unsupported own hand.')
    if code:raise ValueError('Invalid packed policy or evaluation input: '+str(code))
    if any(not math.isfinite(v) for v in result):raise ValueError('Nonfinite turn evidence.')
    values=[result[2*p] for p in range(game.n)];best=[result[2*p+1] for p in range(game.n)]
    gains=[max(0.,b-v) for b,v in zip(best,values)]
    metrics={'policy_payoffs':values,'best_response_payoffs':best,'unilateral_gains':gains,
             'nash_conv_chips':sum(gains),'max_unilateral_gain_pct_pot':max(gains)/game.decision_pot*100}
    return metrics,list(result[2*game.n:2*game.n+count]),result[-1]


def measure(game,policy):
    if not isinstance(policy,Policy) or policy.game is not game:raise ValueError('Matching packed policy required.')
    if policy.metrics is None:policy.metrics=evaluate(game,policy)[0]
    return policy.metrics


def root_values(game,policy,own_hand):
    actor=game.root.actor
    if own_hand not in game.packed['hand_ids'][actor]:raise ValueError('Unsupported own hand.')
    if own_hand not in policy.roots:
        metrics,values,mass=evaluate(game,policy,game.packed['hand_ids'][actor][own_hand])
        policy.metrics=metrics
        probabilities=policy[game.key(game.root,next(d for d,(h,_,_,_) in enumerate(game.outcomes) if h[actor]==own_hand))]
        best=max(values);sunk=game.initial_contributions[actor]+game.root.invested[actor]
        policy.roots[own_hand]={'actor':actor,'own_hand':own_hand,'conditional_mass':mass,
            'ev_basis':'from_current_decision_prior_contributions_are_sunk',
            'continuation':'same_fixed_profile_after_each_first_action','sunk_chips':sunk,
            'policy_ev_chips':sum(p*v for p,v in zip(probabilities,values)),
            'actions':[{'action':a,'probability':p,'ev_chips':v,'gap_to_best_first_action_chips':max(0.,best-v)}
                       for a,p,v in zip(game.root.actions,probabilities,values)]}
    return policy.roots[own_hand]
