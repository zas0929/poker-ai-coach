"""Isolated exact turn reference checks; no connection to gameplay or lesson API."""
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

from research.benchmark_capacity import peak_rss_mib
from research.benchmark_expanded import run_guarded
from research.custom_river import demo_ranges
from research.turn_reference import TurnGame


def scenarios():
    for n in range(2, 7):
        # Capacity controls deliberately use ONE hand per seat. They test genuine
        # multiway future betting/runouts, not uncertainty across a wide range.
        yield {'name': 'turn_capacity_' + str(n), 'range_scope': 'one explicit hand per seat',
               'input': {'board': ['2c', '4d', '7h', '9s'],
                         'ranges': [r[:1] for r in demo_ranges(n)], 'pot': 20*n,
                         'initial_contributions': [20]*n, 'stacks': [5, 10, 15, 20, 25, 30][:n],
                         'min_bet': 2, 'turn_bet_sizes': [10], 'river_bet_sizes': [10]}}
    yield {'name': 'turn_private_uncertainty_2', 'range_scope': 'two hands per seat, four joint private deals',
           'input': {'board': ['2c', '4d', '7h', '9s'], 'ranges': demo_ranges(2),
                     'pot': 40, 'initial_contributions': [20, 20], 'stacks': [20, 20],
                     'min_bet': 2, 'turn_bet_sizes': [10], 'river_bet_sizes': [10]}}


    for n in range(3, 7):
        yield {'name': 'turn_private_uncertainty_' + str(n),
               'range_scope': 'two hands per seat; shared alternate hand limits compatible lineups',
               'input': {'board': ['2c', '4d', '7h', '9s'],
                         'ranges': [[(r[0][0], 1), ('8c8d', 1)] for r in demo_ranges(n)],
                         'pot': 20*n, 'initial_contributions': [20]*n, 'stack': 2,
                         'min_bet': 2, 'turn_bet_sizes': [2], 'river_bet_sizes': [2]}}


def worker(case, iterations, method):
    if method not in ('cfr_plus', 'cfr_plus_native'):
        raise ValueError('Choose Python CFR+ or the turn-specific native adapter.')

    def progress(phase):
        print(json.dumps({'phase': phase, 'observed_peak_rss_mib': peak_rss_mib()}), flush=True)

    progress('build')
    start = time.perf_counter()
    try:
        game = TurnGame(**case['input'])
    except ValueError as error:
        return {'status': 'rejected', 'reason': str(error), 'peak_rss_mib': peak_rss_mib()}
    built = time.perf_counter() - start
    progress('measure_uniform')
    before = game.measure(game.uniform_policy())
    progress('train')
    start = time.perf_counter()
    try:
        policy = game.train(iterations, method=method,
                            max_visits=200000000 if method == 'cfr_plus_native' else 20000000)
    except ValueError as error:
        return {'status': 'rejected', 'reason': str(error), 'peak_rss_mib': peak_rss_mib()}
    trained = time.perf_counter() - start
    progress('measure_trained')
    start = time.perf_counter()
    metrics = game.measure(policy)
    measured = time.perf_counter() - start
    return {'status': 'completed', 'model_version': game.model_version,
            'iterations': iterations, 'method': method,
            'traversal_budget': 200000000 if method == 'cfr_plus_native' else 20000000, 'build_seconds': built, 'train_seconds': trained,
            'trained_measure_seconds': measured, 'peak_rss_mib': peak_rss_mib(),
            'public_nodes': len(game.nodes), 'joint_private_deals': game.joint_private_deals,
            'joint_hand_river_outcomes': len(game.outcomes), 'information_sets': len(game.keys),
            'uniform_metrics': before, 'metrics': metrics,
            'root_values': [game.root_action_values(policy, hand)
                            for hand, _ in game.ranges[game.root.actor]] if game.root.actor >= 0 else [],
            'live_advice': False, 'production_ready': False}


def benchmark(iterations=8, timeout_seconds=60, memory_mib=256, names=None, method='cfr_plus'):
    cases = list(scenarios())
    if names is not None:
        if not names or len(set(names)) != len(names) or set(names) - {c['name'] for c in cases}:
            raise ValueError('Select distinct known case names.')
        cases = [c for c in cases if c['name'] in names]
    rows = []
    for case in cases:
        print('Starting ' + case['name'], file=sys.stderr, flush=True)
        result = run_guarded(case, iterations, timeout_seconds, memory_mib, method=method,
                             worker_module='research.benchmark_turn')
        rows.append({**case, **result})
        print(case['name'] + ': ' + result['status'], file=sys.stderr, flush=True)
    source_hashes = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                     for name in ('turn_reference.py', 'turn_oracle.py', 'turn_native.py', 'benchmark_turn.py',
                                  'custom_river.py', 'native_cfr.py', 'native/cfr.cpp', 'compact_utilities.py')}
    return {'model_version': TurnGame.model_version, 'platform': platform.platform(),
            'python': sys.version, 'iterations': iterations, 'sources': source_hashes,
            'scope': 'Exact small turn/river games, opening bets only, no raises. Capacity controls '
                     'have one hand per seat; separate 2-6 seat controls have two hands each, '
                     'with strongly restricted compatible lineups at 3-6 seats. Measured deviations apply only to these bounded games. No production admission.',
            'results': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--method', choices=['cfr_plus', 'cfr_plus_native'], default='cfr_plus')
    parser.add_argument('--iterations', type=int, default=8)
    parser.add_argument('--timeout-seconds', type=float, default=60)
    parser.add_argument('--memory-mib', type=float, default=256)
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.load(sys.stdin), args.iterations, args.method)), flush=True)
    else:
        result = benchmark(args.iterations, args.timeout_seconds, args.memory_mib, args.cases, args.method)
        if args.output:
            args.output.write_text(json.dumps(result, indent=2) + '\n')
        else:
            print(json.dumps(result, indent=2))
        if any(row['status'] != 'completed' for row in result['results']):
            sys.exit(1)
