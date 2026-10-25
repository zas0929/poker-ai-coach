"""Small, conservative postflop rules. Thresholds are presets, not solved EV."""
from collections import Counter
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


def advise(state, player, equity, required, call, evaluator, strength=None):
    if len(state.board) < 3: return None  # Preflop needs its own position/range presets.
    label, texture, dangerous = classify(player.cards, state.board, evaluator, strength)
    opponents = [p for p in state.players if p.id != player.id and p.status.value != 'folded']
    multiway = len(opponents) > 1
    strong = label in {'Two pair','Set','Trips','Straight','Flush','Full house','Four of a kind','Straight flush'}
    premium = label in {'Full house','Four of a kind','Straight flush'}
    pair_value = label in {'Overpair','Top pair, good kicker'} and not multiway and not dangerous
    pressure = any(a.street == state.street and a.action == 'raise' for a in state.history)
    value = (strong and equity >= (.75 if multiway else .62) and (not dangerous or premium)) or (pair_value and equity >= .62)
    if call:
        if value and equity >= (.85 if multiway else .75) and (not pressure or (premium and equity >= .9)):
            action, purpose, reason = 'raise','Value','A strong made hand and the equity estimate support a cautious value raise.'
        elif equity >= required:
            action, purpose, reason = 'call','Continue at the offered price','Equity clears the call threshold, but a profitable raise has not been established.'
        else:
            action, purpose, reason = 'fold','Avoid an expensive call','Estimated equity is below the call threshold. Future winnings are not assumed.'
    elif value:
        action, purpose, reason = 'bet','Value','The made hand and equity estimate support a value bet; weaker calls remain an assumption.'
    else:
        action, purpose, reason = 'check','Control the pot','Check: the rules do not establish enough value from weaker calls to justify a bet.'
    return {'version':'postflop_rules_v1','action':action,'hand_label':label,'board_texture':texture,
            'purpose':purpose,'reason':reason,'live_opponents':len(opponents),
            'close_price':bool(call and abs(equity-required)<.03),
            'limitations':'Conservative rules, not a comparison of action EVs. Opponent responses are not solved.'}
