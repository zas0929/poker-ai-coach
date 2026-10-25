"""Reproducible offline sensitivity audit; agreement is not an accuracy certificate.

Each sample is a separate, fully solved subset game. Frequencies/EVs from distinct
opponent distributions are never averaged into a claimed equilibrium strategy.
"""
import argparse
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path
from research import turn_analysis
from research.analysis_contract import ResearchLimits
from research.benchmark_turn_factored import FIXTURE
from research.river_snapshot import digest
from research.trainer_ranges import VERSION, select_ranges


def summarize(samples):
    ready = [r for r in samples if r['status'] == 'ready']
    common = None
    for r in ready:
        values = r['action_values']
        best = max(values['ev_chips'])
        preferred = {a for a, v in zip(values['actions'], values['ev_chips']) if best-v <= 1e-7}
        common = preferred if common is None else common & preferred
    complete = len(ready) == len(samples) and len(samples) >= 3
    actions = sorted({a for r in ready for a in r['action_values']['actions']})
    spans = {}
    for a in actions:
        values = [r['action_values']['ev_chips'][r['action_values']['actions'].index(a)]
                  for r in ready if a in r['action_values']['actions']]
        spans[a] = {'min': min(values), 'max': max(values), 'spread': max(values)-min(values)}
    return {'requested_samples': len(samples), 'admitted_samples': len(ready),
        'status': ('agreement_observed' if common else 'sensitive') if complete else 'inconclusive',
        'common_best_actions': sorted(common or []) if complete else [],
        'ev_spans': spans, 'reliable_advice': False,
        'interpretation': 'Small-subset stress test only. Agreement does not establish full-range accuracy; EV spans are not confidence intervals.'}


def audit(request, samples=3, iterations=100):
    if type(samples) is not int or not 3 <= samples <= 20:
        raise ValueError('3-20 independent reproducible samples required.')
    rows = []
    for trial in range(samples):
        selected, _, coverage, sampling = select_ranges(request['snapshot'], request['own_hand'], trial=trial)
        variant = deepcopy(request)
        variant['selected_hands'] = selected
        variant['input'].update(utility_storage='factored', max_nodes=30000, max_work=6000000)
        result = turn_analysis.analyze(variant, ResearchLimits(iterations=iterations))
        rows.append({'trial': trial, 'selected_hands': selected, 'coverage': coverage, 'sampling': sampling,
            'request_key': digest(variant), 'status': result['status'], 'reasons': result['reasons'],
            'quality': result['quality'], 'timing': result['timing'], 'action_values': result.get('action_values')})
    return {'source_information_key': request['snapshot']['information_key'],
        'own_hand': request['own_hand'], 'live_players': request['snapshot']['live_player_count'],
        'summary': summarize(rows), 'samples': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--iterations', type=int, default=100)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    output = {'version': 1, 'fixture_sha256': sha256(FIXTURE.read_bytes()).hexdigest(),
        'sampling_version': VERSION, 'engine': turn_analysis.provenance(), 'results': []}
    for request in fixture['requests']:
        result = audit(request, args.samples, args.iterations)
        output['results'].append(result)
        args.output.write_text(json.dumps(output, indent=2)+'\n')
        print(json.dumps({'live_players': result['live_players'], **result['summary']}), flush=True)
