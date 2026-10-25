"""Exact bounded turn -> river reference, deliberately separate from river native ABI.

Chance is enumerated as joint (private hands, river) outcomes. A unary public
reveal node exposes that river only AFTER turn betting. Turn information sets
merge every indistinguishable outcome; river information sets include the card.
No sampling, actual archived future card, or independent per-river turn solves.
This first model starts at the beginning of the turn, with opening bets and no
raises on either street. It is an offline reference, not a production solver.
"""
import itertools
import math
import re
from dataclasses import dataclass

from app.services.hand_evaluator import HandEvaluator
from research.compact_utilities import CompactUtilities
from research.custom_river import RiverGame
from research.river_reference import cards

TERMINAL = -1
REVEAL = -2
DECK = tuple(rank + suit for rank in '23456789TJQKA' for suit in 'cdhs')


@dataclass
class TurnNode:
    actor: int
    street: str
    history: tuple
    actions: tuple = ()
    children: tuple = ()
    invested: tuple = ()  # Total new chips across BOTH modelled streets.
    alive: tuple = ()


class TurnGame:
    model_version = 'bounded-turn-reference-v1'

    def __init__(self, board, ranges, *, pot=100, stack=100, stacks=None,
                 initial_contributions=None, dealer=None, folded=(), min_bet=1,
                 turn_bet_sizes=(50,), river_bet_sizes=(50,), max_joint_combos=64,
                 max_nodes=20000, max_outcomes=4096, max_work=1000000):
        self.board = tuple(board)
        self.n = n = len(ranges)
        if (not 2 <= n <= 6 or len(board) != 4 or len(set(board)) != 4
                or any(not isinstance(c, str) or c not in DECK for c in board)):
            raise ValueError('Two to six seats and four distinct turn cards required.')
        for value, upper, label in ((pot, 10000, 'pot'), (min_bet, 10000, 'minimum bet'),
                                     (max_joint_combos, 4096, 'joint combo budget'),
                                     (max_nodes, 20000, 'node budget'),
                                     (max_outcomes, 4096, 'outcome budget'),
                                     (max_work, 2000000, 'node/outcome budget')):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError('Invalid ' + label + '.')
        self.pot = self.decision_pot = pot
        self.min_bet = min_bet
        self.dealer = n - 1 if dealer is None else dealer
        if type(self.dealer) is not int or not 0 <= self.dealer < n:
            raise ValueError('Dealer must be a seat index.')
        self.folded = tuple(folded)
        if (any(type(p) is not int or not 0 <= p < n for p in self.folded)
                or len(set(self.folded)) != len(self.folded) or n - len(self.folded) < 2):
            raise ValueError('Distinct folded seats and at least two live seats required.')
        self.live = tuple(p for p in range(n) if p not in self.folded)
        if stacks is None:
            if type(stack) is not int or not 0 <= stack <= 10000:
                raise ValueError('Invalid equal remaining stack.')
            stacks = (stack,) * n
        self.stacks = tuple(stacks)
        if len(self.stacks) != n or any(type(v) is not int or not 0 <= v <= 10000 for v in self.stacks):
            raise ValueError('One integer remaining stack per seat required.')
        self.integer_payouts = initial_contributions is not None
        self.initial_contributions = (tuple(initial_contributions) if self.integer_payouts
                                      else (pot / n,) * n)
        if self.integer_payouts:
            if (len(self.initial_contributions) != n
                    or any(type(v) is not int or v < 0 for v in self.initial_contributions)
                    or sum(self.initial_contributions) != pot):
                raise ValueError('Nonnegative integer prior contributions must sum to pot.')
            highest = max(self.initial_contributions)
            if any(self.stacks[p] and self.initial_contributions[p] != highest for p in self.live):
                raise ValueError('Funded players must have matched prior streets.')

        def sizes(values):
            result = tuple(values)
            if (len(result) > 2 or len(set(result)) != len(result)
                    or any(type(v) is not int or not min_bet <= v <= 10000 for v in result)):
                raise ValueError('Up to two distinct opening sizes meeting minimum bet required.')
            return tuple(sorted(result))

        self.turn_bet_sizes = sizes(turn_bet_sizes)
        self.river_bet_sizes = sizes(river_bet_sizes)
        self.ranges = tuple(tuple(r) for r in ranges)
        if (any(self.ranges[p] for p in self.folded)
                or any(not self.ranges[p] for p in self.live)
                or math.prod(max(1, len(r)) for r in self.ranges) > max_joint_combos):
            raise ValueError('Invalid or over-budget explicit ranges; no silent truncation.')
        for hand_range in self.ranges:
            seen = set()
            for text, weight in hand_range:
                if not isinstance(text, str) or not re.fullmatch(r'(?:[2-9TJQKA][cdhs]){2}', text):
                    raise ValueError('Invalid hole cards.')
                hand = frozenset((text[:2], text[2:]))
                if len(hand) != 2 or hand.intersection(board) or hand in seen:
                    raise ValueError('Duplicate, invalid or board-blocked combo.')
                if type(weight) not in (int, float) or not math.isfinite(weight) or weight <= 0:
                    raise ValueError('Positive finite weights required.')
                seen.add(hand)
        lineups = []
        for lineup in itertools.product(*(r if p in self.live else ((None, 1),)
                                          for p, r in enumerate(self.ranges))):
            hands = tuple(text for text, _ in lineup)
            occupied = [text[i:i+2] for text in hands if text for i in (0, 2)]
            if len(occupied) != len(set(occupied)):
                continue
            rivers = tuple(c for c in DECK if c not in board and c not in occupied)
            lineups.append((hands, math.prod(w for _, w in lineup), rivers))
        mass = sum(weight for _, weight, _ in lineups)
        if not math.isfinite(mass) or mass <= 0:
            raise ValueError('No positive compatible private deal.')
        if sum(len(rivers) for _, _, rivers in lineups) > max_outcomes:
            raise ValueError('Joint hand/river outcomes exceed budget; no sampling or truncation.')
        evaluator = HandEvaluator()
        scores = {}
        self.outcomes = []
        for hands, weight, rivers in lineups:
            for river in rivers:
                ranks = []
                for hand in hands:
                    if hand is None:
                        ranks.append(None)
                        continue
                    key = (hand, river)
                    if key not in scores:
                        scores[key] = evaluator.score(cards(hand + ''.join(board) + river))
                    ranks.append(scores[key])
                self.outcomes.append((hands, river, weight / mass / len(rivers), tuple(ranks)))
        self.joint_private_deals = len(lineups)
        self.nodes = []

        def save(node):
            if len(self.nodes) >= max_nodes or (len(self.nodes) + 1) * len(self.outcomes) > max_work:
                raise ValueError('Public tree/outcome budget exceeded; choose smaller explicit model.')
            self.nodes.append(node)
            return node

        def round_tree(street, history, alive, prior):
            available = tuple(self.stacks[p] - prior[p] for p in range(n))
            pending = tuple((self.dealer + i) % n for i in range(1, n+1)
                            if (self.dealer + i) % n in alive)
            sizes_ = self.turn_bet_sizes if street == 'turn' else self.river_bet_sizes

            def build(history, alive, paid, pending, current):
                funded = tuple(p for p in alive if paid[p] < available[p])
                pending = tuple(p for p in pending if p in funded)
                invested = tuple(a+b for a, b in zip(prior, paid))
                if len(alive) == 1:
                    return save(TurnNode(TERMINAL, street, history, invested=invested, alive=alive))
                if not pending or (len(funded) == 1 and paid[funded[0]] >= current):
                    if street == 'river':
                        return save(TurnNode(TERMINAL, street, history, invested=invested, alive=alive))
                    # Return an uncalled TURN excess before resetting street amounts.
                    ordered = sorted(range(n), key=lambda p: paid[p], reverse=True)
                    high, second = ordered[:2]
                    carried = list(invested)
                    carried[high] -= paid[high] - paid[second]
                    child = round_tree('river', history + (('RIVER',),), alive, tuple(carried))
                    return save(TurnNode(REVEAL, street, history, ('REVEAL_RIVER',), (child,),
                                         tuple(carried), alive))
                actor = pending[0]
                actions, children = [], []

                def add(label, next_alive, next_paid, queue, next_current=current):
                    actions.append(label)
                    children.append(build(history + ((actor, label),), next_alive,
                                          next_paid, queue, next_current))

                if paid[actor] < current:
                    add('FOLD', tuple(p for p in alive if p != actor), paid, pending[1:])
                    called = list(paid)
                    called[actor] = min(current, available[actor])
                    add('CALL', alive, tuple(called), pending[1:])
                else:
                    add('CHECK', alive, paid, pending[1:])
                # No raises in v1. Previously checked players respond to an opening.
                if current == 0 and len(funded) >= 2:
                    for target in sorted({min(size, available[actor]) for size in sizes_}):
                        wagered = list(paid)
                        wagered[actor] = target
                        responders = tuple((actor+i) % n for i in range(1, n)
                                           if (actor+i) % n in funded)
                        add('BET ' + str(target), alive, tuple(wagered), responders, target)
                return save(TurnNode(actor, street, history, tuple(actions), tuple(children), invested, alive))

            return build(history, alive, (0,) * n, pending, 0)

        self.root = round_tree('turn', (), self.live, (0,) * n)
        self.utilities = CompactUtilities(self.nodes, len(self.outcomes), n)
        for node in self.nodes:
            if node.actor != TERMINAL:
                continue
            for deal, (_, _, _, ranks) in enumerate(self.outcomes):
                awards, _, _ = self.settle(node, ranks)
                values = tuple(awards[p] - node.invested[p] - self.initial_contributions[p]
                               for p in range(n))
                if abs(sum(values)) > 1e-7:
                    raise ValueError('Payoffs must conserve chips.')
                self.utilities.put(node, deal, values)
        self.keys = set()
        self.action_counts = {}
        for node in self.nodes:
            if node.actor < 0:
                continue
            for deal in range(len(self.outcomes)):
                key = self.key(node, deal)
                self.keys.add(key)
                self.action_counts[key] = len(node.actions)

    # Reuse the frozen river's accounting only, not its single-street strategies
    # or tree ABI. Here invested holds cumulative new contributions.
    settle = RiverGame.settle

    def key(self, node, deal):
        if node.actor < 0:
            raise ValueError('Only player decisions have information sets.')
        hands, river, _, _ = self.outcomes[deal]
        return (node.actor, hands[node.actor], node.history, river if node.street == 'river' else None)

    def uniform_policy(self):
        return {key: [1 / size] * size for key, size in self.action_counts.items()}

    def train(self, iterations=50, *, max_visits=20000000, method='cfr_plus'):
        """Alternating CFR+ across ALL joint outcomes, with delayed public reveal.

        Linear averaging; no multiway convergence guarantee. A complete pass is
        frozen over private hands AND future cards before a player's update.
        """
        if method not in ('cfr_plus', 'cfr_plus_native'):
            raise ValueError('Choose Python CFR+ or the versioned turn native adapter.')
        if type(iterations) is not int or not 1 <= iterations <= 2000:
            raise ValueError('1–2000 iterations required.')
        if type(max_visits) is not int or not 1 <= max_visits <= 200000000:
            raise ValueError('Invalid traversal budget.')
        owned = [[key for key in self.action_counts if key[0] == p] for p in range(self.n)]
        work = iterations * sum(bool(keys) for keys in owned) * len(self.nodes) * len(self.outcomes)
        if work > max_visits:
            raise ValueError('Training traversal budget exceeded; no partial result returned.')
        if method == 'cfr_plus_native':
            from research.turn_native import train_turn_native
            return train_turn_native(self, iterations)
        regrets = {key: [0.] * size for key, size in self.action_counts.items()}
        average = {key: [0.] * size for key, size in self.action_counts.items()}
        policy = self.uniform_policy()
        keys = {(id(node), d): self.key(node, d) for node in self.nodes if node.actor >= 0
                for d in range(len(self.outcomes))}
        for iteration in range(1, iterations+1):
            for target, information_sets in enumerate(owned):
                if not information_sets:
                    continue
                delta = {key: [0.] * self.action_counts[key] for key in information_sets}

                def visit(node, deal, reach, chance):
                    if node.actor == TERMINAL:
                        return self.utilities[(id(node), deal)][target]
                    if node.actor == REVEAL:
                        # Probability is already in the joint root weight. Do not
                        # draw again, condition again, or multiply it a second time.
                        return visit(node.children[0], deal, reach, chance)
                    actor = node.actor
                    key = keys[(id(node), deal)]
                    strategy = policy[key]
                    values = []
                    for a, child in enumerate(node.children):
                        next_reach = list(reach)
                        next_reach[actor] *= strategy[a]
                        values.append(visit(child, deal, next_reach, chance))
                    value = sum(p*v for p, v in zip(strategy, values))
                    if actor == target:
                        counterfactual = chance * math.prod(reach[p] for p in range(self.n) if p != actor)
                        for a, probability in enumerate(strategy):
                            delta[key][a] += counterfactual * (values[a] - value)
                            average[key][a] += iteration * chance * reach[actor] * probability
                    return value

                for deal, (_, _, chance, _) in enumerate(self.outcomes):
                    visit(self.root, deal, [1.] * self.n, chance)
                for key, changes in delta.items():
                    row = regrets[key]
                    for a in range(len(row)):
                        row[a] = max(0., row[a] + changes[a])
                    total = sum(row)
                    policy[key] = [v / total for v in row] if total else [1 / len(row)] * len(row)
        return {key: [v / sum(row) for v in row] if sum(row) else [1 / len(row)] * len(row)
                for key, row in average.items()}

    def measure(self, policy):
        """Exact unilateral BR respecting own hand and time of public river reveal."""
        if (set(policy) != self.keys
                or any(len(row) != self.action_counts[key]
                       or any(not math.isfinite(p) or not 0 <= p <= 1 for p in row)
                       or abs(sum(row) - 1) > 1e-8 for key, row in policy.items())):
            raise ValueError('Complete normalized finite policy required.')

        def recurse(node, me, weights, best):
            if node.actor == TERMINAL:
                return sum(w * self.utilities[(id(node), d)][me] for d, w in weights)
            if node.actor == REVEAL:
                groups = {}
                for d, w in weights:
                    groups.setdefault(self.outcomes[d][1], []).append((d, w))
                return sum(recurse(node.children[0], me, group, best) for group in groups.values())
            if node.actor == me:
                strategy = policy[self.key(node, weights[0][0])]
                values = [recurse(child, me, weights, best) for child in node.children]
                return max(values) if best else sum(p*v for p, v in zip(strategy, values))
            return sum(recurse(child, me, [(d, w * policy[self.key(node, d)][a])
                                           for d, w in weights], best)
                       for a, child in enumerate(node.children))

        values, best = [], []
        for me in range(self.n):
            groups = {}
            for d, (hands, _, weight, _) in enumerate(self.outcomes):
                groups.setdefault(hands[me], []).append((d, weight))
            values.append(sum(recurse(self.root, me, group, False) for group in groups.values()))
            best.append(sum(recurse(self.root, me, group, True) for group in groups.values()))
        gains = [max(0., b-v) for b, v in zip(best, values)]
        return {'policy_payoffs': values, 'best_response_payoffs': best,
                'unilateral_gains': gains, 'nash_conv_chips': sum(gains),
                'max_unilateral_gain_pct_pot': max(gains) / self.decision_pot * 100}

    def root_action_values(self, policy, own_hand):
        """Own-hand EV of each first action, retaining the SAME continuation policy.

        EV starts at this decision: already funded pot is sunk, so add that
        seat's initial contribution back to the zero-sum accounting payoffs.
        This is not a separately optimized best response for each action.
        """
        if self.root.actor < 0:
            raise ValueError('No player decision at the turn root.')
        # Validate the full policy before inspecting any continuation.
        if (set(policy) != self.keys
                or any(len(row) != self.action_counts[key]
                       or any(not math.isfinite(p) or not 0 <= p <= 1 for p in row)
                       or abs(sum(row) - 1) > 1e-8 for key, row in policy.items())):
            raise ValueError('Complete normalized finite policy required.')
        actor = self.root.actor
        outcomes = [(d, weight) for d, (hands, _, weight, _) in enumerate(self.outcomes)
                    if hands[actor] == own_hand]
        mass = sum(weight for _, weight in outcomes)
        if mass <= 0:
            raise ValueError('Own hand must have positive compatible probability.')

        def continuation(node, deal):
            if node.actor == TERMINAL:
                return self.utilities[(id(node), deal)][actor]
            if node.actor == REVEAL:
                return continuation(node.children[0], deal)
            return sum(p * continuation(child, deal)
                       for p, child in zip(policy[self.key(node, deal)], node.children))

        values = [sum(w / mass * continuation(child, d) for d, w in outcomes)
                  + self.initial_contributions[actor] for child in self.root.children]
        probabilities = policy[self.key(self.root, outcomes[0][0])]
        best = max(values)
        return {'actor': actor, 'own_hand': own_hand, 'conditional_mass': mass,
                'ev_basis': 'from_current_decision_prior_contributions_are_sunk',
                'continuation': 'same_fixed_profile_after_each_first_action',
                'policy_ev_chips': sum(p*v for p, v in zip(probabilities, values)),
                'actions': [{'action': label, 'probability': p, 'ev_chips': value,
                             'gap_to_best_first_action_chips': best - value}
                            for label, p, value in zip(self.root.actions, probabilities, values)]}
