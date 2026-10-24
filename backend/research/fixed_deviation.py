"""Three-way fixed-deviation diagnostics for bounded river models; no advice gate.

Fit responses on one sample; freeze them before a separate paired test sample.
Variance-sensitive bounds use Maurer & Pontil (2009), Theorem 4:
https://www.cs.mcgill.ca/~colt2009/papers/012.pdf
IID sampling and independence from fitting are caller obligations.
"""
from hashlib import sha256
import json
import math

from research.deal_sampling import SampleView
from research.fused_best_response import evaluate_policy
from research.independent_evaluation import payoff_bounds


def policy_digest(policy):
    rows = [(key, policy[key]) for key in sorted(policy, key=str)]
    return sha256(json.dumps(rows, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_policy(game, policy):
    if set(policy) != game.keys or any(
        len(row) != game.action_counts[key] or
        any(not math.isfinite(p) or not 0 <= p <= 1 for p in row) or abs(sum(row) - 1) > 1e-8
        for key, row in policy.items()
    ):
        raise ValueError('Complete finite normalized original policy required.')


def validate_responses(game, responses):
    if len(responses) != game.n:
        raise ValueError('One fixed own-information response per seat required.')
    for p, response in enumerate(responses):
        own = {key for key in game.keys if key[0] == p}
        if set(response) != own or any(
            len(row) != game.action_counts[key] or
            any(not math.isfinite(v) or not 0 <= v <= 1 for v in row) or abs(sum(row) - 1) > 1e-8
            for key, row in response.items()
        ):
            raise ValueError('Responses must use complete own-information rows only.')


def fit_responses(game, policy, draw):
    validate_policy(game, policy)
    view = SampleView(game, draw)
    metrics, records = evaluate_policy(view, {key: policy[key] for key in view.keys})
    responses = [{key: list(row) for key, row in policy.items() if key[0] == p} for p in range(game.n)]
    for key, record in records.items():
        # q is already aggregated over hidden deals sharing the same own hand.
        # First action wins a tie. Unseen original rows retain the base policy.
        selected = max(range(len(record['q'])), key=record['q'].__getitem__)
        responses[key[0]][key] = [float(a == selected) for a in range(len(record['q']))]
    validate_responses(game, responses)
    return {'game': game, 'responses': responses,
            'policy_sha256': policy_digest(policy),
            'response_sha256': [policy_digest(row) for row in responses],
            'fit_seed': draw['seed'], 'fit_samples': draw['requested'],
            'fit_missing_rows': len(view.missing_keys), 'fit_metrics': metrics}


def deal_payoffs(game, policy, responses):
    """Integrate public actions exactly for each deal and each unilateral response.

    Every response changes only its own seat. No response maximization here.
    Output pairs retain common deals instead of subtracting independent samples.
    """
    validate_policy(game, policy)
    validate_responses(game, responses)
    result = []
    for d in range(len(game.deals)):
        def visit(node):
            if node.actor == -1:
                values = game.utilities[(id(node), d)]
                return values, values
            children = [visit(child) for child in node.children]
            key = game.key(node, d)
            base = policy[key]
            response = responses[node.actor][key]
            profile = [math.fsum(base[a] * child[0][p] for a, child in enumerate(children)) for p in range(game.n)]
            deviations = [math.fsum((response[a] if node.actor == p else base[a]) * child[1][p]
                                    for a, child in enumerate(children)) for p in range(game.n)]
            return profile, deviations
        result.append(visit(game.root))
    return result


def paired_intervals(values, counts, spans, delta):
    """Finite-sample intervals for SIGNED fixed deviations, not optimal BR gains.

    Each difference is in [-R, R], so its range width is 2R. Half the error
    budget funds Hoeffding, half funds two-sided empirical Bernstein; union
    over seats permits taking the tighter radius without post-hoc selection.
    """
    if (len(values) != len(counts) or not counts or
        any(type(c) is not int or c < 1 for c in counts) or sum(counts) < 2 or
        type(delta) not in (int, float) or not math.isfinite(delta) or not 0 < delta < 1):
        raise ValueError('Complete weighted sample with N >= 2 and finite delta required.')
    n = sum(counts)
    players = len(spans)
    if not players or any(not math.isfinite(r) or r < 0 for r in spans):
        raise ValueError('Finite nonnegative payoff spans required.')
    if any(len(base) != players or len(dev) != players or
           any(not math.isfinite(v) for v in [*base, *dev])
           for base, dev in values):
        raise ValueError('Finite paired values per player required.')
    rows = []
    for p, span in enumerate(spans):
        base = [pair[0][p] for pair in values]
        dev = [pair[1][p] for pair in values]
        difference = [b-a for a, b in zip(base, dev)]
        if any(abs(x) > span + 1e-8 for x in difference):
            raise ValueError('Difference exceeds terminal payoff span.')
        def moments(data):
            mean = math.fsum(c*x for c, x in zip(counts, data)) / n
            variance = math.fsum(c*(x-mean)**2 for c, x in zip(counts, data)) / (n-1)
            return mean, variance
        mean, variance = moments(difference)
        _, base_variance = moments(base)
        _, dev_variance = moments(dev)
        width = 2 * span
        hoeffding = width * math.sqrt(math.log(4 * players / delta) / (2 * n))
        log_tail = math.log(8 * players / delta)
        bernstein = math.sqrt(2 * variance * log_tail / n) + 7 * width * log_tail / (3 * (n-1))
        radius = min(hoeffding, bernstein)
        rows.append({'mean_difference_chips': mean, 'sample_variance': variance,
            'independent_difference_variance': base_variance + dev_variance,
            'hoeffding_radius_chips': hoeffding, 'bernstein_radius_chips': bernstein,
            'interval_chips': [max(-span, mean-radius), min(span, mean+radius)]})
    return rows


def evaluate_fixed_deviations(game, policy, fitted, draw, *, delta):
    if fitted['game'] is not game or policy_digest(policy) != fitted['policy_sha256']:
        raise ValueError('Base game/policy changed after fitting.')
    if [policy_digest(row) for row in fitted['responses']] != fitted['response_sha256']:
        raise ValueError('Fixed responses changed after fitting.')
    if draw['seed'] == fitted['fit_seed']:
        raise ValueError('Fit seed cannot be reused for testing; caller must ensure independence.')
    view = SampleView(game, draw)
    projected = {key: policy[key] for key in view.keys}
    responses = [{key: row for key, row in response.items() if key in view.keys}
                 for response in fitted['responses']]
    values = deal_payoffs(view, projected, responses)
    counts = [draw['counts'][texts] for texts, _, _ in view.deals]
    spans = [hi-lo for lo, hi in payoff_bounds(game)]
    rows = paired_intervals(values, counts, spans, delta)
    for row in rows:
        row['interval_pct_pot'] = [x / game.decision_pot * 100 for x in row['interval_chips']]
        row['confirms_above_threshold'] = row['interval_pct_pot'][0] > .5
    return {'status': 'diagnostics_only', 'delta': delta, 'players': rows,
            'confirms_above_threshold': any(row['confirms_above_threshold'] for row in rows),
            'evaluation_missing_rows': len(view.missing_keys), 'unique_deals': len(view.deals),
            'live_advice_allowed': False, 'quality_pass_allowed': False}
