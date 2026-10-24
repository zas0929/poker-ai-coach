"""Lossless river-only range quotient for bounded explicit ranges, offline only.

Merge hands ONLY when every opposing original hand has the same collision and
showdown relation. Thus pairwise legality and all terminal payouts are preserved.
This is a conservative baseline, not a full-range approximate abstraction.
"""
from collections import defaultdict
from itertools import product
import math
import re
from app.services.hand_evaluator import HandEvaluator
from research.river_reference import cards

NAME='exact_river_relation_quotient_v1'


def compress_ranges(board, ranges, *, folded=(), max_pair_checks=100000):
    if not 2<=len(ranges)<=6 or len(board)!=5 or len(set(board))!=5 or any(not isinstance(c,str) or not re.fullmatch(r'[2-9TJQKA][cdhs]',c) for c in board):
        raise ValueError('Two to six seats and five distinct river cards required.')
    if type(max_pair_checks) is not int or not 1<=max_pair_checks<=100000:
        raise ValueError('Explicit pair budget 1–100000 required.')
    if len(set(folded))!=len(folded) or any(type(p) is not int or not 0<=p<len(ranges) for p in folded):
        raise ValueError('Invalid folded seats.')
    live=[p for p in range(len(ranges)) if p not in folded]
    if len(live)<2 or any(ranges[p] for p in folded) or any(not ranges[p] or len(ranges[p])>64 for p in live):
        raise ValueError('Two or more live ranges, 1–64 hands each; folded ranges empty.')
    checks=sum(len(ranges[p])*len(ranges[q]) for p in live for q in live if p!=q)
    if checks>max_pair_checks:raise ValueError('Pair budget exceeded; no truncation.')
    evaluator=HandEvaluator();bc=cards(''.join(board));scores={};holes={}
    for p in live:
        seen=set()
        for text,weight in ranges[p]:
            if not isinstance(text,str) or not re.fullmatch(r'(?:[2-9TJQKA][cdhs]){2}',text):
                raise ValueError('Invalid hole cards.')
            key=frozenset((text[:2],text[2:]))
            if len(key)!=2 or key & set(board) or key in seen:raise ValueError('Duplicate or blocked hand.')
            if isinstance(weight,bool) or not isinstance(weight,(float,int)) or not math.isfinite(weight) or weight<=0:
                raise ValueError('Positive finite weights required.')
            seen.add(key);holes[text]=key;scores[text]=evaluator.score([*bc,*cards(text)])
    compressed=[];mapping=[];groups=[]
    for p,rows in enumerate(ranges):
        buckets=defaultdict(list)
        for text,weight in sorted(rows):
            signature=tuple(None if holes[text] & holes[other] else
                            (scores[text]>scores[other])-(scores[text]<scores[other])
                            for q in live if q!=p for other,_ in sorted(ranges[q]))
            buckets[signature].append((text,weight))
        output=[];seatmap={};seatgroups=[]
        for members in buckets.values():
            representative=members[0][0];mass=math.fsum(w for _,w in members)
            if not math.isfinite(mass):raise ValueError('Group mass overflow.')
            output.append((representative,mass))
            for text,_ in members:seatmap[text]=representative
            seatgroups.append({'representative':representative,'members':[t for t,_ in members],'weight':mass})
        compressed.append(output);mapping.append(seatmap);groups.append(seatgroups)
    return {'name':NAME,'ranges':compressed,'mapping':mapping,'groups':groups,
            'pair_checks':checks,'original_widths':[len(r) for r in ranges],
            'compressed_widths':[len(r) for r in compressed],
            'live_advice_allowed':False,
            'scope':'Exact equivalence for supplied river ranges only; no full-range calibration or earlier-street claim.'}


def lift_policy(full_game, compressed_policy, quotient):
    return {key:list(compressed_policy[(key[0],quotient['mapping'][key[0]][key[1]],key[2])])
            for key in full_game.keys}


def verify_quotient(full, reduced, quotient, *, max_terminal_checks=1000000):
    """Exhaustively compare joint masses and every terminal/player utility."""
    if type(max_terminal_checks) is not int or not 1<=max_terminal_checks<=1000000:
        raise ValueError('Explicit verification budget required.')
    original={n.history:n for n in full.nodes};small={n.history:n for n in reduced.nodes}
    if set(original)!=set(small) or any((n.actor,n.actions,n.invested,n.alive)!=(small[h].actor,small[h].actions,small[h].invested,small[h].alive) for h,n in original.items()):
        raise ValueError('Identical public trees required.')
    terminals=[n for n in full.nodes if n.actor==-1]
    checks=len(terminals)*len(full.deals)*full.n
    raw_count=math.prod(max(1,len(r)) for r in full.ranges)
    if checks+raw_count>max_terminal_checks:raise ValueError('Terminal verification budget exceeded.')
    # Check illegal original lineups too: normalized legal masses alone can hide
    # an abstraction that silently makes blocked card combinations legal.
    blocked=0
    for lineup in product(*(r if p in full.live else [(None,1)] for p,r in enumerate(full.ranges))):
        texts=[t for t,_ in lineup]
        target=[quotient['mapping'][p][t] if t is not None else None for p,t in enumerate(texts)]
        def legal(hands):
            deck=[t[i:i+2] for t in hands if t is not None for i in (0,2)]
            return len(deck)==len(set(deck))
        valid=legal(texts);blocked+=int(not valid)
        if valid!=legal(target):raise ValueError('Original/compressed lineup card compatibility differs.')
    targets={texts:i for i,(texts,_,_) in enumerate(reduced.deals)};masses=defaultdict(float)
    max_error=0.
    for d,(texts,weight,_) in enumerate(full.deals):
        target=tuple(quotient['mapping'][p][t] if t is not None else None for p,t in enumerate(texts))
        if target not in targets:raise ValueError('Legal original deal mapped to illegal compressed deal.')
        e=targets[target];masses[target]+=weight
        for node in terminals:
            a=full.utilities[(id(node),d)];b=reduced.utilities[(id(small[node.history]),e)]
            max_error=max(max_error,max(abs(x-y) for x,y in zip(a,b)))
    if set(masses)!=set(targets):raise ValueError('Compressed deal has no original preimage.')
    mass_error=max(abs(masses[t]-reduced.deals[e][1]) for t,e in targets.items())
    if max_error>1e-9 or mass_error>1e-9:raise ValueError('Quotient failed exact utility/mass validation.')
    return {'terminal_player_checks':checks,'raw_lineups_checked':raw_count,'blocked_lineups_checked':blocked,
            'max_utility_error_chips':max_error,
            'max_normalized_joint_mass_error':mass_error,'verified':True}
