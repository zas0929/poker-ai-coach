"""Derived comparisons from saved solves; never reruns or selects a winning seed."""
import argparse
from itertools import combinations
import json
from pathlib import Path
from research.benchmark_range_stability import modes


def usable(row):
    return row.get('status') == 'completed' and row.get('passes_quality_gate') is True


def distance(a, b):
    if a['actions'] != b['actions']:
        raise ValueError('Identical action tree required.')
    return {'same_modes': modes(a) == modes(b),
            'tv': sum(abs(x-y) for x,y in zip(a['probabilities'],b['probabilities'])) / 2}


def aggregate(values):
    return {'pairs': len(values), 'same_modes': sum(v['same_modes'] for v in values),
            'mean_tv': sum(v['tv'] for v in values)/len(values) if values else None,
            'max_tv': max((v['tv'] for v in values), default=None)}


def summarize(report):
    rows=report['results']; lookup={}
    for row in rows:
        c=row['candidate']; lookup[(row['case'],row['probe'],c['method'],c['width'],c['seed'])]=row
    result={'seed_stability':{}, 'width_stability':{}, 'matched_reference_losses':{}}
    cases=sorted({(r['case'],r['probe']) for r in rows})
    for method in ('uniform','stratified'):
        for width in report['candidate_widths']:
            values=[]; eligible=0
            for case,probe in cases:
                candidates=[lookup[(case,probe,method,width,s)]['candidate'] for s in report['seeds']]
                if all(usable(c) for c in candidates):
                    eligible+=1
                    values.extend(distance(a,b) for a,b in combinations(candidates,2))
            result['seed_stability'][method+'_'+str(width)]={
                'eligible_probes':eligible,'attempted_probes':len(cases),**aggregate(values)}
        values=[]
        for case,probe in cases:
            for seed in report['seeds']:
                a,b=[lookup[(case,probe,method,w,seed)]['candidate'] for w in report['candidate_widths']]
                if usable(a) and usable(b):values.append(distance(a,b))
        result['width_stability'][method]=aggregate(values)
    # Equal populations: neither method gains from excluding only its own failures.
    for width in report['candidate_widths']:
        matched=[]
        for case,probe in cases:
            for seed in report['seeds']:
                pair=[lookup[(case,probe,m,width,seed)] for m in ('uniform','stratified')]
                if all(len(r['comparisons'])==2 and usable(r['candidate']) for r in pair):matched.append(pair)
        result['matched_reference_losses'][str(width)]={'matched_candidates_per_method':len(matched)}
        for i,method in enumerate(('uniform','stratified')):
            values=[c['first_action_loss_bb'] for pair in matched for c in pair[i]['comparisons'].values()]
            result['matched_reference_losses'][str(width)][method]={
                'comparisons':len(values),'mean_loss_bb':sum(values)/len(values) if values else None,
                'max_loss_bb':max(values,default=None)}
    refs=[r['comparison'] for r in report['reference_disagreements'] if r['comparison'] is not None]
    result['reference_agreement']=aggregate(refs)
    result['limitations']=[
        'Paired TV compares strategies only within an identical action tree; no cross-range raw payoff comparison.',
        'Reference loss is a first-action diagnostic with optimal own continuation against a finite reference policy, not measured real-game loss.',
        'Four public states and three own hands per state are a diagnostic corpus, not statistical validation.',
        'All seed pairs require all three seeds to pass quality; refusals and quality failures remain excluded, never scored as success.',
        'Both reference selectors remain biased finite models; agreeing with either is not proof of full-range correctness.']
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report',type=Path);args=parser.parse_args()
    print(json.dumps(summarize(json.loads(args.report.read_text())),indent=2,allow_nan=False))
