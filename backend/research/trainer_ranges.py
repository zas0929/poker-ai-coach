"""Public-only strength-stratified subsets, not a full-range approximation guarantee.

One uniformly selected combination per equal-count showdown-strength stratum.
Original heuristic combo weights are retained; there is no bucket-mass transfer,
no equity-equivalence claim and no conditioning opponents on the hero probe.
"""
import math
import random
from app.models.poker import Card, Rank, Suit
from app.services.hand_evaluator import HandEvaluator
from research.river_snapshot import combo_key

VERSION = 'strength_stratified_subsets_v1'
SUITS = {'s': Suit.SPADES, 'h': Suit.HEARTS, 'd': Suit.DIAMONDS, 'c': Suit.CLUBS}


def cards(text):
    return [Card(rank=Rank(text[i]), suit=SUITS[text[i+1]]) for i in range(0, len(text), 2)]


def select_ranges(snapshot, own_hand, *, trial=0, width=None):
    live = [p for p in snapshot['players'] if p['status'] != 'folded']
    if type(trial) is not int or not 0 <= trial < 1000:
        raise ValueError('A bounded reproducible trial index is required.')
    width = (8 if len(live) == 2 else 4 if len(live) == 3 else 2) if width is None else width
    if type(width) is not int or not 1 <= width <= 8 or width ** len(live) > 64:
        raise ValueError('At most eight combos per seat and 64 raw joint combinations.')
    board = cards(''.join(snapshot['board']))
    evaluator = HandEvaluator()
    # Same public board/range union is scored once, regardless of seats/weights.
    scores = {text: evaluator.score([*cards(text), *board])
              for text in {r['cards'] for p in live for r in p['range']}}
    selected, players, coverage = {}, [], []
    for p in snapshot['players']:
        view = {k: v for k, v in p.items() if k != 'range'}
        if p['status'] != 'folded':
            rows = sorted(p['range'], key=lambda r: (scores[r['cards']], combo_key(r['cards'])))
            count = min(width, len(rows))
            if not count or any(not math.isfinite(r['weight']) or r['weight'] <= 0 for r in rows):
                raise ValueError('Positive finite public combo weights required.')
            rng = random.Random(VERSION + snapshot['information_key'] + p['id'] + ':' + str(trial))
            picked = []
            for i in range(count):
                group = rows[i*len(rows)//count:(i+1)*len(rows)//count]
                chosen = rng.choice(group)
                # The known probe replaces only its own strength stratum.
                # Opponent seeds, groups and selections never read own_hand.
                if p['id'] == snapshot['actor_id']:
                    chosen = next((r for r in group if combo_key(r['cards']) == combo_key(own_hand)), chosen)
                picked.append(chosen)
            selected[p['id']] = [r['cards'] for r in picked]
            view['range'] = picked
            coverage.append({'player_id': p['id'], 'selected_combos': count,
                             'public_combos': len(rows),
                             'weight_share': sum(r['weight'] for r in picked) / sum(r['weight'] for r in rows)})
        players.append(view)
    if combo_key(own_hand) not in [combo_key(c) for c in selected[snapshot['actor_id']]]:
        raise ValueError('Own probe must belong to the public range.')
    return selected, players, coverage, {'version': VERSION, 'trial': trial,
        'combos_per_live_seat': width, 'raw_joint_combos': math.prod(map(len, selected.values())),
        'stratification': 'equal_count_showdown_strength', 'weights': 'original_public_combo_weights',
        'stability': 'not_checked', 'reliable_advice': False}
