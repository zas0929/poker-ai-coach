"""Offline differential audit; PokerKit is an optional research dependency only.
Run from backend: PYTHONPATH=. <audit-python> research/audit_engine.py
"""
import json
import random
import time
from importlib.metadata import version
from itertools import product
from pokerkit import StandardHighHand
from app.models.poker import Card, HandState, Player, Rank, Street, Suit
from app.services.equity_service import EquityService
from app.services.hand_evaluator import HandEvaluator
from app.services.range_service import OpponentRange, RangeService, WeightedCombo

SUITS = {Suit.SPADES:'s', Suit.HEARTS:'h', Suit.DIAMONDS:'d', Suit.CLUBS:'c'}
def notation(cards):
    return ''.join(c.rank.value + SUITS[c.suit] for c in cards)
def reference(cards):
    return StandardHighHand.from_game(notation(cards))
def outcome(a,b):
    return .5 if a==b else float(a>b)
def hand(hero,board,others=1):
    return HandState(hand_id='offline-audit',street=Street.RIVER if len(board)==5 else Street.TURN,pot=100,small_blind=1,big_blind=2,dealer_player_id='hero',current_player_id='hero',board=board,players=[Player(id='hero',name='Hero',stack=100,position='button',cards=hero)]+[Player(id=f'v{i}',name='Opponent',stack=100,position='big_blind',cards=[]) for i in range(others)])

def run():
    rng=random.Random(20261024)
    deck=[Card(rank=r,suit=s) for r in Rank for s in Suit]
    evaluator=HandEvaluator(); equity=EquityService(); started=time.perf_counter()
    comparisons=0
    for size in (5,6,7):
        for _ in range(5000):
            a,b=rng.sample(deck,size),rng.sample(deck,size)
            assert outcome(evaluator.score(a),evaluator.score(b))==outcome(reference(a),reference(b)), (notation(a),notation(b))
            comparisons+=1
    ordering_seconds=time.perf_counter()-started
    river_cases=0
    for _ in range(20):
        cards=rng.sample(deck,7);state=hand(cards[:2],cards[2:]);known=set(notation([c]) for c in cards)
        remaining=[c for c in deck if notation([c]) not in known]
        inferred=RangeService().infer(state)
        combos={}
        while len(combos)<16:
            pair=tuple(rng.sample(remaining,2));key=tuple(sorted(notation([c]) for c in pair));combos[key]=WeightedCombo(pair,rng.choice([.25,.5,1,3]))
        inferred.combos=list(combos.values());hero=reference(cards)
        expected=sum(c.weight*outcome(hero,reference([*c.cards,*state.board])) for c in inferred.combos)/sum(c.weight for c in inferred.combos)
        actual=equity.estimate(state,opponent_range=inferred)
        assert actual.method=='exact_river' and abs(actual.equity-expected)<=.000051,(actual,expected)
        river_cases+=1
    # Independent exact enumeration of all turn runouts for a fixed opponent hand.
    dealt=rng.sample(deck,8);state=hand(dealt[:2],dealt[2:6]);inferred=RangeService().infer(state)
    inferred.combos=[WeightedCombo(tuple(dealt[6:8]),1)]
    blocked={notation([c]) for c in dealt};rivers=[c for c in deck if notation([c]) not in blocked]
    exact=sum(outcome(reference([*dealt[:6],c]),reference([*dealt[6:8],*state.board,c])) for c in rivers)/len(rivers)
    estimated=equity.estimate(state,opponent_range=inferred,simulations=10000)
    assert abs(estimated.equity-exact)<=estimated.sampling_error,(estimated,exact)
    # Multiway reference conditions the complete product of ranges on no card collisions.
    cards=rng.sample(deck,15);state=hand(cards[:2],cards[2:7],2);template=RangeService().infer(state,opponent_id='v0')
    ranges=[OpponentRange([WeightedCombo(tuple(cards[7:9]),1),WeightedCombo(tuple(cards[9:11]),3)],template.summary),OpponentRange([WeightedCombo(tuple(cards[7:9]),2),WeightedCombo(tuple(cards[11:13]),1),WeightedCombo(tuple(cards[13:15]),2)],template.summary)]
    total=weighted=0;hero=reference(cards[:7])
    for lineup in product(*(r.combos for r in ranges)):
        keys=[notation([c]) for combo in lineup for c in combo.cards]
        if len(keys)!=len(set(keys)):continue
        weight=lineup[0].weight*lineup[1].weight;scores=[hero,*[reference([*combo.cards,*state.board]) for combo in lineup]];best=max(scores)
        weighted+=weight*(1/scores.count(best) if hero==best else 0);total+=weight
    multi=equity.estimate(state,opponent_ranges=ranges,simulations=10000)
    assert abs(multi.equity-weighted/total)<=multi.sampling_error,(multi,weighted/total)
    probe=[rng.sample(deck,7) for _ in range(10000)];t=time.perf_counter()
    for cards in probe:evaluator.score(cards)
    score_seconds=time.perf_counter()-t
    return {'seed':20261024,'pokerkit_version':version('pokerkit'),'ordering_comparisons':comparisons,'ordering_mismatches':0,'ordering_seconds':round(ordering_seconds,3),'weighted_exact_river_cases':river_cases,'river_mismatches':0,'turn':{'reference':round(exact,6),'estimate':estimated.equity,'bound_95':estimated.sampling_error},'multiway_river':{'reference':round(weighted/total,6),'estimate':multi.equity,'bound_95':multi.sampling_error},'seven_card_scores_per_second':round(10000/score_seconds),'elapsed_seconds':round(time.perf_counter()-started,3),'limitations':'Seeded differential checks, not exhaustive certification or strategy validation.'}
if __name__=='__main__':
    print(json.dumps(run(),indent=2))
