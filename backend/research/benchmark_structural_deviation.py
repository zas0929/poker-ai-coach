"""Paired comparison of frozen generic and public-tree signed bounds."""
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
from research.fixed_deviation import fit_responses, deal_payoffs
from research.independent_evaluation import payoff_bounds
from research.fused_best_response import evaluate_policy
from research.native_cfr import train_native
from research.structural_deviation import prepare_envelopes, evaluate_structural

SIZES = (512, 2048, 8192)
SEEDS = (1237, 3253, 5279)
COMPARISONS = 10 * 2 * len(SIZES) * len(SEEDS)
DELTA = .05 / (2 * COMPARISONS)


def evidence(draw):
    return {k: v for k, v in draw.items() if k != 'counts'}


def worker(case):
    def phase(name):
        print(json.dumps({'phase': name, 'observed_peak_rss_mib': peak_rss_mib()}), flush=True)
    phase('build')
    game = RiverGame(**{**case['input'], 'utility_storage': 'compact'})
    def draw(size, seed):
        return sample_joint_ranges(game.board, game.ranges, samples=size, seed=seed, max_attempts=size*100)
    training = draw(512, 11)
    view = SampleView(game, training)
    if view.missing_keys:
        return {'status': 'incomplete_training_coverage'}
    policies = {'exact_trained': train_native(game, 100), 'sample_trained': train_native(view, 100)}
    fit = draw(2048, 73)
    fitted = {name: fit_responses(game, policy, fit) for name, policy in policies.items()}
    generic = [hi-lo for lo, hi in payoff_bounds(game)]
    prepared = {name: prepare_envelopes(game, policy, fitted[name], generic) for name, policy in policies.items()}
    references = {}
    for name, policy in policies.items():
        optimal, _ = evaluate_policy(game, policy)
        values = deal_payoffs(game, policy, fitted[name]['responses'])
        differences = [sum(w*(dev[p]-base[p]) for (_, w, _), (base, dev) in zip(game.deals, values))
                       for p in range(game.n)]
        # Exhaustive reference audit only; never used to tune a bound or response.
        for base, dev in values:
            for p, row in enumerate(prepared[name]['players']):
                lo, hi = row['bounds_chips']
                if not lo-1e-8 <= dev[p]-base[p] <= hi+1e-8:
                    raise ValueError('Public envelope failed exact-deal audit; refuse result.')
        references[name] = {'optimal_metrics': optimal, 'fixed_differences_chips': differences,
            'public_envelopes': prepared[name]['players'],
            'policy_sha256': fitted[name]['policy_sha256'], 'response_sha256': fitted[name]['response_sha256']}
    rows = []
    for size in SIZES:
        for base_seed in SEEDS:
            seed = base_seed + 10*size
            phase(f'test_{size}_{seed}')
            test = draw(size, seed)
            if test['status'] != 'sampled':
                rows.append({'status': test['status'], 'sampling': evidence(test)})
                continue
            for name, policy in policies.items():
                result = evaluate_structural(game, policy, fitted[name], prepared[name], test, delta=DELTA)
                truth = references[name]['fixed_differences_chips']
                bad = references[name]['optimal_metrics']['max_unilateral_gain_pct_pot'] > .5
                def covered(field):
                    return all(row[field][0]-1e-9 <= actual <= row[field][1]+1e-9
                               for row, actual in zip(result['players'], truth))
                rows.append({'policy': name, 'sampling': evidence(test), **result,
                    'exact_original_above_threshold': bad,
                    'intervals_cover_truth': covered('interval_chips'),
                    'previous_intervals_cover_truth': covered('previous_interval_chips')})
    return {'status': 'completed', 'training': evidence(training), 'fit': evidence(fit),
            'policies': references, 'results': rows, 'peak_rss_mib': peak_rss_mib()}


def summarize(cases):
    summary = {}
    for size in SIZES:
        rows = [r for case in cases if case['status'] == 'completed' for r in case['results']
                if r['status'] == 'diagnostics_only' and r['sampling']['requested'] == size]
        summary[str(size)] = {
            'comparisons': len(rows),
            'previous_confirmed': sum(r['previous_confirms_above_threshold'] for r in rows),
            'structural_confirmed': sum(r['confirms_above_threshold'] for r in rows),
            'structural_false_accusations': sum(r['confirms_above_threshold'] and not r['exact_original_above_threshold'] for r in rows),
            'previous_cover_truth': sum(r['previous_intervals_cover_truth'] for r in rows),
            'structural_cover_truth': sum(r['intervals_cover_truth'] for r in rows),
            'narrower_intervals': sum(p['interval_chips'][1]-p['interval_chips'][0] < p['previous_interval_chips'][1]-p['previous_interval_chips'][0]-1e-9
                                     for r in rows for p in r['players']),
            'player_comparisons': sum(len(r['players']) for r in rows)}
    return summary


def benchmark():
    cases = []
    for case in scenarios():
        print(case['name'], file=sys.stderr, flush=True)
        cases.append({'case': case, **run_guarded(case, 100, 45, 128,
            worker_module='research.benchmark_structural_deviation', method='cfr_plus_native')})
    sources = ('structural_deviation.py', 'benchmark_structural_deviation.py', 'fixed_deviation.py',
        'independent_evaluation.py', 'deal_sampling.py', 'benchmark_deal_sampling.py',
        'fused_best_response.py', 'custom_river.py', 'native_cfr.py', 'benchmark_expanded.py')
    return {'scope': 'Same frozen candidate-fitting rule on ten KNOWN small river games, new test seeds. Public structural envelopes audited against all reference deals. Generic reference spans still require full small game. Lower diagnostic only; no quality pass or live change.',
        'plan': {'training_samples': 512, 'training_seed': 11, 'iterations': 100,
            'fit_samples': 2048, 'fit_seed': 73, 'test_sizes': SIZES,
            'test_base_seeds': SEEDS, 'test_seed_rule': 'base_seed + 10*size',
            'comparisons': COMPARISONS, 'interval_families': 2*COMPARISONS,
            'per_method_delta': DELTA, 'family_delta': .05, 'wall_seconds_per_case': 45, 'memory_mib': 128},
        'source_sha256': {p: sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in sources},
        'summary': summarize(cases), 'cases': cases}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--iterations', type=int, default=100)
    parser.add_argument('--method', default='cfr_plus_native')
    args = parser.parse_args()
    print(json.dumps(worker(json.load(sys.stdin)) if args.worker else benchmark(),
                     indent=None if args.worker else 2, allow_nan=False))
