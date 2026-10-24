"""Experimental category/blocker representatives; NOT enabled in the trainer.
Equal category coverage retains source combo weights, not bucket probability mass.
"""
from collections import defaultdict
from functools import lru_cache
from itertools import combinations
import random
from app.services.hand_evaluator import HandEvaluator
from research.river_reference import cards
from research.river_snapshot import combo_key,digest
from research.public_subset_policy import validate_policy

NAME='stratified_public_subset_v1'
CATEGORIES=('high_card','pair','two_pair','trips','straight','flush','full_house','quads','straight_flush')


@lru_cache(maxsize=8)
def feature_table(board):
    board=tuple(board);evaluator=HandEvaluator();board_cards=cards(''.join(board))
    deck=[r+s for r in '23456789TJQKA' for s in 'cdhs' if r+s not in board]
    suit=max('cdhs',key=lambda s:sum(c[1]==s for c in board))
    nut=next((r+suit for r in reversed('23456789TJQKA') if r+suit not in board),None) if sum(c[1]==suit for c in board)>=3 else None
    result={}
    for pair in combinations(deck,2):
        score=evaluator.score([*board_cards,*cards(''.join(pair))])
        result[tuple(sorted(pair))]={'score':score,'category':CATEGORIES[score[0]],
            'nut_suit_blocker':nut in pair,'ace_or_king':any(c[0] in 'AK' for c in pair)}
    return result


def features(snapshot,text):return feature_table(tuple(sorted(snapshot['board'])))[combo_key(text)]


def select_stratified_subset(snapshot,own_hand,policy):
    if type(policy) is not dict or policy.get('name')!=NAME:raise ValueError('Explicit stratified policy required.')
    validate_policy({**policy,'name':'anchored_public_subset_v1'})
    width=policy['width'];actor=snapshot['actor_id'];own_key=combo_key(own_hand)
    live=[p for p in snapshot['players'] if p['status']!='folded']
    if width**len(live)>policy['max_joint_combos']:raise ValueError('Raw joint budget exceeded; no auto-shrinking.')
    selected={};weights={};coverage={}
    for player in live:
        if len(player['range'])<width:raise ValueError('Public range too narrow.')
        seed=int(digest({'source':snapshot['information_key'],'seat':player['id'],'seed':policy['seed'],'method':NAME})[:16],16)
        rng=random.Random(seed);buckets=defaultdict(list);anchor=None
        for row in sorted(player['range'],key=lambda r:combo_key(r['cards'])):
            if player['id']==actor and combo_key(row['cards'])==own_key:anchor=row;continue
            f=features(snapshot,row['cards']);buckets[(f['category'],f['nut_suit_blocker'],f['ace_or_king'])].append(row)
        keys=sorted(buckets);rng.shuffle(keys)
        for key in keys:rng.shuffle(buckets[key])
        if player['id']==actor and anchor is None:raise ValueError('Acting hand outside public range.')
        order=[anchor] if anchor else []
        while len(order)<width:
            for key in keys:
                if buckets[key]:order.append(buckets[key].pop())
                if len(order)==width:break
        selected[player['id']]=[r['cards'] for r in order]
        weights[player['id']]=order
        coverage[player['id']]=sorted({features(snapshot,r['cards'])['category'] for r in order})
    return selected,selected[actor][0],{'name':NAME,'width':width,'seed':policy['seed'],
        'selected_key':digest(weights),'category_coverage':coverage,'range_stability_verified':False,
        'limitations':['Round-robin category/blocker representatives do not preserve bucket probability mass.',
                       'Original combo weights are retained; this is an experimental bounded-game selection.',
                       'Known acting hand anchors only its own range; opponent selection is public.']}


def probe_hands(snapshot):
    actor=next(p for p in snapshot['players'] if p['id']==snapshot['actor_id'])
    ordered=sorted(actor['range'],key=lambda r:(features(snapshot,r['cards'])['score'],combo_key(r['cards'])))
    median=features(snapshot,ordered[len(ordered)//2]['cards'])['score']
    weak=[r for r in ordered if features(snapshot,r['cards'])['score']<=median]
    blockers=[r for r in weak if features(snapshot,r['cards'])['nut_suit_blocker']]
    if not blockers:blockers=[r for r in weak if features(snapshot,r['cards'])['ace_or_king']]
    chosen=[('strong',ordered[int(.9*(len(ordered)-1))]),('marginal',ordered[len(ordered)//2]),
            ('weak_blocker_candidate',(blockers or weak)[len(blockers or weak)//2])]
    result=[];seen=set()
    for label,row in chosen:
        if row['cards'] in seen:row=next(r for r in ordered if r['cards'] not in seen)
        seen.add(row['cards']);result.append({'label':label,'hand':row['cards'],'features':features(snapshot,row['cards'])})
    return result
