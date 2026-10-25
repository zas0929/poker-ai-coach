"""Small, conservative postflop rules. Thresholds are presets, not solved EV."""
from collections import Counter
from math import ceil
from app.models.poker import Card, Rank, Suit
from app.services.betting_rules import betting_options, highest_bet
from app.services.hand_evaluator import RANK_VALUES


def classify(hole, board, evaluator, strength=None):
    strength = strength or evaluator.evaluate([*hole, *board])
    values = [RANK_VALUES[c.rank] for c in board]
    own = [RANK_VALUES[c.rank] for c in hole]
    counts = Counter(values)
    if len(board) == 5 and evaluator.score(board) == evaluator.score([*hole, *board]):
        label = 'Board-only hand'
    elif strength.rank == 1:
        if own[0] == own[1]:
            label = 'Overpair' if own[0] > max(values) else 'Underpair' if own[0] < min(values) else 'Middle pocket pair'
        else:
            matched = [v for v in own if v in values]
            if not matched: label = 'Pair on the board'
            elif max(matched) == max(values):
                kicker = next((v for v in own if v != max(matched)), 0)
                label = 'Top pair, good kicker' if kicker >= 10 else 'Top pair, weak kicker'
            else: label = 'Middle pair' if max(matched) > min(values) else 'Bottom pair'
    elif strength.rank == 2:
        label = 'Two pair' if len(set(own) & set(values)) == 2 else 'Two pair with a board pair'
    elif strength.rank == 3:
        label = 'Set' if own[0] == own[1] and counts[own[0]] == 1 else 'Trips' if any(counts[v] == 2 for v in own) else 'Trips on the board'
    else:
        label = {0:'High card',4:'Straight',5:'Flush',6:'Full house',7:'Four of a kind',8:'Straight flush'}[strength.rank]
    suits = Counter(c.suit for c in board)
    unique = set(values)
    if 14 in unique: unique.add(1)
    connected = any(len(unique & set(range(start,start+5))) >= 3 for start in range(1,11))
    four_connected = any(len(unique & set(range(start,start+5))) >= 4 for start in range(1,11))
    texture = []
    if max(counts.values()) >= 2: texture.append('Paired board')
    if max(suits.values()) >= 3: texture.append('Flush possible')
    elif max(suits.values()) == 2 and len(board) < 5: texture.append('Two-tone board')
    if connected: texture.append('Connected board')
    if not texture: texture.append('Dry board')
    return label, texture, max(suits.values()) >= 4 or four_connected


def draw_completions(hole, board, evaluator, strength=None):
    """Distinct next cards making a hole-card-supported straight/flush, not winning outs."""
    strength = strength or evaluator.evaluate([*hole, *board])
    if len(board) not in (3, 4) or strength.rank >= 4:
        return {'outs': 0, 'draws': [], 'next_card_probability': 0.0}
    known = {(c.rank, c.suit) for c in [*hole, *board]}
    completions = set()
    kinds = set()
    for rank in Rank:
        for suit in Suit:
            if (rank, suit) in known:
                continue
            card = Card(rank=rank, suit=suit)
            score = evaluator.score([*hole, *board, card])
            if score[0] not in (4, 5, 8):
                continue
            if len(board) == 4 and evaluator.score([*board, card]) >= score:
                continue  # A draw completing only on the board is not our draw.
            completions.add((rank, suit))
            kinds.add('flush draw' if score[0] in (5, 8) else 'straight draw')
    return {'outs': len(completions), 'draws': sorted(kinds),
            'next_card_probability': len(completions) / (52 - len(known))}


def postflop_context(state, player, opponents):
    # Postflop order starts after the button. All-in players no longer act.
    ids = [p.id for p in state.players]
    button = ids.index(state.dealer_player_id)
    order = ids[button + 1:] + ids[:button + 1]
    can_act = {p.id for p in opponents if p.stack > 0}
    acting = [pid for pid in order if pid in can_act or pid == player.id]
    in_position = bool(can_act) and acting[-1] == player.id
    effective = max((min(player.stack, p.stack) for p in opponents), default=0)
    prior = [a for a in state.history if a.street.value in ('preflop', 'flop', 'turn')
             and a.street != state.street and a.action in ('bet', 'raise')]
    aggressor = prior[-1].player_id if prior else None
    if aggressor not in {player.id, *(p.id for p in opponents)}:
        aggressor = None
    street_actions = [a for a in state.history if a.street == state.street]
    return {'position_label': 'In position' if in_position else 'Out of position',
            'effective_stack': effective,
            'stack_to_pot': round(effective / max(1, state.pot), 2),
            'previous_aggressor': aggressor,
            'facing_raise': any(a.action == 'raise' for a in street_actions),
            'in_position': in_position}


def advice_size(state, player, action, fraction):
    options = betting_options(state, player.id)
    if action not in options.legal_actions:
        return None
    if action == 'bet':
        target, minimum = ceil(state.pot * fraction), options.min_bet
    elif action == 'raise':
        target = highest_bet(state) + ceil((state.pot + options.call_amount) * fraction)
        minimum = options.min_raise_to
    else:
        return None
    contestable = max((p.stack + p.current_bet for p in state.players
                       if p.id != player.id and p.status.value != 'folded'), default=0)
    return min(options.max_raise_to, max(minimum, min(target, contestable)))


def advise(state, player, equity, required, call, evaluator, strength=None):
    if len(state.board) < 3:
        return None
    strength = strength or evaluator.evaluate([*player.cards, *state.board])
    label, texture, dangerous = classify(player.cards, state.board, evaluator, strength)
    opponents = [p for p in state.players if p.id != player.id and p.status.value != 'folded']
    multiway = len(opponents) > 1
    context = postflop_context(state, player, opponents)
    draw = draw_completions(player.cards, state.board, evaluator, strength)
    context.update(draw)
    strong = label in {'Two pair','Set','Trips','Straight','Flush','Full house','Four of a kind','Straight flush'}
    premium = label in {'Full house','Four of a kind','Straight flush'}
    pair = strength.rank == 1
    pair_value = label in {'Overpair','Top pair, good kicker'} and not multiway and not dangerous
    wet = any(t in texture for t in ('Two-tone board', 'Connected board', 'Flush possible'))
    pair_threshold = .62 if context['in_position'] else .68
    value = (strong and equity >= (.75 if multiway else .62) and (not dangerous or premium)) or (pair_value and equity >= pair_threshold)
    # Equity estimates reach showdown; marginal hands may have to pay again before then.
    all_in_call = bool(call) and (call >= player.stack or all(p.stack == 0 for p in opponents))
    margin = 0.0 if all_in_call else (.03 if multiway else 0) + (.03 if not context['in_position'] else 0)
    if not all_in_call and pair and (context['facing_raise'] or (state.street.value in ('turn', 'river') and call >= state.pot / 3)):
        margin += .08
    threshold = min(1.0, required + margin)
    context['call_equity_threshold'] = threshold
    fraction = .75 if strong and wet else 2/3 if strong else .5 if wet else 1/3
    if call:
        if value and equity >= (.85 if multiway else .75) and (not context['facing_raise'] or (premium and equity >= .9)):
            action, purpose, reason = 'raise','Value','A strong made hand and the equity estimate support a cautious value raise.'
        elif equity < threshold:
            action, purpose, reason = 'fold','Avoid an expensive call','The call does not clear the contextual threshold after position and betting pressure guards.'
        elif draw['outs'] and strength.rank == 0 and not all_in_call and draw['next_card_probability'] < required:
            action, purpose, reason = 'fold','Avoid chasing a draw','The draw alone does not justify this price for one card. Future winnings and a free river are not assumed.'
        else:
            action, purpose, reason = 'call','Continue at the offered price','Equity clears the contextual call threshold; this does not establish a profitable raise.'
    elif value:
        if pair and not context['in_position'] and context['previous_aggressor'] not in (None, player.id):
            action, purpose, reason = 'check','Control the pot','Out of position against the previous aggressor, keep this one-pair hand in the checking range.'
        else:
            action, purpose, reason = 'bet','Value','The made hand supports a value bet. The size reflects board texture and hand class, not solved opponent responses.'
    else:
        action, purpose, reason = 'check','Control the pot','Check: the rules do not establish enough value from weaker calls to justify a bet.'
    if action == 'check' and draw['outs'] and strength.rank == 0:
        reason = 'Take the free card with this draw; fold equity has not been established for a semi-bluff.'
    if action == 'bet' and strong and equity >= .85 and not dangerous and 0 < context['stack_to_pot'] <= 1:
        fraction = context['effective_stack'] / max(1, state.pot)
        purpose = 'Value with a short effective stack'
        reason = 'With a strong made hand and a short effective stack, size the value bet to the remaining contestable stack.'
    context['size_fraction'] = fraction if action in ('bet', 'raise') else None
    return {'version':'postflop_rules_v2','action':action,'amount':advice_size(state, player, action, fraction),
            'hand_label':label,'board_texture':texture,'purpose':purpose,'reason':reason,
            'live_opponents':len(opponents),'context':context,
            'close_price':bool(call and abs(equity-threshold)<.03),
            'limitations':'Educational postflop rules, not GTO or action EV. Draw completions are not guaranteed winning outs; opponent responses and future payments are not solved.'}
