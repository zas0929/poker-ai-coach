"""Reproducible offline turn continuations with observed bets and future raises."""
import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

from research.benchmark_expanded import run_guarded
from research.custom_river import demo_ranges
from research.turn_native import ADAPTER_VERSION
from research.turn_reference import TurnGame


def scenarios():
    for n in range(2, 7):
        yield {
            'name': 'turn_bet_raise_capacity_' + str(n),
            'range_scope': 'one explicit hand per live seat; capacity control only',
            'input': {
                'board': ['2c', '4d', '7h', '9s'],
                'ranges': [r[:1] for r in demo_ranges(n)],
                'pot': 20*n, 'initial_contributions': [20]*n,
                'stacks': [8, 12, 16, 20, 24, 28][:n], 'min_bet': 5,
                'turn_actions': [[0, 'bet', 5]],
                'turn_bet_sizes': [5], 'turn_raise_sizes': [10], 'turn_max_raises': 1,
                'river_bet_sizes': [5], 'river_raise_sizes': [], 'river_max_raises': 0,
            },
        }
    yield {
        'name': 'turn_bet_raise_capacity_6_check_only_river',
        'range_scope': 'one hand per seat; explicit check-only river, not the rejected larger tree',
        'input': {
            'board': ['2c', '4d', '7h', '9s'],
            'ranges': [r[:1] for r in demo_ranges(6)],
            'pot': 120, 'initial_contributions': [20]*6,
            'stacks': [8, 12, 16, 20, 24, 28], 'min_bet': 5,
            'turn_actions': [[0, 'bet', 5]],
            'turn_bet_sizes': [5], 'turn_raise_sizes': [10], 'turn_max_raises': 1,
            'river_bet_sizes': [], 'river_raise_sizes': [], 'river_max_raises': 0,
        },
    }
    yield {
        'name': 'turn_observed_raise_private_uncertainty_2',
        'range_scope': 'two hands per seat; four compatible private deals',
        'input': {
            'board': ['2c', '4d', '7h', '9s'], 'ranges': demo_ranges(2),
            'pot': 40, 'initial_contributions': [20, 20], 'stacks': [30, 30],
            'min_bet': 5, 'turn_actions': [[0, 'bet', 5], [1, 'raise', 10]],
            'turn_bet_sizes': [5], 'turn_raise_sizes': [20], 'turn_max_raises': 1,
            'river_bet_sizes': [5], 'river_raise_sizes': [10], 'river_max_raises': 1,
        },
    }


def benchmark(iterations=60, timeout_seconds=45, memory_mib=256):
    rows = []
    for case in scenarios():
        print('Starting ' + case['name'], file=sys.stderr, flush=True)
        result = run_guarded(
            case, iterations, timeout_seconds, memory_mib,
            method='cfr_plus_native', worker_module='research.benchmark_turn',
        )
        rows.append({**case, **result})
        print(case['name'] + ': ' + result['status'], file=sys.stderr, flush=True)
    source_files = (
        'turn_reference.py', 'turn_oracle.py', 'turn_native.py', 'turn_snapshot.py',
        'benchmark_turn.py', 'benchmark_turn_continuation.py', 'benchmark_expanded.py',
        'river_replay.py', 'custom_river.py', 'native_cfr.py', 'native/cfr.cpp',
        'compact_utilities.py',
    )
    return {
        'model_version': TurnGame.model_version, 'adapter_version': ADAPTER_VERSION,
        'iterations': iterations, 'timeout_seconds': timeout_seconds, 'memory_mib': memory_mib,
        'platform': platform.platform(), 'python': sys.version,
        'sources': {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                    for name in source_files},
        'scope': 'Synthetic continuation controls with observed turn actions and explicit '
                 'future sizes/caps. All compatible rivers enumerated. Five 2-6 seat '
                 'capacity controls have ONE hand per seat; only the separate heads-up '
                 'control has private uncertainty. No broad-range or server-speed claim. '
                 'Exact deviation metrics apply only to the stated bounded games. '
                 'Sampled RSS is a soft process budget, not an OS allocation limit.',
        'live_advice': False, 'production_ready': False, 'results': rows,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=60)
    parser.add_argument('--timeout-seconds', type=float, default=45)
    parser.add_argument('--memory-mib', type=float, default=256)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(args.iterations, args.timeout_seconds, args.memory_mib)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if any(row['status'] != 'completed' for row in report['results']):
        sys.exit(1)
