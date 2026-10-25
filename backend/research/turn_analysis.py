"""Separate bounded current-turn contract; the frozen river contract is unchanged."""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sys
import time

from research import analysis_contract as base
from research.benchmark_capacity import peak_rss_mib
from research.benchmark_expanded import run_guarded
from research.lesson_values import VALUE_VERSION, valid_values
from research.river_snapshot import combo_key, digest
from research.turn_snapshot import build_turn_from_snapshot

CONTRACT_VERSION = 'bounded_current_turn_v1'
SCOPE = 'offline_bounded_current_turn'
finish = base.finish
recheck_decision = base.recheck_decision
TREE_FIELDS = {'turn_bet_sizes', 'turn_raise_sizes', 'turn_max_raises',
               'river_bet_sizes', 'river_raise_sizes', 'river_max_raises',
               'max_nodes', 'max_joint_combos', 'max_outcomes', 'max_work'}
FILES = ('turn_analysis.py', 'turn_snapshot.py', 'turn_reference.py', 'turn_native.py',
         'analysis_contract.py', 'lesson_values.py', 'river_replay.py', 'river_snapshot.py',
         'custom_river.py', 'compact_utilities.py', 'native_cfr.py', 'native/cfr.cpp',
         'benchmark_expanded.py', '../app/services/hand_evaluator.py',
         '../app/services/solver_snapshot.py', '../app/services/range_service.py')


def provenance():
    root = Path(__file__).parent
    return {'engine_version': CONTRACT_VERSION,
            'engine_source_sha256': digest({p: sha256((root/p).read_bytes()).hexdigest() for p in FILES}),
            'range_version': base.RANGE_VERSION, 'method': 'cfr_plus_native',
            'turn_adapter': 'turn-delayed-reveal-native-v2'}


def validate_request(request):
    # Exact public whitelist, with a separate turn-specific tree schema.
    if type(request) is not dict or type(request.get('input')) is not dict:
        raise ValueError('Explicit public turn request required.')
    base.validate_request({**request, 'input': {}})
    config = request['input']; snapshot = request['snapshot']
    if set(config) != TREE_FIELDS:
        raise ValueError('Complete explicit turn tree required.')
    if (snapshot['schema_version'] != 1 or snapshot['street'] != 'turn'
            or snapshot['range_model'] != base.RANGE_VERSION
            or snapshot['information_key'] != digest({k:v for k,v in snapshot.items() if k != 'information_key'})):
        raise ValueError('Current schema-v1 turn snapshot required.')
    for name in ('turn_bet_sizes', 'turn_raise_sizes', 'river_bet_sizes', 'river_raise_sizes'):
        sizes = config[name]
        if (type(sizes) is not list or len(sizes) > 2 or len(set(sizes)) != len(sizes)
                or any(type(v) is not int or not 1 <= v <= 10000 for v in sizes)):
            raise ValueError('Up to two explicit positive sizes required.')
    for name in ('turn_max_raises', 'river_max_raises'):
        if type(config[name]) is not int or not 0 <= config[name] <= 3:
            raise ValueError('Invalid per-street future raise cap.')
    for name, high in (('max_nodes', 4000), ('max_joint_combos', 64),
                       ('max_outcomes', 3072), ('max_work', 200000)):
        if type(config[name]) is not int or not 1 <= config[name] <= high:
            raise ValueError('Invalid bounded turn capacity.')
    if any(type(v) is not list or not v or len(v) > 2 for v in request['selected_hands'].values()):
        raise ValueError('One or two explicit combos per live seat required.')
    actor = snapshot['actor_id']
    if combo_key(request['own_hand']) not in [combo_key(v) for v in request['selected_hands'][actor]]:
        raise ValueError('Own probe must be selected.')
    json.dumps(request, allow_nan=False)


def expected_root_actions(request):
    """Check current legal labels by public replay; never build a future tree inline."""
    from research.river_replay import replay_river
    snapshot = request['snapshot']; players = snapshot['players']; ids = [p['id'] for p in players]
    stacks = tuple(p['stack'] + p['street_committed'] for p in players)
    cursor = replay_river(stacks, ids.index(snapshot['button_id']), snapshot['big_blind'],
                          tuple(i for i,p in enumerate(players) if p['status'] == 'folded'),
                          [(ids.index(a['player_id']),a['action'],a['amount_added'])
                           for a in snapshot['history'] if a['street'] == 'turn'])
    if (not cursor.pending or ids[cursor.pending[0]] != snapshot['actor_id']
            or cursor.invested != tuple(p['street_committed'] for p in players)):
        return []
    actor = cursor.pending[0]; current = cursor.current; config = request['input']
    actions = ['FOLD', 'CALL'] if current > cursor.invested[actor] else ['CHECK']
    funded = tuple(p for p in cursor.alive if cursor.invested[p] < stacks[p])
    reopened = cursor.acted[actor] is None or current - cursor.acted[actor] >= cursor.increment
    targets = (config['turn_bet_sizes'] if current == 0 else
               config['turn_raise_sizes'] if config['turn_max_raises'] and reopened else [])
    if len(funded) < 2:
        targets = []
    minimum = snapshot['big_blind'] if current == 0 else current + cursor.increment
    for total in sorted({min(v, stacks[actor]) for v in targets}):
        if total > current and (total >= minimum or total == stacks[actor]):
            actions.append(('BET ' if current == 0 else 'RAISE ') + str(total))
    return actions


def valid_candidate(candidate, request):
    if type(candidate) is not dict or set(candidate) != {
            'actor_id','own_hand','actions','probabilities','compatible_deals','conditional_mass'}:
        return False
    try:
        probabilities = candidate['probabilities']
        return (candidate['actor_id'] == request['snapshot']['actor_id']
                and candidate['own_hand'] == request['own_hand']
                and candidate['actions'] == expected_root_actions(request) and bool(candidate['actions'])
                and type(probabilities) is list and len(probabilities) == len(candidate['actions'])
                and all(base.finite_number(v) and 0 <= v <= 1 for v in probabilities)
                and abs(sum(probabilities) - 1) < 1e-8
                and type(candidate['compatible_deals']) is int
                and 1 <= candidate['compatible_deals'] <= math.prod(len(v) for v in request['selected_hands'].values())
                and base.finite_number(candidate['conditional_mass'])
                and 0 < candidate['conditional_mass'] <= 1 + 1e-8)
    except (ValueError, KeyError, TypeError, IndexError):
        return False


def valid_tree(tree, request):
    if type(tree) is not dict or set(tree) != TREE_FIELDS | {
            'min_bet', 'public_nodes', 'joint_private_deals', 'joint_river_outcomes'}:
        return False
    if any(tree[k] != v for k,v in request['input'].items()) or tree['min_bet'] != request['snapshot']['big_blind']:
        return False
    if any(type(tree[k]) is not int or tree[k] < 1 for k in
           ('public_nodes', 'joint_private_deals', 'joint_river_outcomes')):
        return False
    raw = math.prod(len(v) for v in request['selected_hands'].values())
    return (tree['public_nodes'] <= tree['max_nodes']
            and tree['joint_private_deals'] <= raw <= tree['max_joint_combos']
            and tree['joint_private_deals'] <= tree['joint_river_outcomes'] <= tree['max_outcomes']
            and tree['public_nodes'] * tree['joint_river_outcomes'] <= tree['max_work'])


def worker(request, iterations):
    def progress(phase):
        print(json.dumps({'phase': phase, 'observed_peak_rss_mib': peak_rss_mib()}), flush=True)
    try:
        validate_request(request); progress('build'); start = time.perf_counter()
        game, metadata = build_turn_from_snapshot(request['snapshot'], request['selected_hands'], **request['input'])
    except (ValueError, KeyError, TypeError, IndexError) as error:
        return {'status': 'model_budget_exceeded' if 'budget' in str(error).lower() else 'rejected'}
    build = time.perf_counter() - start
    if not any(hands[game.root.actor] == request['own_hand'] for hands,_,_,_ in game.outcomes):
        return {'status': 'invalid_probe'}
    try:
        progress('train'); start = time.perf_counter()
        policy = game.train(iterations, method='cfr_plus_native', max_visits=200000000)
    except (RuntimeError, OSError):
        return {'status': 'provider_unavailable'}
    except ValueError as error:
        return {'status': 'model_budget_exceeded' if 'budget' in str(error).lower() else 'rejected'}
    train = time.perf_counter() - start
    progress('measure'); start = time.perf_counter()
    metrics = game.measure(policy); own = request['own_hand']
    root = game.root_action_values(policy, own)
    compatible = {hands for hands, _, _, _ in game.outcomes if hands[game.root.actor] == own}
    candidate = {'actor_id': request['snapshot']['actor_id'], 'own_hand': own,
                 'actions': [row['action'] for row in root['actions']],
                 'probabilities': [row['probability'] for row in root['actions']],
                 'compatible_deals': len(compatible), 'conditional_mass': root['conditional_mass']}
    values = {'version': VALUE_VERSION, 'actor_id': candidate['actor_id'], 'own_hand': own,
              'actions': candidate['actions'], 'ev_chips': [r['ev_chips'] for r in root['actions']],
              'gap_to_best_chips': [r['gap_to_best_first_action_chips'] for r in root['actions']],
              'policy_ev_chips': root['policy_ev_chips'], 'sunk_chips': root['sunk_chips'],
              'continuation': 'fixed_learned_policy', 'baseline': 'current_decision',
              'compatible_deals': len(compatible), 'conditional_mass': root['conditional_mass']}
    return {'status': 'completed', 'iterations': iterations, 'provenance': provenance(),
            'request_key': digest(request), 'metadata': metadata,
            'tree': {**request['input'], 'min_bet': game.min_bet, 'public_nodes': len(game.nodes),
                     'joint_private_deals': game.joint_private_deals, 'joint_river_outcomes': len(game.outcomes)},
            'metrics': metrics, 'candidate': candidate, 'action_values': values,
            'build_seconds': build, 'train_seconds': train,
            'measure_seconds': time.perf_counter() - start, 'peak_rss_mib': peak_rss_mib()}


def admit(result, raw, request, limits):
    def refuse(status, code):
        return finish(result, status, code, 'Turn calculation was not admitted.', 'turn_admission')
    if type(raw) is not dict:
        return refuse('error', 'WORKER_FAILED')
    result['timing'] = {k: raw.get(k) if base.finite_number(raw.get(k)) else None for k in
                        ('wall_seconds','peak_rss_mib','sampled_peak_rss_mib','build_seconds','train_seconds','measure_seconds')}
    failures = {'invalid_probe': ('unsupported','UNSUPPORTED_OWN_HAND'),
                'model_budget_exceeded': ('budget_exceeded','MODEL_BUDGET_EXCEEDED'),
                'cancelled': ('cancelled','ANALYSIS_CANCELLED'),
                'timed_out': ('budget_exceeded','TIME_BUDGET_EXCEEDED'),
                'memory_exceeded': ('budget_exceeded','MEMORY_BUDGET_EXCEEDED'),
                'rejected': ('unsupported','UNSUPPORTED_STATE_OR_TREE'),
                'provider_unavailable': ('unavailable','NATIVE_KERNEL_UNAVAILABLE')}
    if raw.get('status') in failures:
        return refuse(*failures[raw['status']])
    if raw.get('status') != 'completed':
        return refuse('error', 'WORKER_FAILED')
    try:
        json.dumps(raw, allow_nan=False)
    except (TypeError, ValueError):
        return refuse('error', 'INVALID_WORKER_EVIDENCE')
    wall, peak, sampled = (raw.get(k) for k in ('wall_seconds','peak_rss_mib','sampled_peak_rss_mib'))
    if any(not base.finite_number(v) or v < 0 for v in (wall,peak,sampled)):
        return refuse('error', 'MISSING_RESOURCE_EVIDENCE')
    if wall > limits.wall_seconds:
        return refuse('budget_exceeded', 'TIME_BUDGET_EXCEEDED')
    if max(peak,sampled) > limits.memory_mib:
        return refuse('budget_exceeded', 'MEMORY_BUDGET_EXCEEDED')
    metadata = raw.get('metadata')
    if (raw.get('provenance') != provenance() or raw.get('request_key') != result['request_key']
            or raw.get('iterations') != limits.iterations or type(metadata) is not dict
            or metadata.get('source_information_key') != result['source_information_key']
            or metadata.get('model_version') != 'bounded-turn-reference-v2'
            or not re.fullmatch('[a-f0-9]{64}', str(metadata.get('task_key','')))):
        return refuse('error', 'RESULT_IDENTITY_MISMATCH')
    if not valid_tree(raw.get('tree'), request):
        return refuse('error', 'INVALID_TREE_EVIDENCE')
    metrics = raw.get('metrics')
    if not base.valid_quality(metrics, len(request['snapshot']['players']), request['snapshot']['pot']):
        return refuse('error', 'INVALID_QUALITY_EVIDENCE')
    result.update(model={**metadata, 'tree': raw['tree']}, task_key=metadata['task_key'])
    gap = metrics['max_unilateral_gain_pct_pot']
    result['quality'] = {'value': gap, 'gate': limits.quality_gate_pct_pot,
                         'passed': gap <= limits.quality_gate_pct_pot,
                         'metric': 'max_unilateral_gain_pct_decision_pot', 'evidence': metrics}
    if gap > limits.quality_gate_pct_pot:
        return refuse('quality_rejected', 'QUALITY_GATE_FAILED')
    candidate = raw.get('candidate')
    if not valid_candidate(candidate, request):
        return refuse('error', 'INVALID_CANDIDATE')
    if not valid_values(raw.get('action_values'), candidate, request):
        return refuse('error', 'INVALID_ACTION_VALUES')
    result['action_values'] = raw['action_values']
    return finish(result, 'ready', None, None, 'turn_admission', candidate)


def analyze(request, limits=None, *, cancel_event=None):
    limits = base.ResearchLimits() if limits is None else limits
    if not isinstance(limits, base.ResearchLimits):
        raise ValueError('ResearchLimits required.')
    result = {'contract_version': CONTRACT_VERSION, 'scope': SCOPE, 'provenance': provenance(),
              'request_key': None, 'source_information_key': None, 'task_key': None,
              'limits': asdict(limits), 'timing': None, 'quality': None, 'model': None}
    try:
        validate_request(request)
    except (ValueError, KeyError, TypeError, IndexError):
        return finish(result, 'invalid_input', 'INVALID_PUBLIC_REQUEST', 'Invalid public turn model.', 'preflight')
    result.update(request_key=digest(request), source_information_key=request['snapshot']['information_key'])
    try:
        raw = run_guarded(request, limits.iterations, limits.wall_seconds, limits.memory_mib,
                          method='cfr_plus_native', worker_module='research.turn_analysis', cancel_event=cancel_event)
    except (OSError, ValueError, TypeError):
        return finish(result, 'error', 'RUNNER_FAILED', 'Isolated runner unavailable.', 'worker')
    if cancel_event is not None and cancel_event.is_set():
        return finish(result, 'cancelled', 'ANALYSIS_CANCELLED', 'Calculation cancelled.', 'admission')
    return admit(result, raw, request, limits)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true', required=True)
    parser.add_argument('--method', choices=['cfr_plus_native'], default='cfr_plus_native')
    parser.add_argument('--iterations', type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(worker(json.load(sys.stdin), args.iterations)), flush=True)
