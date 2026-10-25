"""Compile delayed public reveal to the unchanged generic CFR numeric ABI.

Joint hand/river outcomes are root chance rows. Reveal nodes are unary and can
be erased WITHOUT changing player choices: information-set IDs still hide the
river on turn and expose it on river. The adapter is separate/versioned; the
frozen river compiler/kernel and the original TurnGame are never mutated.
"""
import copy
import json
from types import SimpleNamespace

from research.native_cfr import train_native
from research.turn_reference import REVEAL

ADAPTER_VERSION = 'turn-delayed-reveal-native-v1'


def compile_turn(game):
    def resolved(node):
        while node.actor == REVEAL:
            if len(node.children) != 1:
                raise ValueError('A delayed reveal must have exactly one continuation.')
            node = node.children[0]
        return node

    originals = [node for node in game.nodes if node.actor != REVEAL]
    if len(originals) * len(game.outcomes) > 1000000:
        raise ValueError('Turn native compilation exceeds the numeric ABI node/outcome budget.')
    proxies = {id(node): SimpleNamespace(actor=node.actor) for node in originals}
    for node in originals:
        proxies[id(node)].children = tuple(proxies[id(resolved(child))] for child in node.children)
    reverse = {id(proxies[id(node)]): node for node in originals}
    # Strings give a total ordering even when histories contain street markers.
    encoded = {key: (key[0], key[1], json.dumps(key[2:], separators=(',', ':'))) for key in game.keys}
    if len(set(encoded.values())) != len(encoded):
        raise ValueError('Information-set encoding collision.')
    utilities = copy.copy(game.utilities)
    utilities.slots = {id(proxies[id(node)]): game.utilities.slots[id(node)]
                       for node in originals if node.actor == -1}
    return SimpleNamespace(
        n=game.n, nodes=[proxies[id(node)] for node in originals],
        root=proxies[id(resolved(game.root))],
        keys=set(encoded.values()),
        action_counts={encoded[key]: size for key, size in game.action_counts.items()},
        key=lambda node, deal: encoded[game.key(reverse[id(node)], deal)],
        deals=[(hands, chance, scores) for hands, _, chance, scores in game.outcomes],
        utilities=utilities, original_keys={v: k for k, v in encoded.items()})


def train_turn_native(game, iterations):
    compiled = compile_turn(game)
    policy = train_native(compiled, iterations)
    return {compiled.original_keys[key]: row for key, row in policy.items()}
