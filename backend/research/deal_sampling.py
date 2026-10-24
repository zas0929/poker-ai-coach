"""Whole-lineup rejection sampling of product-weighted river ranges.
No grouping, no own-hand anchors, no sequential card repair or coverage rerolls.
"""
from bisect import bisect_right
from collections import Counter
from itertools import accumulate
import math
import random
import re
from research.compact_utilities import CompactUtilities


def sample_joint_ranges(board,ranges,*,folded=(),samples,seed,max_attempts):
    for value,lo,hi in ((samples,1,65536),(seed,0,2**32-1),(max_attempts,samples,1000000)):
        if type(value) is not int or not lo<=value<=hi:raise ValueError('Explicit sample, seed and proposal budgets required.')
    if not 2<=len(ranges)<=6 or len(board)!=5 or any(not isinstance(c,str) or not re.fullmatch(r'[2-9TJQKA][cdhs]',c) for c in board) or len(set(board))!=5:
        raise ValueError('Two to six seats and five distinct river cards required.')
    if len(set(folded))!=len(folded) or any(type(p) is not int or not 0<=p<len(ranges) for p in folded):raise ValueError('Invalid folded seats.')
    live=[p for p in range(len(ranges)) if p not in folded]
    if len(live)<2 or any(ranges[p] for p in folded):raise ValueError('Two live ranges required; folded ranges empty.')
    tables={}
    for p in live:
        if not ranges[p] or len(ranges[p])>1081:raise ValueError('1–1081 combos per live range required.')
        seen=set();rows=[];weights=[]
        for text,w in sorted(ranges[p]):
            if not isinstance(text,str) or not re.fullmatch(r'(?:[2-9TJQKA][cdhs]){2}',text):raise ValueError('Invalid combo.')
            pair=frozenset((text[:2],text[2:]))
            if len(pair)!=2 or pair & set(board) or pair in seen:raise ValueError('Duplicate or board-blocked combo.')
            if type(w) not in (int,float) or not math.isfinite(w) or w<=0:raise ValueError('Finite positive weights required.')
            seen.add(pair);rows.append((text,pair));weights.append(w)
        total=math.fsum(weights)
        if not math.isfinite(total):raise ValueError('Range mass overflow.')
        cumulative=list(accumulate(w/total for w in weights));tables[p]=(rows,cumulative)
    rng=random.Random(seed);counts=Counter();accepted=0;attempts=0
    while accepted<samples and attempts<max_attempts:
        attempts+=1;texts=[None]*len(ranges);used=set();legal=True
        for p in live:
            rows,cumulative=tables[p];index=min(len(rows)-1,bisect_right(cumulative,rng.random()*cumulative[-1]))
            text,pair=rows[index];texts[p]=text
            if used & pair:legal=False
            used.update(pair)
        # Discard the WHOLE lineup. Retrying just a blocked seat biases the law.
        if legal:counts[tuple(texts)]+=1;accepted+=1
    return {'status':'sampled' if accepted==samples else 'proposal_budget_exhausted',
        'counts':dict(counts),'accepted':accepted,'attempts':attempts,'requested':samples,'seed':seed,
        'max_attempts':max_attempts,'live_advice_allowed':False}


class SampleView:
    def __init__(self,game,draw):
        if draw['status']!='sampled' or sum(draw['counts'].values())!=draw['requested']:
            raise ValueError('Only complete fixed-size samples may be trained.')
        lookup={texts:(d,score) for d,(texts,w,score) in enumerate(game.deals)}
        self.n=game.n;self.nodes=game.nodes;self.root=game.root;self.decision_pot=game.decision_pot
        self.deals=[];indices=[]
        for texts,count in sorted(draw['counts'].items(),key=lambda row:str(row[0])):
            if texts not in lookup:raise ValueError('Sample contains a deal outside original legal support.')
            d,score=lookup[texts];indices.append(d);self.deals.append((texts,count/draw['requested'],score))
        self.utilities=CompactUtilities(self.nodes,len(self.deals),self.n)
        for node in self.nodes:
            if node.actor==-1:
                for d,original in enumerate(indices):self.utilities.put(node,d,game.utilities[(id(node),original)])
        self.keys={(node.actor,texts[node.actor],node.history) for node in self.nodes if node.actor!=-1 for texts,_,_ in self.deals}
        self.action_counts={key:game.action_counts[key] for key in self.keys}
        self.missing_keys=game.keys-self.keys

    def key(self,node,deal):return (node.actor,self.deals[deal][0][node.actor],node.history)
