"""Paired range sensitivity: small anchored subsets vs larger nested subsets.
Independent bounded-game quality gates do not guarantee stability across ranges.
"""
import json
from hashlib import sha256
from pathlib import Path
import random
import sys
from research.analysis_contract import analyze,ResearchLimits
from research.benchmark_midriver_ranges import scenarios
from research.public_subset_policy import select_public_subset,POLICY_NAME
import research.public_subset_policy as policy_module


def benchmark():
    rows=[];widths={2:16,3:8,4:6,5:4,6:4}
    for case in scenarios():
        if case['name'] not in {f'{t}_{n}' for t in ('dry','flush') for n in range(2,7)}:continue
        snapshot=case['snapshot'];actor=next(p for p in snapshot['players'] if p['id']==snapshot['actor_id'])
        own=random.Random(case['seed']+777).choice(actor['range'])['cards'];arms={}
        for label,width in [('small',3),('wider',widths[len(snapshot['players'])])]:
            policy={'name':POLICY_NAME,'width':width,'seed':20261024,'max_joint_combos':4096}
            selected,canonical,evidence=select_public_subset(snapshot,own,policy)
            request={'snapshot':snapshot,'selected_hands':selected,'own_hand':canonical,
                     'input':{'bet_sizes':[10],'raise_sizes':[40],'max_raises':1,'max_joint_combos':4096,'utility_storage':'compact'}}
            result=analyze(request,ResearchLimits(wall_seconds=45))
            arms[label]={'selection':evidence,'result':result}
            print(case['name']+' '+label+': '+result['status'],file=sys.stderr,flush=True)
        small=arms['small']['result'];wide=arms['wider']['result'];comparison=None
        if small['status']=='ready' and wide['status']=='ready':
            a=small['candidate'];b=wide['candidate']
            if a['actions']!=b['actions']:raise AssertionError('Action tree must match across range controls.')
            distance=.5*sum(abs(x-y) for x,y in zip(a['probabilities'],b['probabilities']))
            modes=lambda c:[x for x,p in zip(c['actions'],c['probabilities']) if abs(p-max(c['probabilities']))<1e-8]
            comparison={'root_total_variation':distance,'small_modes':modes(a),'wider_modes':modes(b),
                        'same_modes':modes(a)==modes(b),'within_diagnostic_tv_015':distance<=.15}
        rows.append({'name':case['name'],'source_information_key':snapshot['information_key'],
                     'own_probe':own,'arms':arms,'comparison':comparison})
    comparable=[r for r in rows if r['comparison'] is not None]
    return {'policy_source_sha256':sha256(Path(policy_module.__file__).read_bytes()).hexdigest(),
        'scope':'10 paired deterministic public river probes, known acting-hand anchor, nested uniform subsets preserving original public weights. Wider is a sensitivity control, not full-range truth.',
        'diagnostic_tv_threshold':.15,'results':rows,
        'summary':{'cases':len(rows),'comparable':len(comparable),
                   'same_modes':sum(r['comparison']['same_modes'] for r in comparable),
                   'within_tv_015':sum(r['comparison']['within_diagnostic_tv_015'] for r in comparable),
                   'statuses':{status:sum(a['result']['status']==status for r in rows for a in r['arms'].values())
                               for status in sorted({a['result']['status'] for r in rows for a in r['arms'].values()})}}}


if __name__=='__main__':print(json.dumps(benchmark(),indent=2,allow_nan=False))
