"""Public-tree envelopes for a fixed river deviation; no hidden-deal enumeration.

At opponent nodes allow any action mixture; at own nodes propagate signed
response/profile reach to terminal payoff envelopes. This bounds a fixed
candidate, never the optimal response or overall strategy quality.
"""
import math

from research.deal_sampling import SampleView
from research.fixed_deviation import (validate_policy, validate_responses, policy_digest,
                                      deal_payoffs, paired_intervals)


def terminal_envelopes(game):
    """Rank-extreme settlement bounds, preserving refunds, side pots and odd chips.

    Uses public terminal state and settlement only; never game.deals/utilities.
    Giving one seat strictly highest/lowest score bounds every realizable rank.
    """
    result = {}
    for node in game.nodes:
        if node.actor != -1:
            continue
        rows = []
        for p in range(game.n):
            low_scores = [1] * game.n
            low_scores[p] = 0
            high_scores = [0] * game.n
            high_scores[p] = 1
            low = game.settle(node, low_scores)[0][p] - node.invested[p] - game.initial_contributions[p]
            high = game.settle(node, high_scores)[0][p] - node.invested[p] - game.initial_contributions[p]
            rows.append((low, high))
        result[id(node)] = rows
    if not result:
        raise ValueError('Public terminal nodes required.')
    return result


def response_envelopes(game, policy, responses, terminals=None):
    validate_policy(game, policy)
    validate_responses(game, responses)
    terminals = terminal_envelopes(game) if terminals is None else terminals
    rows = []
    for p in range(game.n):
        hands = sorted({key[1] for key in responses[p]})
        per_hand = {}
        for hand in hands:
            def visit(node, base_reach, response_reach):
                if node.actor == -1:
                    coefficient = response_reach - base_reach
                    lo, hi = terminals[id(node)][p]
                    return (coefficient * lo, coefficient * hi) if coefficient >= 0 else (coefficient * hi, coefficient * lo)
                if node.actor == p:
                    key = (p, hand, node.history)
                    children = [visit(child, base_reach * policy[key][a], response_reach * responses[p][key][a])
                                for a, child in enumerate(node.children)]
                    return math.fsum(c[0] for c in children), math.fsum(c[1] for c in children)
                # One shared opponent action distribution appears in both paths.
                # Its unknown probabilities form a convex combination, so min/max
                # over branches are safe without looking at opponent hole cards.
                children = [visit(child, base_reach, response_reach) for child in node.children]
                return min(c[0] for c in children), max(c[1] for c in children)
            per_hand[hand] = visit(game.root, 1., 1.)
        signed = [min(v[0] for v in per_hand.values()), max(v[1] for v in per_hand.values())] if hands else [0., 0.]
        rows.append({'bounds_chips': signed, 'own_hand_bounds': per_hand})
    return rows


def prepare_envelopes(game, policy, fitted, generic_spans):
    if fitted['game'] is not game or policy_digest(policy) != fitted['policy_sha256']:
        raise ValueError('Original fitted game/policy required.')
    if [policy_digest(r) for r in fitted['responses']] != fitted['response_sha256']:
        raise ValueError('Responses changed after fitting.')
    if len(generic_spans) != game.n or any(not math.isfinite(r) or r < 0 for r in generic_spans):
        raise ValueError('One valid generic payoff span per player required.')
    rows = response_envelopes(game, policy, fitted['responses'])
    for row, span in zip(rows, generic_spans):
        lo, hi = row['bounds_chips']
        lo, hi = max(lo, -span), min(hi, span)
        if lo > hi + 1e-8:
            raise ValueError('Inconsistent public and generic envelopes.')
        row['bounds_chips'] = [lo, hi]
        row['generic_span_chips'] = span
    return {'game': game, 'policy_sha256': fitted['policy_sha256'],
            'response_sha256': list(fitted['response_sha256']), 'players': rows}


def signed_intervals(values, counts, bounds, delta):
    spans = [max(abs(lo), abs(hi)) for lo, hi in bounds]
    if any(not math.isfinite(v) for pair in bounds for v in pair) or any(lo > hi for lo, hi in bounds):
        raise ValueError('Finite ordered signed envelopes required.')
    rows = paired_intervals(values, counts, spans, delta)
    n = sum(counts)
    players = len(bounds)
    for p, (row, (lo, hi)) in enumerate(zip(rows, bounds)):
        if any(not lo-1e-8 <= dev[p]-base[p] <= hi+1e-8 for base, dev in values):
            raise ValueError('Observed fixed deviation outside structural envelope.')
        width = hi-lo
        hoeffding = width * math.sqrt(math.log(4*players/delta) / (2*n))
        log_tail = math.log(8*players/delta)
        bernstein = math.sqrt(2*row['sample_variance']*log_tail/n) + 7*width*log_tail/(3*(n-1))
        radius = min(hoeffding, bernstein)
        mean = row['mean_difference_chips']
        # Numerical noise at a proved constant boundary must not invert an interval.
        center = min(hi, max(lo, mean))
        row.update(bounds_chips=[lo, hi], hoeffding_radius_chips=hoeffding,
                   bernstein_radius_chips=bernstein,
                   interval_chips=[max(lo, center-radius), min(hi, center+radius)])
    return rows


def evaluate_structural(game, policy, fitted, prepared, draw, *, delta):
    if (prepared['game'] is not game or fitted['game'] is not game or
        policy_digest(policy) != prepared['policy_sha256'] or
        prepared['policy_sha256'] != fitted['policy_sha256'] or
        [policy_digest(r) for r in fitted['responses']] != prepared['response_sha256']):
        raise ValueError('Frozen base policy, response and public envelopes required.')
    if draw['seed'] == fitted['fit_seed']:
        raise ValueError('Independent test sample required.')
    view = SampleView(game, draw)
    policy_view = {k: policy[k] for k in view.keys}
    responses = [{k: row for k, row in response.items() if k in view.keys} for response in fitted['responses']]
    values = deal_payoffs(view, policy_view, responses)
    counts = [draw['counts'][texts] for texts, _, _ in view.deals]
    old = paired_intervals(values, counts, [p['generic_span_chips'] for p in prepared['players']], delta)
    new = signed_intervals(values, counts, [p['bounds_chips'] for p in prepared['players']], delta)
    for previous, row in zip(old, new):
        row['previous_interval_chips'] = previous['interval_chips']
        row['interval_pct_pot'] = [v / game.decision_pot * 100 for v in row['interval_chips']]
        row['confirms_above_threshold'] = row['interval_pct_pot'][0] > .5
        row['previous_confirms_above_threshold'] = previous['interval_chips'][0] / game.decision_pot * 100 > .5
    return {'status': 'diagnostics_only', 'players': new, 'delta': delta,
            'confirms_above_threshold': any(p['confirms_above_threshold'] for p in new),
            'previous_confirms_above_threshold': any(p['previous_confirms_above_threshold'] for p in new),
            'quality_pass_allowed': False, 'live_advice_allowed': False}
