"""Explicit seeded, nested PUBLIC subsets with a declared acting-hand anchor.
Preserves original weights, not an unbiased estimator or full-range GTO model.
"""
import copy
import math
import random
from research.river_snapshot import combo_key,digest

POLICY_NAME='anchored_public_subset_v1'


def validate_policy(value):
    if type(value) is not dict or set(value)!={'name','width','seed','max_joint_combos'} or value['name']!=POLICY_NAME:
        raise ValueError('Explicit anchored_public_subset_v1 policy required.')
    for key,low,high in [('width',2,64),('seed',0,2**32-1),('max_joint_combos',1,4096)]:
        if type(value[key]) is not int or not low<=value[key]<=high:raise ValueError('Invalid explicit subset policy limit.')
    return copy.deepcopy(value)


def select_public_subset(snapshot,own_hand,policy):
    policy=validate_policy(policy);actor=snapshot['actor_id'];own_key=combo_key(own_hand)
    players=[p for p in snapshot['players'] if p['status']!='folded']
    if not 2<=len(players)<=6 or actor not in [p['id'] for p in players]:raise ValueError('Two to six live seats and acting id required.')
    width=policy['width'];raw=width**len(players)
    if raw>policy['max_joint_combos']:raise ValueError('Explicit subset width exceeds raw joint-combo budget; no auto-shrinking.')
    chosen={};weights={}
    for p in players:
        rows=p['range']
        if len(rows)<width:raise ValueError('Public range narrower than requested width; no auto-shrinking.')
        # Seed deliberately excludes own cards and width. Wider subsets extend the same ordering.
        seed=int(digest({'source':snapshot['information_key'],'seat':p['id'],'seed':policy['seed']})[:16],16)
        ordered=sorted(rows,key=lambda row:combo_key(row['cards']))
        rng=random.Random(seed);rng.shuffle(ordered)
        if p['id']==actor:
            matches=[row for row in rows if combo_key(row['cards'])==own_key]
            if len(matches)!=1:raise ValueError('Acting hand must be a public legal combo.')
            ordered=[matches[0]]+[row for row in ordered if combo_key(row['cards'])!=own_key]
        selected=ordered[:width]
        chosen[p['id']]=[row['cards'] for row in selected]
        weights[p['id']]=[{'cards':row['cards'],'weight':row['weight']} for row in selected]
    canonical=chosen[actor][0]
    evidence={'name':POLICY_NAME,'seed':policy['seed'],'width':width,'raw_combinations':raw,
              'selected_key':digest(weights),'actor_anchor':True,'opponents_seeded_without_own_hand':True,'range_stability_verified':False,
              'limitations':['Selected subsets retain public weights; finite renormalized selection is not an unbiased full-range estimate.',
                             'Acting hand anchors its own range; this changes the bounded game and may change opponents responses.',
                             'No private opponent holdings or folded-card bunching are used.']}
    return chosen,canonical,evidence


def validate_tree_policy(value):
    if type(value) is not dict or set(value)!={'bet_sizes_bb','raise_sizes_bb','max_raises','include_coach_size'}:
        raise ValueError('Explicit BB tree sizes, raise cap and include_coach_size required.')
    for key in ('bet_sizes_bb','raise_sizes_bb'):
        values=value[key]
        if type(values) is not list or len(values)>3 or len(set(values))!=len(values) or any(type(v) is not int or not 1<=v<=100 for v in values):
            raise ValueError('At most three distinct integer BB sizes 1–100 required.')
    if not value['bet_sizes_bb'] or type(value['max_raises']) is not int or not 0<=value['max_raises']<=3 or type(value['include_coach_size']) is not bool:
        raise ValueError('Opening sizes, 0–3 future raises and explicit boolean required.')
    return copy.deepcopy(value)


def tree_from_policy(snapshot,baseline,tree,raw_budget):
    tree=validate_tree_policy(tree)
    maximum=max(p['stack']+p['street_committed'] for p in snapshot['players'] if p['status']!='folded')
    if maximum<=0:raise ValueError('A funded acting seat required.')
    sizes={kind:{min(maximum,v*snapshot['big_blind']) for v in tree[kind+'_sizes_bb']} for kind in ('bet','raise')}
    if tree['include_coach_size'] and baseline['action'] in ('bet','raise'):
        amount=baseline['amount']
        if type(amount) is not int or not 1<=amount<=maximum:raise ValueError('Invalid exact coach size.')
        sizes[baseline['action']].add(amount)
    return {'bet_sizes':sorted(sizes['bet']),'raise_sizes':sorted(sizes['raise']),
            'max_raises':tree['max_raises'],'max_joint_combos':raw_budget,'utility_storage':'compact'}
