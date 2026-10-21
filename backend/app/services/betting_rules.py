from __future__ import annotations

from app.models.poker import ActionType, BettingOptions, HandState, PlayerStatus, Street


def betting_options(state: HandState, player_id: str | None = None) -> BettingOptions:
    """Legal table actions and sizes; a raise amount is the total street bet.

    Short all-ins may be below the minimum full raise. A prior actor only regains
    raise rights after facing at least one full raise in cumulative increments.
    No further raises are allowed against an opponent already all-in.
    """
    player_id = player_id or state.current_player_id
    options = BettingOptions(player_id=player_id)
    if state.result or state.street == Street.SHOWDOWN or player_id != state.current_player_id:
        return options
    player = next((p for p in state.players if p.id == player_id), None)
    if player is None or player.status != PlayerStatus.ACTIVE or player.stack <= 0:
        return options
    highest = highest_bet(state)
    owed = highest - player.current_bet
    options.call_amount = min(player.stack, owed)
    options.legal_actions = [ActionType.FOLD, ActionType.CALL if owed else ActionType.CHECK]
    can_contest = any(p.id != player_id and p.status == PlayerStatus.ACTIVE and p.stack > 0 for p in state.players)
    increment = max(state.big_blind, state.last_full_raise)
    last_acted = state.acted_at_bet.get(player_id)
    reopened = last_acted is None or highest - last_acted >= increment
    maximum = player.current_bet + player.stack
    if can_contest and maximum > highest and reopened:
        options.max_raise_to = maximum
        if highest == 0:
            options.legal_actions.append(ActionType.BET)
            options.min_bet = min(state.big_blind, player.stack)
        else:
            options.legal_actions.append(ActionType.RAISE)
            options.min_raise_to = min(highest + increment, maximum)
    return options


def highest_bet(state: HandState) -> int:
    actual = max(p.current_bet for p in state.players)
    funded = sum(p.status == PlayerStatus.ACTIVE and p.stack > 0 for p in state.players)
    # A short posted big blind does not reduce the preflop bring-in for others.
    return max(actual, state.big_blind) if state.street == Street.PREFLOP and funded > 1 else actual
