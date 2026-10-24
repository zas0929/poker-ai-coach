"""Independent fixed-policy sample diagnostics against bounded river references.

The confidence calculation assumes IID accepted deals and a policy fixed before
seeing the evaluation sample. Independence is a caller obligation, not something
that can be inferred from the supplied policy or a different RNG seed.
"""
import math

from research.deal_sampling import SampleView
from research.fused_best_response import evaluate_policy


def payoff_bounds(game):
    """Exact terminal envelopes; still depends on the full small reference game."""
    lower = [math.inf] * game.n
    upper = [-math.inf] * game.n
    for key in game.utilities:
        for p, value in enumerate(game.utilities[key]):
            lower[p] = min(lower[p], value)
            upper[p] = max(upper[p], value)
    if any(not math.isfinite(v) for v in lower + upper):
        raise ValueError('Finite nonempty terminal payoffs required.')
    return list(zip(lower, upper))


def confidence_envelope(game, metrics, samples, delta, bounds):
    """Simultaneous two-sided Hoeffding bounds for values and pure-response max.

    Each responder has K = product(action counts at all own information sets)
    pure policies. A union bound over them controls choosing a best response on
    the same evaluation sample. No pure policies need to be enumerated.
    """
    if type(samples) is not int or samples < 1:
        raise ValueError('Positive integer sample count required.')
    if type(delta) not in (float, int) or not math.isfinite(delta) or not 0 < delta < 1:
        raise ValueError('Delta must lie strictly between zero and one.')
    log_tail = math.log(4 * game.n / delta)
    rows = []
    for p, (lo, hi) in enumerate(bounds):
        span = hi - lo
        log_count = math.fsum(math.log(c) for key, c in game.action_counts.items() if key[0] == p)
        value_radius = span * math.sqrt(log_tail / (2 * samples))
        response_radius = span * math.sqrt((log_count + log_tail) / (2 * samples))
        value = metrics['policy_payoffs'][p]
        response = metrics['best_response_payoffs'][p]
        value_interval = [max(lo, value - value_radius), min(hi, value + value_radius)]
        response_interval = [max(lo, response - response_radius), min(hi, response + response_radius)]
        rows.append({
            'payoff_bounds': [lo, hi], 'log_pure_response_count': log_count,
            'policy_radius_chips': value_radius, 'response_radius_chips': response_radius,
            'policy_interval_chips': value_interval,
            'response_interval_chips': response_interval,
            'gain_interval_chips': [max(0., response_interval[0] - value_interval[1]),
                                    max(0., response_interval[1] - value_interval[0])],
        })
    upper_pct = max(row['gain_interval_chips'][1] for row in rows) / game.decision_pot * 100
    return {'delta': delta, 'players': rows, 'max_gain_upper_pct_pot': upper_pct,
            'research_bound_passed': upper_pct <= .5, 'live_advice_allowed': False}


def evaluate_independent(game, policy, draw, *, delta):
    if set(policy) != game.keys or any(
        len(row) != game.action_counts[key] or
        any(not math.isfinite(p) or not 0 <= p <= 1 for p in row) or abs(sum(row) - 1) > 1e-8
        for key, row in policy.items()
    ):
        raise ValueError('Complete fixed original-game policy required; no coverage repair.')
    view = SampleView(game, draw)
    projected = {key: policy[key] for key in view.keys}
    metrics, _ = evaluate_policy(view, projected)
    envelope = confidence_envelope(game, metrics, draw['requested'], delta, payoff_bounds(game))
    return {
        'status': 'diagnostics_only', 'metrics': metrics, 'confidence': envelope,
        'evaluation_missing_rows': len(view.missing_keys), 'unique_deals': len(view.deals),
        'live_advice_allowed': False,
    }
