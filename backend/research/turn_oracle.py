"""Replay a bounded turn model through the independent production poker engine.

Only verification imports the engine: the turn reference does not use it for
its public tree, future-card probabilities, strategies or payoff calculation.
"""
from app.models.poker import ActionType, HandState, Player, PlayerStatus, Street
from app.services.poker_engine import PokerEngine
from research.river_reference import cards
from research.turn_reference import REVEAL, TERMINAL


def compare_every_path(game, outcome_indices=None):
    indices = tuple(range(len(game.outcomes))) if outcome_indices is None else tuple(outcome_indices)
    if not indices or len(set(indices)) != len(indices) or any(
            type(d) is not int or not 0 <= d < len(game.outcomes) for d in indices):
        raise ValueError('Distinct existing outcomes required for verification.')
    if not game.integer_payouts:
        raise ValueError('Production engine comparison requires explicit integer contributions.')
    engine = PokerEngine()
    visited = terminals = 0
    for deal in indices:
        hands, river, _, _ = game.outcomes[deal]
        observed_folds = {a[0] for a in game.turn_actions if a[1] == 'fold'}
        initial_folded = set(game.folded) - observed_folds
        state = HandState(
            hand_id='turn-reference-oracle', street=Street.TURN, pot=game.pot,
            small_blind=1, big_blind=game.min_bet, board=cards(''.join(game.board)),
            players=[Player(id=str(p), name=str(p), position='', stack=game.stacks[p],
                            cards=cards(hand) if hand else [],
                            status=PlayerStatus.FOLDED if p in initial_folded else
                            (PlayerStatus.ACTIVE if game.stacks[p] else PlayerStatus.ALL_IN))
                     for p, hand in enumerate(hands)],
            current_player_id=str(game.root.actor) if game.root.actor >= 0 else None,
            dealer_player_id=str(game.dealer), last_full_raise=game.min_bet,
            contributions={str(p): v for p, v in enumerate(game.initial_contributions)})
        state._deck = cards(river)
        # Reconstruct the observed prefix independently through production actions,
        # not by copying the research replay cursor into engine bookkeeping.
        state.current_player_id = engine._next_pending(state, state.dealer_player_id)
        engine._refresh_betting(state)
        for actor, label, added in game.turn_actions:
            if state.current_player_id != str(actor):
                raise AssertionError('Observed prefix actor mismatch.')
            player = state.players[actor]
            if label == 'call' and state.betting.call_amount != added:
                raise AssertionError('Observed call amount mismatch.')
            amount = player.current_bet + added if label in ('bet', 'raise') else None
            engine.apply_action(state, str(actor), ActionType(label), amount)
        if state.result is None and game.root.actor >= 0:
            if (state.pot != game.decision_pot or state.current_player_id != str(game.root.actor)
                    or tuple(p.current_bet for p in state.players) != game.root_state.invested
                    or state.last_full_raise != game.root_state.increment):
                raise AssertionError('Observed turn cursor disagrees with engine.')

        def visit(node, current):
            nonlocal visited, terminals
            visited += 1
            if node.actor == TERMINAL:
                terminals += 1
                if current.result is None:
                    engine.advance(current)
                if current.result is None:
                    raise AssertionError('Model ended before engine settled.')
                for p, player in enumerate(current.players):
                    actual = player.stack - game.stacks[p] - game.initial_contributions[p]
                    expected = game.utilities[(id(node), deal)][p]
                    if abs(actual - expected) > 1e-8:
                        raise AssertionError((node.history, river, p, expected, actual))
                if sum(p.stack for p in current.players) != sum(game.stacks) + game.pot:
                    raise AssertionError('Conservation failure.')
                return
            if node.actor == REVEAL:
                if current.result is None:
                    engine.advance(current)
                if current.board[-1] != cards(river)[0]:
                    raise AssertionError('Wrong public river card.')
                visit(node.children[0], current)
                return
            if current.street.value != node.street or current.current_player_id != str(node.actor):
                raise AssertionError((node.street, node.actor, current.street, current.current_player_id))
            for label, child in zip(node.actions, node.children):
                parts = label.split()
                next_state = current.model_copy(deep=True)
                engine.apply_action(next_state, str(node.actor), ActionType(parts[0].lower()),
                                    int(parts[1]) if len(parts) == 2 else None)
                visit(child, next_state)

        visit(game.root, state)
    return {'outcomes_verified': len(indices), 'total_outcomes': len(game.outcomes),
            'node_outcome_visits': visited, 'terminal_outcome_checks': terminals}
