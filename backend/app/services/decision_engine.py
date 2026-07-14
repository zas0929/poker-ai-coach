from __future__ import annotations

from app.models.poker import HandAnalysis, HandState
from app.services.equity_service import EquityService
from app.services.hand_evaluator import HandEvaluator


class DecisionEngine:
    def __init__(
        self,
        evaluator: HandEvaluator | None = None,
        equity_service: EquityService | None = None,
    ):
        self.evaluator = evaluator or HandEvaluator()
        self.equity_service = equity_service or EquityService(self.evaluator)

    def analyze(self, state: HandState, player_id: str = "hero") -> HandAnalysis:
        player = self._get_player(state, player_id)
        call_amount = self._call_amount(state, player_id)
        equity = self.equity_service.estimate_equity(state, player_id=player_id)
        required_equity = self._required_equity(state.pot, call_amount)
        ev_call = round(equity * (state.pot + call_amount) - call_amount, 2)
        hand_strength = self.evaluator.evaluate([*player.cards, *state.board])

        return HandAnalysis(
            hand_id=state.hand_id,
            street=state.street,
            pot=state.pot,
            player_id=player_id,
            call_amount=call_amount,
            required_equity=required_equity,
            equity=equity,
            ev_call=ev_call,
            recommended_action=self._recommend_action(equity, required_equity, call_amount),
            hand_strength=hand_strength,
            notes=self._notes(equity, required_equity, call_amount, ev_call),
        )

    def _call_amount(self, state: HandState, player_id: str) -> int:
        player = self._get_player(state, player_id)
        highest_bet = max(seat.current_bet for seat in state.players)
        return max(highest_bet - player.current_bet, 0)

    def _required_equity(self, pot: int, call_amount: int) -> float:
        if call_amount == 0:
            return 0.0
        return round(call_amount / (pot + call_amount), 4)

    def _recommend_action(self, equity: float, required_equity: float, call_amount: int) -> str:
        if call_amount == 0:
            return "bet" if equity >= 0.58 else "check"

        if equity < required_equity - 0.03:
            return "fold"
        if equity >= required_equity + 0.18:
            return "raise"
        return "call"

    def _notes(self, equity: float, required_equity: float, call_amount: int, ev_call: float) -> list[str]:
        if call_amount == 0:
            return ["No bet to call. Recommendation is based on raw equity versus a random opponent hand."]

        return [
            "Equity is estimated with Monte Carlo simulation against a random opponent hand.",
            f"Calling requires {required_equity:.1%} equity and the estimate is {equity:.1%}.",
            f"Estimated EV of call is {ev_call}.",
        ]

    def _get_player(self, state: HandState, player_id: str):
        for player in state.players:
            if player.id == player_id:
                return player
        raise ValueError(f"Player {player_id} was not found.")
