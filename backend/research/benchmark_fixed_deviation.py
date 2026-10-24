"""Fit a response independently; test its fixed deviation on a third sample."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from research.benchmark_capacity import peak_rss_mib
from research.benchmark_deal_sampling import scenarios
from research.benchmark_expanded import run_guarded
from research.custom_river import RiverGame
from research.deal_sampling import sample_joint_ranges, SampleView
from research.fixed_deviation import fit_responses, deal_payoffs, evaluate_fixed_deviations
from research.fused_best_response import evaluate_policy
from research.native_cfr import train_native

SIZES = (512, 2048, 8192)
BASE_SEEDS = (4001, 6007, 8009)
FIT_SEED = 73
FIT_SAMPLES = 2048
EVALUATIONS = 10 * 2 * len(SIZES) * len(BASE_SEEDS)
DELTA = .05 / EVALUATIONS


def evidence(draw):
    return {key: value for key, value in draw.items() if key != 'counts'}


def worker(case):
    def phase(name):
        print(json.dumps({'phase': name, 'observed_peak_rss_mib': peak_rss_mib()}), flush=True)
    def draw(samples, seed):
        return sample_joint_ranges(game.board, game.ranges, samples=samples, seed=seed,
                                   max_attempts=samples * 100)
    phase('build')
    game = RiverGame(**{**case['input'], 'utility_storage': 'compact'})
    training = draw(512, 11)
    training_view = SampleView(game, training)
    if training_view.missing_keys:
        return {'status': 'incomplete_training_coverage', 'training': evidence(training)}
    policies = {'exact_trained': train_native(game, 100), 'sample_trained': train_native(training_view, 100)}
    fit_draw = draw(FIT_SAMPLES, FIT_SEED)
    fitted = {name: fit_responses(game, policy, fit_draw) for name, policy in policies.items()}
    references = {}
    for name, policy in policies.items():
        exact, _ = evaluate_policy(game, policy)
        values = deal_payoffs(game, policy, fitted[name]['responses'])
        differences = [sum(w * (v[1][p]-v[0][p]) for (_, w, _), v in zip(game.deals, values))
                       for p in range(game.n)]
        if any(d > g + 1e-8 for d, g in zip(differences, exact['unilateral_gains'])):
            raise ValueError('A fixed legal response exceeded the exact best response.')
        references[name] = {'exact_optimal_metrics': exact, 'exact_fixed_differences_chips': differences,
            'exact_fixed_max_pct_pot': max(differences) / game.decision_pot * 100,
            **{key: value for key, value in fitted[name].items() if key not in ('game', 'responses')}}
    # Both base policies and all candidate responses are frozen before testing.
    rows = []
    for size in SIZES:
        for base_seed in BASE_SEEDS:
            seed = base_seed + 10 * size
            phase(f'test_{size}_{seed}')
            test_draw = draw(size, seed)
            if test_draw['status'] != 'sampled':
                rows.append({'status': test_draw['status'], 'sampling': evidence(test_draw)})
                continue
            for name, policy in policies.items():
                result = evaluate_fixed_deviations(game, policy, fitted[name], test_draw, delta=DELTA)
                reference = references[name]
                differences = reference['exact_fixed_differences_chips']
                original_bad = reference['exact_optimal_metrics']['max_unilateral_gain_pct_pot'] > .5
                fixed_bad = reference['exact_fixed_max_pct_pot'] > .5
                empirical_bad = max(r['mean_difference_chips'] for r in result['players']) / game.decision_pot * 100 > .5
                rows.append({'policy': name, 'sampling': evidence(test_draw), **result,
                    'exact_original_above_threshold': original_bad,
                    'exact_fixed_above_threshold': fixed_bad,
                    'point_estimate_above_threshold': empirical_bad,
                    'intervals_cover_fixed_truth': all(
                        r['interval_chips'][0]-1e-9 <= truth <= r['interval_chips'][1]+1e-9
                        for r, truth in zip(result['players'], differences)),
                    'errors_chips': [r['mean_difference_chips']-truth for r, truth in zip(result['players'], differences)]})
    return {'status': 'completed', 'training': evidence(training), 'fit_sampling': evidence(fit_draw),
            'policies': references, 'results': rows, 'legal_deals': len(game.deals), 'peak_rss_mib': peak_rss_mib()}


def summarize(cases):
    result = {}
    for size in SIZES:
        rows = [r for case in cases if case['status'] == 'completed' for r in case['results']
                if r['sampling']['requested'] == size and r['status'] == 'diagnostics_only']
        result[str(size)] = {
            'evaluations': len(rows),
            'exact_original_above_threshold': sum(r['exact_original_above_threshold'] for r in rows),
            'exact_fixed_above_threshold': sum(r['exact_fixed_above_threshold'] for r in rows),
            'point_above_threshold': sum(r['point_estimate_above_threshold'] for r in rows),
            'point_false_accusations': sum(r['point_estimate_above_threshold'] and not r['exact_original_above_threshold'] for r in rows),
            'confirmed_above_threshold': sum(r['confirms_above_threshold'] for r in rows),
            'confirmed_false_accusations': sum(r['confirms_above_threshold'] and not r['exact_original_above_threshold'] for r in rows),
            'intervals_cover_fixed_truth': sum(r['intervals_cover_fixed_truth'] for r in rows),
            'paired_variance_lower': sum(p['sample_variance'] < p['independent_difference_variance']
                                         for r in rows for p in r['players']),
            'player_comparisons': sum(len(r['players']) for r in rows),
        }
    return result


def benchmark():
    cases = []
    for case in scenarios():
        print(case['name'], file=sys.stderr, flush=True)
        cases.append({'case': case, **run_guarded(case, 100, 45, 128,
            worker_module='research.benchmark_fixed_deviation', method='cfr_plus_native')})
    sources = ('fixed_deviation.py', 'benchmark_fixed_deviation.py', 'independent_evaluation.py',
               'deal_sampling.py', 'benchmark_deal_sampling.py', 'benchmark_expanded.py',
               'fused_best_response.py', 'custom_river.py', 'native_cfr.py')
    return {'scope': 'Three separate data roles on ten KNOWN small river games. Fixed legal response evidence is a lower diagnostic, NEVER an optimal-BR upper certificate. No live gate or MCCFR.',
        'plan': {'training_samples': 512, 'training_seed': 11, 'iterations': 100,
                 'fit_samples': FIT_SAMPLES, 'fit_seed': FIT_SEED,
                 'test_sizes': SIZES, 'test_base_seeds': BASE_SEEDS,
                 'test_seed_rule': 'base_seed + 10 * size', 'planned_evaluations': EVALUATIONS,
                 'per_evaluation_delta': DELTA, 'family_delta': .05,
                 'wall_seconds_per_case': 45, 'memory_mib': 128,
                 'confidence_reference': 'Maurer & Pontil 2009 Theorem 4, https://www.cs.mcgill.ca/~colt2009/papers/012.pdf'},
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
