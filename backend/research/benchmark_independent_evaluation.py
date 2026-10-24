"""Fresh evaluation draws for frozen policies on ten known small reference games."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from research.benchmark_capacity import peak_rss_mib
from research.benchmark_deal_sampling import scenarios
from research.benchmark_expanded import run_guarded
from research.custom_river import RiverGame
from research.deal_sampling import SampleView, sample_joint_ranges
from research.fused_best_response import evaluate_policy
from research.independent_evaluation import evaluate_independent
from research.native_cfr import train_native

SIZES = (128, 512, 2048)
SEEDS = (1009, 2017, 3001)
EVALUATIONS = 10 * 2 * len(SIZES) * len(SEEDS)
DELTA = .05 / EVALUATIONS


def evidence(draw):
    return {key: value for key, value in draw.items() if key != 'counts'}


def worker(case):
    def phase(name):
        print(json.dumps({'phase': name, 'observed_peak_rss_mib': peak_rss_mib()}), flush=True)
    phase('build')
    game = RiverGame(**{**case['input'], 'utility_storage': 'compact'})
    training_draw = sample_joint_ranges(game.board, game.ranges, samples=512, seed=11, max_attempts=51200)
    training_view = SampleView(game, training_draw)
    if training_view.missing_keys:
        return {'status': 'incomplete_training_coverage', 'training': evidence(training_draw)}
    policies = {'exact_trained': train_native(game, 100), 'sample_trained': train_native(training_view, 100)}
    references = {name: evaluate_policy(game, policy)[0] for name, policy in policies.items()}
    rows = []
    for size in SIZES:
        for base_seed in SEEDS:
            seed = base_seed + 10 * size
            phase(f'evaluate_{size}_{seed}')
            draw = sample_joint_ranges(game.board, game.ranges, samples=size, seed=seed, max_attempts=size * 100)
            if draw['status'] != 'sampled':
                rows.append({'sampling': evidence(draw), 'status': draw['status']})
                continue
            for name, policy in policies.items():
                result = evaluate_independent(game, policy, draw, delta=DELTA)
                exact = references[name]
                empirical = result['metrics']
                bounds = result['confidence']['players']
                def covered(field, interval):
                    return all(lo - 1e-9 <= value <= hi + 1e-9
                               for value, (lo, hi) in zip(exact[field], (b[interval] for b in bounds)))
                rows.append({'policy': name, 'sampling': evidence(draw), **result,
                    'exact_metrics': exact,
                    'raw_quality_passed': empirical['max_unilateral_gain_pct_pot'] <= .5,
                    'exact_quality_passed': exact['max_unilateral_gain_pct_pot'] <= .5,
                    'policy_error_chips': [a-b for a,b in zip(empirical['policy_payoffs'], exact['policy_payoffs'])],
                    'response_error_chips': [a-b for a,b in zip(empirical['best_response_payoffs'], exact['best_response_payoffs'])],
                    'policy_intervals_cover': covered('policy_payoffs', 'policy_interval_chips'),
                    'response_intervals_cover': covered('best_response_payoffs', 'response_interval_chips'),
                    'gain_intervals_cover': covered('unilateral_gains', 'gain_interval_chips')})
    return {'status': 'completed', 'training': evidence(training_draw), 'results': rows,
            'legal_deals': len(game.deals), 'peak_rss_mib': peak_rss_mib()}


def summarize(cases):
    result = {}
    for size in SIZES:
        rows = [r for case in cases if case['status'] == 'completed' for r in case['results']
                if r['sampling']['requested'] == size and r['status'] == 'diagnostics_only']
        result[str(size)] = {
            'evaluations': len(rows), 'raw_pass': sum(r['raw_quality_passed'] for r in rows),
            'exact_pass': sum(r['exact_quality_passed'] for r in rows),
            'raw_pass_exact_fail': sum(r['raw_quality_passed'] and not r['exact_quality_passed'] for r in rows),
            'raw_fail_exact_pass': sum(not r['raw_quality_passed'] and r['exact_quality_passed'] for r in rows),
            'bound_pass': sum(r['confidence']['research_bound_passed'] for r in rows),
            'all_intervals_cover': sum(all(r[k] for k in ('policy_intervals_cover', 'response_intervals_cover', 'gain_intervals_cover')) for r in rows),
            'missing_evaluation_coverage': sum(r['evaluation_missing_rows'] > 0 for r in rows),
        }
    return result


def benchmark():
    cases = []
    for case in scenarios():
        print(case['name'], file=sys.stderr, flush=True)
        cases.append({'case': case, **run_guarded(case, 100, 45, 128,
            worker_module='research.benchmark_independent_evaluation', method='cfr_plus_native')})
    sources = ('independent_evaluation.py', 'benchmark_independent_evaluation.py',
               'deal_sampling.py', 'benchmark_deal_sampling.py', 'benchmark_expanded.py',
               'fused_best_response.py', 'custom_river.py', 'native_cfr.py')
    return {'scope': 'Fixed policies, fresh IID-model draws on ten KNOWN small exact games. No new-game holdout, MCCFR, live gate, or scalable full-range claim.',
        'evaluation_plan': {'sizes': SIZES, 'base_seeds': SEEDS, 'seed_rule': 'base_seed + 10 * size',
            'training_seed': 11, 'training_samples': 512, 'iterations': 100,
            'planned_evaluations': EVALUATIONS, 'per_evaluation_delta': DELTA, 'family_delta': .05,
            'wall_seconds_per_case': 45, 'memory_mib': 128},
        'source_sha256': {p: sha256((Path(__file__).parent / p).read_bytes()).hexdigest() for p in sources},
        'summary': summarize(cases), 'cases': cases}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--iterations', type=int, default=100)
    parser.add_argument('--method', default='cfr_plus_native')
    args = parser.parse_args()
    print(json.dumps(worker(json.load(sys.stdin)) if args.worker else benchmark(),
                     indent=None if args.worker else 2, allow_nan=False))
