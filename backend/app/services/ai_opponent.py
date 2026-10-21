from __future__ import annotations

from dataclasses import dataclass

from app.models.poker import ActionType, HandAnalysis, HandState, Player, Street
from app.services.betting_rules import betting_options, highest_bet as table_highest_bet


@dataclass(frozen=True)
class AIOpponentDecision:
    action: ActionType
    amount: int | None = None
    reason: str = ""


class AIOpponentService:
    def __init__(self, profile: str = "balanced"):
        self.profile = profile

    def choose_action(self, state: HandState, analysis: HandAnalysis, player_id: str = "villain") -> AIOpponentDecision:
        player = self._get_player(state, player_id)
        highest_bet = table_highest_bet(state)
        call_amount = max(highest_bet - player.current_bet, 0)

        options = betting_options(state, player_id)
        if not options.legal_actions:
            raise ValueError(f"Player {player_id} has no legal action.")
        if state.street == Street.PREFLOP:
            decision = self._preflop_decision(state, analysis, player, call_amount, highest_bet)
        else:
            decision = self._postflop_decision(state, analysis, player, call_amount, highest_bet)
        if decision.action not in options.legal_actions:
            fallback = ActionType.CALL if options.call_amount else ActionType.CHECK
            return AIOpponentDecision(fallback, reason="Continue without an available raise.")
        if decision.action in {ActionType.BET, ActionType.RAISE}:
            minimum = options.min_bet if decision.action == ActionType.BET else options.min_raise_to
            target = min(options.max_raise_to, max(minimum, decision.amount or minimum))
            return AIOpponentDecision(decision.action, target, decision.reason)
        return decision

    def _preflop_decision(
        self,
        state: HandState,
        analysis: HandAnalysis,
        player: Player,
        call_amount: int,
        highest_bet: int,
    ) -> AIOpponentDecision:
        category = analysis.preflop_profile.category
        score = analysis.preflop_profile.score

        if call_amount > 0:
            if category in {"premium pair", "premium broadway", "strong"}:
                return AIOpponentDecision(
                    action=ActionType.RAISE,
                    amount=self._raise_target(state, player, highest_bet, multiplier=3),
                    reason=f"{self.profile} preflop 3-bet with {analysis.preflop_profile.notation}",
                )
            if category == "playable" or (category == "speculative" and call_amount <= state.big_blind):
                return AIOpponentDecision(
                    action=ActionType.CALL,
                    reason=f"{self.profile} preflop continue with {analysis.preflop_profile.notation}",
                )
            return AIOpponentDecision(
                action=ActionType.FOLD,
                reason=f"{self.profile} preflop fold with {analysis.preflop_profile.notation}",
            )

        if category in {"premium pair", "premium broadway", "strong"}:
            return AIOpponentDecision(
                action=ActionType.RAISE if highest_bet > 0 else ActionType.BET,
                amount=(self._raise_target(state, player, highest_bet, multiplier=3)
                        if highest_bet > 0 else self._open_size(state, player, multiplier=3)),
                reason=f"{self.profile} preflop open with {analysis.preflop_profile.notation}",
            )
        if category == "playable" or score >= 22:
            return AIOpponentDecision(
                action=ActionType.CHECK,
                reason=f"{self.profile} preflop check with {analysis.preflop_profile.notation}",
            )
        return AIOpponentDecision(
            action=ActionType.CHECK,
            reason=f"{self.profile} preflop pot control with {analysis.preflop_profile.notation}",
        )

    def _postflop_decision(
        self,
        state: HandState,
        analysis: HandAnalysis,
        player: Player,
        call_amount: int,
        highest_bet: int,
    ) -> AIOpponentDecision:
        if call_amount > 0:
            if analysis.recommended_action == "raise":
                return AIOpponentDecision(
                    action=ActionType.RAISE,
                    amount=self._raise_target(state, player, highest_bet, multiplier=2),
                    reason=f"{self.profile} pressure raise with {analysis.equity:.1%} equity",
                )
            if analysis.recommended_action == "call":
                return AIOpponentDecision(
                    action=ActionType.CALL,
                    reason=f"{self.profile} call with {analysis.equity:.1%} equity",
                )
            return AIOpponentDecision(
                action=ActionType.FOLD,
                reason=f"{self.profile} fold below pot odds",
            )

        if analysis.recommended_action == "bet":
            return AIOpponentDecision(
                action=ActionType.BET,
                amount=self._postflop_bet_size(state, player),
                reason=f"{self.profile} value/protection bet with {analysis.equity:.1%} equity",
            )
        return AIOpponentDecision(
            action=ActionType.CHECK,
            reason=f"{self.profile} check with {analysis.equity:.1%} equity",
        )

    def _open_size(self, state: HandState, player: Player, multiplier: int) -> int:
        return min(player.stack, max(state.big_blind, state.big_blind * multiplier))

    def _postflop_bet_size(self, state: HandState, player: Player) -> int:
        return min(player.stack, max(state.big_blind, round(state.pot * 0.6)))

    def _raise_target(self, state: HandState, player: Player, highest_bet: int, multiplier: int) -> int:
        target = max(highest_bet + state.big_blind, highest_bet * multiplier)
        return min(player.current_bet + player.stack, target)

    def _get_player(self, state: HandState, player_id: str) -> Player:
        for player in state.players:
            if player.id == player_id:
                return player
        raise ValueError(f"Player {player_id} was not found.")
