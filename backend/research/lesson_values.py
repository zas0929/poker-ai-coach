"""Decision-relative action EV under a fixed policy, conditional on own cards.

No best-response continuation or access to the opponents' actual hidden cards.
The separate lesson adapter leaves the frozen research contract unchanged.
"""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import time

from research import analysis_contract as contract
from research.benchmark_capacity import peak_rss_mib
from research.benchmark_expanded import run_guarded
from research.river_snapshot import build_river_from_snapshot, digest

VALUE_VERSION = 'fixed_policy_decision_ev_v1'


def value_provenance():
    return {'version': VALUE_VERSION, 'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest()}


def action_values(game, policy, own_hand):
    """Force each root action, then integrate the same fixed continuation policy.

    Chance is conditioned jointly on own hand and card compatibility. At every
    information set all deals use that actor's own cards and public history only.
    Terminal utilities are hand-net, so add back the root actor's sunk chips.
    """
    actor = game.root.actor
    if actor < 0:
        raise ValueError('An acting player is required.')
    deals = [(d, weight) for d, (texts, weight, _) in enumerate(game.deals) if texts[actor] == own_hand]
    mass = sum(weight for _, weight in deals)
    if not deals or mass <= 0:
        raise ValueError('Own hand has no compatible deal.')
    sunk = game.initial_contributions[actor] + game.root.invested[actor]

    def continuation(node, deal):
        if node.actor == -1:
            return game.utilities[(id(node), deal)][actor] + sunk
        probabilities = policy[game.key(node, deal)]
        if (len(probabilities) != len(node.children) or
                any(not contract.finite_number(p) or not 0 <= p <= 1 for p in probabilities) or
                abs(sum(probabilities) - 1) > 1e-8):
            raise ValueError('Complete normalized continuation policy required.')
        return sum(p * continuation(child, deal) for p, child in zip(probabilities, node.children))

    values = [sum(weight * continuation(child, d) for d, weight in deals) / mass
              for child in game.root.children]
    probabilities = policy[(actor, own_hand, game.root.history)]
    best = max(values)
    return {'version': VALUE_VERSION, 'actor_id': actor, 'own_hand': own_hand,
            'actions': list(game.root.actions), 'ev_chips': values,
            'gap_to_best_chips': [max(0., best - value) for value in values],
            'policy_ev_chips': sum(p * v for p, v in zip(probabilities, values)),
            'sunk_chips': sunk, 'continuation': 'fixed_learned_policy',
            'baseline': 'current_decision', 'compatible_deals': len(deals), 'conditional_mass': mass}


def valid_values(values, candidate, request):
    """Reject mismatched, nonfinite, inconsistent or incorrectly labelled EV."""
    if type(values) is not dict or type(candidate) is not dict:
        return False
    required = {'version', 'actor_id', 'own_hand', 'actions', 'ev_chips', 'gap_to_best_chips',
                'policy_ev_chips', 'sunk_chips', 'continuation', 'baseline', 'compatible_deals', 'conditional_mass'}
    if set(values) != required:
        return False
    if (values['version'] != VALUE_VERSION or values['actor_id'] != candidate['actor_id'] or
            values['own_hand'] != candidate['own_hand'] or values['actions'] != candidate['actions'] or
            values['baseline'] != 'current_decision' or values['continuation'] != 'fixed_learned_policy' or
            values['compatible_deals'] != candidate['compatible_deals'] or
            values['conditional_mass'] != candidate['conditional_mass']):
        return False
    chips, gaps = values['ev_chips'], values['gap_to_best_chips']
    count = len(candidate['actions'])
    if any(type(row) is not list or len(row) != count or any(not contract.finite_number(v) for v in row)
           for row in (chips, gaps)):
        return False
    player = next(p for p in request['snapshot']['players'] if p['id'] == candidate['actor_id'])
    if values['sunk_chips'] != player['total_committed']:
        return False
    pot, stack = request['snapshot']['pot'], player['stack']
    # All existing and remaining table chips bound the possible future net receipt.
    maximum = pot + sum(p['stack'] for p in request['snapshot']['players'] if p['id'] != player['id'])
    if any(v < -stack - 1e-7 or v > maximum + 1e-7 for v in chips):
        return False
    if any(g < 0 or abs(max(chips) - v - g) > 1e-7 for v, g in zip(chips, gaps)):
        return False
    expected = sum(p * v for p, v in zip(candidate['probabilities'], chips))
    return contract.finite_number(values['policy_ev_chips']) and abs(expected - values['policy_ev_chips']) < 1e-7


def worker(request, iterations):
    def progress(phase):
        print(json.dumps({'phase': phase, 'observed_peak_rss_mib': peak_rss_mib()}), flush=True)
    try:
        contract.validate_request(request)
        progress('build'); start = time.perf_counter()
        game, metadata = build_river_from_snapshot(request['snapshot'], request['selected_hands'], **request['input'])
    except (ValueError, TypeError, KeyError) as error:
        return {'status': 'rejected', 'reason': str(error)}
    build = time.perf_counter() - start
    actor, hand = game.root.actor, request['own_hand']
    deals = [(d, w) for d, (texts, w, _) in enumerate(game.deals) if texts[actor] == hand]
    if not deals:
        return {'status': 'invalid_probe'}
    progress('train'); start = time.perf_counter()
    try:
        policy = game.train(iterations, method='cfr_plus_native')
    except (RuntimeError, OSError):
        return {'status': 'provider_unavailable'}
    train = time.perf_counter() - start
    progress('measure'); start = time.perf_counter()
    metrics = game.measure(policy)
    values = action_values(game, policy, hand)
    values['actor_id'] = request['snapshot']['actor_id']
    return {'status': 'completed', 'iterations': iterations, 'provenance': contract.provenance(),
            'value_provenance': value_provenance(), 'request_key': digest(request), 'metadata': metadata,
            'tree': {'bet_sizes': list(game.bet_sizes), 'raise_sizes': list(game.raise_sizes),
                     'future_raise_cap': game.max_raises, 'min_bet': game.min_bet,
                     'max_nodes': request['input'].get('max_nodes', 20000), 'public_nodes': len(game.nodes),
                     'joint_deals': len(game.deals), 'max_joint_combos': game.max_joint_combos},
            'metrics': metrics, 'build_seconds': build, 'train_seconds': train,
            'measure_seconds': time.perf_counter() - start, 'peak_rss_mib': peak_rss_mib(),
            'candidate': {'actor_id': request['snapshot']['actor_id'], 'own_hand': hand,
                          'actions': list(game.root.actions), 'probabilities': policy[(actor, hand, game.root.history)],
                          'compatible_deals': len(deals), 'conditional_mass': sum(w for _, w in deals)},
            'action_values': values}


def admit(result, raw, request, limits):
    """Lesson extension admission using the frozen contract's validators and gate."""
    def refuse(status, code):
        return contract.finish(result, status, code, 'Lesson calculation was not admitted.', 'lesson_admission')
    if type(raw) is not dict:
        return refuse('error', 'WORKER_FAILED')
    result['timing'] = {k: raw.get(k) if contract.finite_number(raw.get(k)) else None for k in
                        ('wall_seconds', 'sampled_peak_rss_mib', 'peak_rss_mib', 'build_seconds', 'train_seconds', 'measure_seconds')}
    failures = {'cancelled': ('cancelled', 'ANALYSIS_CANCELLED'),
                'timed_out': ('budget_exceeded', 'TIME_BUDGET_EXCEEDED'),
                'memory_exceeded': ('budget_exceeded', 'MEMORY_BUDGET_EXCEEDED'),
                'rejected': ('unsupported', 'UNSUPPORTED_STATE_OR_TREE'),
                'provider_unavailable': ('unavailable', 'NATIVE_KERNEL_UNAVAILABLE'),
                'invalid_probe': ('unsupported', 'UNSUPPORTED_OWN_HAND')}
    if raw.get('status') in failures:
        return refuse(*failures[raw['status']])
    if raw.get('status') != 'completed':
        return refuse('error', 'WORKER_FAILED')
    try:
        json.dumps(raw, allow_nan=False)
    except (TypeError, ValueError):
        return refuse('error', 'INVALID_WORKER_EVIDENCE')
    wall, peak, sampled = (raw.get(k) for k in ('wall_seconds', 'peak_rss_mib', 'sampled_peak_rss_mib'))
    if any(not contract.finite_number(v) or v < 0 for v in (wall, peak, sampled)):
        return refuse('error', 'MISSING_RESOURCE_EVIDENCE')
    if wall > limits.wall_seconds:
        return refuse('budget_exceeded', 'TIME_BUDGET_EXCEEDED')
    if max(peak, sampled) > limits.memory_mib:
        return refuse('budget_exceeded', 'MEMORY_BUDGET_EXCEEDED')
    metadata = raw.get('metadata')
    if (raw.get('provenance') != result['provenance'] or raw.get('value_provenance') != value_provenance() or
            raw.get('request_key') != result['request_key'] or raw.get('iterations') != limits.iterations or
            type(metadata) is not dict or metadata.get('source_information_key') != result['source_information_key']):
        return refuse('error', 'RESULT_IDENTITY_MISMATCH')
    if not contract.valid_tree(raw.get('tree'), request):
        return refuse('error', 'INVALID_TREE_EVIDENCE')
    metrics = raw.get('metrics'); task = metadata.get('task_key')
    if (not contract.valid_quality(metrics, len(request['snapshot']['players']), request['snapshot']['pot']) or
            type(task) is not str or not re.fullmatch('[0-9a-f]{64}', task)):
        return refuse('error', 'INVALID_QUALITY_EVIDENCE')
    result['model'] = {**metadata, 'tree': raw['tree']}; result['task_key'] = task
    gap = metrics['max_unilateral_gain_pct_pot']
    result['quality'] = {'value': gap, 'gate': limits.quality_gate_pct_pot,
                         'passed': gap <= limits.quality_gate_pct_pot,
                         'metric': 'max_unilateral_gain_pct_decision_pot', 'evidence': metrics}
    if gap > limits.quality_gate_pct_pot:
        return refuse('quality_rejected', 'QUALITY_GATE_FAILED')
    candidate = raw.get('candidate')
    if not contract.valid_candidate(candidate, request):
        return refuse('error', 'INVALID_CANDIDATE')
    if not valid_values(raw.get('action_values'), candidate, request):
        return refuse('error', 'INVALID_ACTION_VALUES')
    result.update(action_values=raw['action_values'], value_provenance=raw['value_provenance'])
    return contract.finish(result, 'ready', None, None, 'lesson_admission', candidate)


def analyze(request, limits=None, *, cancel_event=None):
    limits = contract.ResearchLimits() if limits is None else limits
    if not isinstance(limits, contract.ResearchLimits):
        raise ValueError('ResearchLimits required.')
    result = {'contract_version': contract.CONTRACT_VERSION, 'scope': 'offline_bounded_river',
              'provenance': contract.provenance(), 'request_key': None, 'source_information_key': None,
              'task_key': None, 'limits': asdict(limits), 'timing': None, 'quality': None, 'model': None}
    try:
        contract.validate_request(request)
    except (ValueError, TypeError, KeyError):
        return contract.finish(result, 'invalid_input', 'INVALID_PUBLIC_REQUEST', 'Invalid public model.', 'preflight')
    result.update(request_key=digest(request), source_information_key=request['snapshot']['information_key'])
    snapshot = request['snapshot']
    if snapshot['schema_version'] != 1 or snapshot['street'] != 'river' or snapshot['range_model'] != contract.RANGE_VERSION or not 2 <= len(snapshot['players']) <= 6:
        return contract.finish(result, 'unsupported', 'UNSUPPORTED_MODEL', 'River model required.', 'preflight')
    try:
        raw = run_guarded(request, limits.iterations, limits.wall_seconds, limits.memory_mib,
                          method='cfr_plus_native', worker_module='research.lesson_values', cancel_event=cancel_event)
    except (OSError, ValueError, TypeError):
        return contract.finish(result, 'error', 'RUNNER_FAILED', 'Isolated runner unavailable.', 'worker')
    if cancel_event is not None and cancel_event.is_set():
        return contract.finish(result, 'cancelled', 'ANALYSIS_CANCELLED', 'Calculation cancelled.', 'admission')
    return admit(result, raw, request, limits)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true', required=True)
    parser.add_argument('--method', choices=['cfr_plus_native'], default='cfr_plus_native')
    parser.add_argument('--iterations', type=int, default=300)
    args = parser.parse_args()
    print(json.dumps(worker(json.load(sys.stdin), args.iterations)), flush=True)
