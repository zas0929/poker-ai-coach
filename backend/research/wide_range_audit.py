"""Tree-free compression audit. No joint deal enumeration or solver admission.

Compact pair signatures implement the conservative exact river equivalence.
Identical range supports share relation tables; weights never change legality.
"""
from collections import defaultdict
from hashlib import sha256
import json
import math
import re
from app.services.hand_evaluator import HandEvaluator
from research.river_reference import cards

NAME='wide_exact_relation_audit_v1'


def audit_ranges(board,ranges,*,folded=(),max_pair_checks=36000000):
    if type(max_pair_checks) is not int or not 1<=max_pair_checks<=36000000:
        raise ValueError('Explicit pair budget 1–36000000 required.')
    if not 2<=len(ranges)<=6 or len(board)!=5 or any(not isinstance(c,str) or not re.fullmatch(r'[2-9TJQKA][cdhs]',c) for c in board) or len(set(board))!=5:
        raise ValueError('Two to six seats and five distinct river cards required.')
    if len(set(folded))!=len(folded) or any(type(p) is not int or not 0<=p<len(ranges) for p in folded):
        raise ValueError('Invalid folded seats.')
    live=[p for p in range(len(ranges)) if p not in folded]
    if len(live)<2 or any(ranges[p] for p in folded) or any(not ranges[p] or len(ranges[p])>1081 for p in live):
        raise ValueError('Two or more live ranges, 1–1081 hands each; folded ranges empty.')
    checks=sum(len(ranges[p])*len(ranges[q]) for p in live for q in live if p!=q)
    if checks>max_pair_checks:raise ValueError('Pair budget exceeded; no truncation.')
    deck=[r+s for r in '23456789TJQKA' for s in 'cdhs'];bits={c:1<<i for i,c in enumerate(deck)}
    bc=cards(''.join(board));evaluator=HandEvaluator();masks={};scores={};rows=[]
    for source in ranges:
        seen=set();normalized=[]
        for text,weight in source:
            if not isinstance(text,str) or not re.fullmatch(r'(?:[2-9TJQKA][cdhs]){2}',text):raise ValueError('Invalid hand.')
            pair=tuple(sorted((text[:2],text[2:])))
            if len(set(pair))!=2 or set(pair)&set(board) or pair in seen:raise ValueError('Duplicate or blocked hand.')
            if type(weight) not in (float,int) or not math.isfinite(weight) or weight<=0:raise ValueError('Positive finite weights required.')
            seen.add(pair);canonical=''.join(pair);normalized.append((canonical,weight))
            if canonical not in masks:
                masks[canonical]=bits[pair[0]]|bits[pair[1]]
                scores[canonical]=evaluator.score([*bc,*cards(canonical)])
        rows.append(sorted(normalized))
    supports=[tuple(t for t,_ in source) for source in rows];tables={};evaluated=0
    for p in live:
        for q in live:
            if p==q:continue
            key=(supports[p],supports[q])
            if key in tables:continue
            table=[]
            for own in key[0]:
                relations=bytes(0 if masks[own]&masks[other] else
                                2+(scores[own]>scores[other])-(scores[own]<scores[other]) for other in key[1])
                table.append((relations,bytes(int(v!=0) for v in relations)))
            tables[key]=table;evaluated+=len(key[0])*len(key[1])
    groups=[];blocker_widths=[]
    for p,source in enumerate(rows):
        buckets=defaultdict(list);blockers=set()
        for i,(text,weight) in enumerate(source):
            pairs=[tables[(supports[p],supports[q])][i] for q in live if q!=p]
            buckets[tuple(pair[0] for pair in pairs)].append((text,weight))
            blockers.add(tuple(pair[1] for pair in pairs))
        seat=[]
        for members in buckets.values():
            mass=math.fsum(w for _,w in members)
            if not math.isfinite(mass):raise ValueError('Group mass overflow.')
            seat.append({'representative':members[0][0],'members':[t for t,_ in members],'weight':mass})
        groups.append(seat);blocker_widths.append(len(blockers))
    original=[len(r) for r in rows];compressed=[len(g) for g in groups]
    before=math.prod(max(1,w) for w in original);after=math.prod(max(1,w) for w in compressed)
    return {'name':NAME,'status':'audited','original_widths':original,'compressed_widths':compressed,
        'blocker_only_widths':blocker_widths,'logical_pair_checks':checks,'evaluated_pair_relations':evaluated,
        'unique_relation_tables':len(tables),'raw_product_before':before,'raw_product_after':after,
        'raw_product_reduction_factor':before/after,'within_raw_solver_budget':after<=4096,
        'groups_sha256':sha256(json.dumps(groups,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'groups':groups,'live_advice_allowed':False,'solver_quality_verified':False,
        'scope':'Exact relation equivalence only. No joint deals, action tree, solve, EV, or quality admission.'}
