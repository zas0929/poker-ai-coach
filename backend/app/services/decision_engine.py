from __future__ import annotations

from collections import OrderedDict
from threading import Lock

from app.models.poker import Card, DrawProfile, HandAnalysis, HandState, PreflopProfile, PlayerStatus, Rank, Street, Suit
from app.services.equity_service import EquityService
from app.services.hand_evaluator import HandEvaluator
from app.services.range_service import RangeService
from app.services.betting_rules import betting_options, highest_bet


class DecisionEngine:
    def __init__(
        self,
        evaluator: HandEvaluator | None = None,
        equity_service: EquityService | None = None,
    ):
        self.evaluator = evaluator or HandEvaluator()
        self.equity_service = equity_service or EquityService(self.evaluator)
        self.range_service = RangeService(self.evaluator)
        self._analysis_cache = OrderedDict()
        self._cache_lock = Lock()
        self.cache_capacity = 128

    def analyze(self, state: HandState, player_id: str = "hero") -> HandAnalysis:
        player = self._get_player(state, player_id)
        # Do not read hidden holdings or deck order, even for cache identity.
        key = (player_id, tuple((c.rank, c.suit) for c in player.cards),
               state.model_dump_json(exclude={'players': {'__all__': {'cards'}}}))
        with self._cache_lock:
            cached = self._analysis_cache.get(key)
            if cached is not None:
                self._analysis_cache.move_to_end(key)
                return cached.model_copy(deep=True)
        result = self._analyze(state, player_id)
        with self._cache_lock:
            self._analysis_cache[key] = result.model_copy(deep=True)
            self._analysis_cache.move_to_end(key)
            while len(self._analysis_cache) > self.cache_capacity:
                self._analysis_cache.popitem(last=False)
        return result

    @staticmethod
    def recommended_size(state, player_id, action):
        if action not in ('bet', 'raise'):
            return None
        options = betting_options(state, player_id)
        if action not in options.legal_actions:
            return None
        highest = highest_bet(state)
        if action == 'bet':
            target = round(state.pot * 2 / 3)
            minimum = options.min_bet
        else:
            target = (3 * highest if state.street == Street.PREFLOP
                      else highest + round((state.pot + options.call_amount) * 2 / 3))
            minimum = options.min_raise_to
        return min(options.max_raise_to, max(minimum, target))

    def _analyze(self, state: HandState, player_id: str) -> HandAnalysis:
        player = self._get_player(state, player_id)
        call_amount = self._call_amount(state, player_id)
        opponents = [p for p in state.players if p.id != player_id and p.status != PlayerStatus.FOLDED]
        if player.status == PlayerStatus.FOLDED or not opponents:
            raise ValueError("Analysis requires an unfolded player and at least one live opponent.")
        ranges = [self.range_service.infer(state, player_id, p.id) for p in opponents]
        opponent_range = ranges[0]
        estimate = self.equity_service.estimate(state, player_id, opponent_range=opponent_range, opponent_ranges=ranges)
        multiway = len(state.players) > 2
        equity = estimate.equity
        # An unmatched overbet is returned when a short stack calls all-in.
        raw_call = highest_bet(state) - player.current_bet
        contestable_pot = state.pot - max(0, raw_call - call_amount)
        if multiway and state.contributions:
            cap = state.contributions[player_id] + call_amount
            contestable_pot = sum(min(c, cap) for c in state.contributions.values())
        required_equity = self._required_equity(contestable_pot, call_amount)
        ev_call = 0.0 if multiway else round(equity * (contestable_pot + call_amount) - call_amount, 2)
        hand_strength = self.evaluator.evaluate([*player.cards, *state.board])
        preflop_profile = self.preflop_profile(player.cards)
        draw_profile = self._draw_profile(player.cards, state.board, state.street)
        recommended_action = self._recommend_action(equity, required_equity, call_amount)
        if recommended_action == "bet" and highest_bet(state) > 0:
            recommended_action = "raise"
        if recommended_action == "raise" and (player.stack <= call_amount or all(p.stack == 0 for p in opponents)):
            recommended_action = "call" if call_amount else "check"
        options = betting_options(state, player_id)
        if options.legal_actions and recommended_action not in options.legal_actions:
            recommended_action = "call" if options.call_amount else "check"

        return HandAnalysis(
            hand_id=state.hand_id,
            street=state.street,
            pot=state.pot,
            player_id=player_id,
            call_amount=call_amount,
            required_equity=required_equity,
            equity=equity,
            opponent_range=opponent_range.summary,
            opponent_ranges=[r.summary for r in ranges],
            opponent_count=len(opponents),
            call_ev_available=not multiway,
            equity_method=estimate.method,
            equity_samples=estimate.samples,
            equity_sampling_error=estimate.sampling_error,
            ev_call=ev_call,
            recommended_action=recommended_action,
            recommended_amount=self.recommended_size(state, player_id, recommended_action),
            hand_strength=hand_strength,
            preflop_profile=preflop_profile,
            draw_profile=draw_profile,
            coach_summary=(f"Equity is your expected share against {len(opponents)} live opponents. "
                           "The action is a heuristic; pot-specific call EV and future responses are not solved.") if multiway else self._coach_summary(
                recommended_action,
                equity,
                required_equity,
                call_amount,
                ev_call,
                hand_strength.category,
                preflop_profile,
                draw_profile,
            ),
            confidence=self._confidence(equity, required_equity, call_amount),
            risk_level=self._risk_level(equity, required_equity, call_amount),
            key_factors=([f"Live opponents: {len(opponents)}", "Multiway equity includes split pots; side-pot EV is not calculated."] if multiway else self._key_factors(
                state,
                call_amount,
                equity,
                required_equity,
                ev_call,
                hand_strength.category,
                preflop_profile,
                draw_profile,
            )),
            notes=(["Multiway ranges are heuristic and sampled jointly without card collisions.", "Required equity is a single-pot price proxy, not a side-pot EV threshold."] if multiway else [opponent_range.summary.description, *self._notes(equity, required_equity, call_amount, ev_call)]),
        )

    def _call_amount(self, state: HandState, player_id: str) -> int:
        player = self._get_player(state, player_id)
        highest = highest_bet(state)
        return min(player.stack, max(highest - player.current_bet, 0))

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
            return ["No bet to call. Bet/check advice uses an equity heuristic, not a comparison of action EVs."]

        return [
            "Equity uses an assumed opponent range, not their hidden cards. Position and action weights are uncalibrated; bet sizing and stack depth do not adjust the range yet.",
            f"Calling requires {required_equity:.1%} equity and the estimate is {equity:.1%}.",
            f"Check-down EV of call is {ev_call}; future betting and rake are excluded. Raise EV is not calculated.",
        ]

    def _coach_summary(
        self,
        action: str,
        equity: float,
        required_equity: float,
        call_amount: int,
        ev_call: float,
        category: str,
        preflop_profile: PreflopProfile,
        draw_profile: DrawProfile,
    ) -> str:
        hand_label = category.replace("_", " ")
        starter = preflop_profile.notation
        draw_text = self._draw_text(draw_profile)

        if call_amount == 0:
            if action == "bet":
                return f"You can apply pressure here. {starter} started as a {preflop_profile.category}, and your {hand_label}{draw_text} has enough estimated equity to value bet or deny equity."
            return f"Checking is reasonable. {starter} is a {preflop_profile.category}, but your {hand_label}{draw_text} does not have enough estimated equity to force value."

        equity_edge = equity - required_equity
        if action == "fold":
            return f"Fold is preferred with {starter} because your equity is below the price being offered. Calling is estimated at {ev_call} EV."
        if action == "raise":
            return f"The heuristic suggests a raise with {starter} because equity is above the call threshold. This does not prove raising beats calling: opponent responses and raise sizing are not solved."
        if equity_edge >= 0:
            return f"Call is acceptable with {starter} because your equity clears the pot-odds threshold by {equity_edge:.1%}."
        return f"This is a close spot with {starter}. Calling is only marginal, so future street play matters."

    def _confidence(self, equity: float, required_equity: float, call_amount: int) -> float:
        if call_amount == 0:
            distance = abs(equity - 0.58)
        else:
            distance = abs(equity - required_equity)

        return round(min(0.95, 0.45 + distance * 1.8), 2)

    def _risk_level(self, equity: float, required_equity: float, call_amount: int) -> str:
        if call_amount == 0:
            if equity >= 0.65:
                return "low"
            if equity >= 0.5:
                return "medium"
            return "high"

        edge = equity - required_equity
        if edge >= 0.18:
            return "low"
        if edge >= 0.03:
            return "medium"
        return "high"

    def _key_factors(
        self,
        state: HandState,
        call_amount: int,
        equity: float,
        required_equity: float,
        ev_call: float,
        category: str,
        preflop_profile: PreflopProfile,
        draw_profile: DrawProfile,
    ) -> list[str]:
        factors = [
            f"Street: {state.street.value}",
            f"Starting hand: {preflop_profile.notation} ({preflop_profile.category})",
            f"Made hand: {category.replace('_', ' ')}",
            f"Estimated equity: {equity:.1%}",
        ]
        if draw_profile.draws:
            factors.append(f"Draws: {', '.join(draw_profile.draws)} ({draw_profile.outs} estimated outs)")
        if draw_profile.overcards:
            factors.append(f"Overcards: {draw_profile.overcards}")

        if call_amount > 0:
            factors.extend(
                [
                    f"Call amount: {call_amount}",
                    f"Required equity: {required_equity:.1%}",
                    f"Call EV: {ev_call}",
                ]
            )
        else:
            factors.append("No bet to call")

        return factors

    def _draw_profile(self, hole_cards: list[Card], board: list[Card], street: Street) -> DrawProfile:
        if street not in {Street.FLOP, Street.TURN} or not board:
            return DrawProfile()

        cards = [*hole_cards, *board]
        draws: list[str] = []
        outs = 0

        suit_counts = {suit: 0 for suit in Suit}
        for card in cards:
            suit_counts[card.suit] += 1

        if max(suit_counts.values()) == 4:
            draws.append("flush draw")
            outs += 9
        elif max(suit_counts.values()) == 3 and len(board) == 3:
            draws.append("backdoor flush draw")
            outs += 1

        straight_draw = self._straight_draw(cards)
        if straight_draw == "open-ended straight draw":
            draws.append(straight_draw)
            outs += 8
        elif straight_draw == "gutshot straight draw":
            draws.append(straight_draw)
            outs += 4

        overcards = self._overcards(hole_cards, board)
        if overcards:
            draws.append("overcards")
            outs += overcards * 3

        return DrawProfile(outs=min(outs, 20), draws=draws, overcards=overcards)

    def _straight_draw(self, cards: list[Card]) -> str | None:
        values = {self._rank_value(card.rank) for card in cards}
        if 14 in values:
            values.add(1)

        open_ended = False
        gutshot = False
        for start in range(1, 11):
            window = set(range(start, start + 5))
            missing = sorted(window - values)
            if len(missing) != 1:
                continue
            missing_value = missing[0]
            if missing_value in {start, start + 4}:
                open_ended = True
            else:
                gutshot = True

        if open_ended:
            return "open-ended straight draw"
        if gutshot:
            return "gutshot straight draw"
        return None

    def _overcards(self, hole_cards: list[Card], board: list[Card]) -> int:
        if not board:
            return 0
        highest_board = max(self._rank_value(card.rank) for card in board)
        return sum(1 for card in hole_cards if self._rank_value(card.rank) > highest_board)

    def _draw_text(self, draw_profile: DrawProfile) -> str:
        if not draw_profile.draws:
            return ""
        return f" plus {', '.join(draw_profile.draws)}"

    @classmethod
    def preflop_profile(cls, cards: list[Card]) -> PreflopProfile:
        if len(cards) != 2:
            return PreflopProfile(notation="unknown", category="unknown", score=0, tags=[])

        first, second = sorted(cards, key=lambda card: cls._rank_value(card.rank), reverse=True)
        first_value = cls._rank_value(first.rank)
        second_value = cls._rank_value(second.rank)
        suited = first.suit == second.suit
        paired = first.rank == second.rank
        gap = abs(first_value - second_value) - 1

        if paired:
            notation = f"{first.rank.value}{second.rank.value}"
        else:
            notation = f"{first.rank.value}{second.rank.value}{'s' if suited else 'o'}"

        tags: list[str] = []
        if paired:
            tags.append("pocket pair")
        if suited:
            tags.append("suited")
        if gap == 0 and not paired:
            tags.append("connector")
        elif gap == 1 and not paired:
            tags.append("one gapper")
        if first_value >= 14 and second_value >= 10:
            tags.append("broadway")
        if first_value == 14:
            tags.append("ace high")

        score = first_value + second_value
        if paired:
            score += first_value + 8
        if suited:
            score += 3
        if gap == 0 and not paired:
            score += 3
        elif gap == 1 and not paired:
            score += 1
        elif gap >= 3:
            score -= 3

        category = cls._preflop_category(score, paired, first_value, second_value)
        return PreflopProfile(notation=notation, category=category, score=score, tags=tags)

    @staticmethod
    def _preflop_category(score: int, paired: bool, high: int, low: int) -> str:
        if paired and high >= 10:
            return "premium pair"
        if high == 14 and low >= 12:
            return "premium broadway"
        if score >= 29:
            return "strong"
        if score >= 24:
            return "playable"
        if score >= 19:
            return "speculative"
        return "weak"

    @staticmethod
    def _rank_value(rank: Rank) -> int:
        values = {
            Rank.TWO: 2,
            Rank.THREE: 3,
            Rank.FOUR: 4,
            Rank.FIVE: 5,
            Rank.SIX: 6,
            Rank.SEVEN: 7,
            Rank.EIGHT: 8,
            Rank.NINE: 9,
            Rank.TEN: 10,
            Rank.JACK: 11,
            Rank.QUEEN: 12,
            Rank.KING: 13,
            Rank.ACE: 14,
        }
        return values[rank]

    def _get_player(self, state: HandState, player_id: str):
        for player in state.players:
            if player.id == player_id:
                return player
        raise ValueError(f"Player {player_id} was not found.")
