from __future__ import annotations

from app.models.poker import ActionType, Card, HandState
from app.services.hand_projection import project_hand
from app.services.poker_engine import PokerEngine


def hand_summary(raw: dict, viewer_id: str, cursor: int, completed_at: str) -> dict:
    player = next((p for p in raw['players'] if p['id'] == viewer_id), None)
    if player is None or not raw.get('result'):
        raise ValueError('Archived hand not found.')
    award = next(r['amount_won'] for r in raw['result']['player_results'] if r['player_id'] == viewer_id)
    committed = raw['contributions'].get(viewer_id, 0)
    return {
        'hand_id': raw['hand_id'], 'cursor': cursor, 'completed_at': completed_at + 'Z',
        'reason': raw['result']['reason'], 'pot_awarded': raw['result']['pot_awarded'],
        'player_count': len(raw['players']), 'own_cards': player['cards'], 'board': raw['board'],
        'amount_won': award, 'committed': committed, 'net': award - committed,
        'winners': [p['name'] for p in raw['players'] if p['id'] in raw['result']['winners']],
    }


def replay_hand(raw: dict, viewer_id: str) -> dict:
    final = HandState.model_validate(raw)
    if not final.result or not any(p.id == viewer_id for p in final.players):
        raise ValueError('Archived hand not found.')
    final_view = project_hand(final, viewer_id)
    try:
        frames = _reconstruct(raw, final, viewer_id)
        warning = None
    except (ValueError, KeyError, StopIteration, TypeError, IndexError):
        # Old/corrupt/incompatible histories must never show an invented replay.
        frames = [{'label': 'Final result', 'hand': final_view, 'decision': None}]
        warning = 'Exact replay is unavailable for this hand. The saved final result is shown.'
    return {'hand_id': final.hand_id, 'viewer_id': viewer_id, 'hand': final_view,
            'frames': frames, 'warning': warning,
            'review_note': 'Review shows recorded decisions and chip accounting. It does not grade strategy or calculate solver EV.'}


def _reconstruct(raw, final, viewer_id):
    engine = PokerEngine()
    button = next(i for i, p in enumerate(final.players) if p.id == final.dealer_player_id)
    ordered = final.players[button:] + final.players[:button]
    awards = {r.player_id: r.amount_won for r in final.result.player_results}
    stacks = [p.stack - awards[p.id] + final.contributions[p.id] for p in ordered]
    state = engine.start_hand(player_count=len(ordered), starting_stacks=stacks,
                              small_blind=final.small_blind, big_blind=final.big_blind)
    mapping = {p.id: original.id for p, original in zip(state.players, ordered)}
    for player, original in zip(state.players, ordered):
        player.id, player.name = original.id, original.name
        player.cards = [c.model_copy() for c in original.cards]
    state.hand_id = final.hand_id
    state.current_player_id = mapping.get(state.current_player_id)
    state.dealer_player_id = mapping[state.dealer_player_id]
    state.contributions = {mapping[k]: v for k, v in state.contributions.items()}
    for action in state.history:
        action.player_id = mapping[action.player_id]
    state._deck = [Card.model_validate(c) for c in raw['_deck']] + list(reversed(final.board))
    engine._refresh_betting(state)
    if [a.model_dump() for a in state.history] != [a.model_dump() for a in final.history[:2]]:
        raise ValueError('Blind history does not match.')
    frames = []
    for action in final.history[2:]:
        if state.result or state.street != action.street or state.current_player_id != action.player_id:
            raise ValueError('History order does not match the engine.')
        player = next(p for p in state.players if p.id == action.player_id)
        supplied_amount = player.current_bet + (action.amount or 0) if action.action in {'bet', 'raise'} else None
        chosen = action.action + (f' to {supplied_amount}' if supplied_amount is not None else f' {action.amount}' if action.amount else '')
        decision = None
        if player.id == viewer_id:
            price = state.betting.call_amount
            raw_call = max(p.current_bet for p in state.players) - player.current_bet
            contestable = state.pot - max(0, raw_call - price)
            threshold = price / (contestable + price) if price and len(state.players) == 2 else None
            decision = {
                'action': action.action, 'description': chosen, 'pot_before': state.pot,
                'stack_before': player.stack, 'call_amount': price,
                'committed_by_action': action.amount or 0,
                'break_even_equity': threshold,
                'made_hand': engine.evaluator.evaluate([*player.cards, *state.board]).category,
                'note': 'Call price assumes no further betting or rake.' if threshold is not None else
                        'Side-pot EV is not calculated.' if len(state.players) > 2 else 'No call price was faced.',
            }
        frames.append({'label': f'{action.street.value} · {player.name}: {chosen}',
                       'hand': project_hand(state, viewer_id), 'decision': decision})
        state = engine.apply_action(state, player.id, ActionType(action.action), supplied_amount)
        if state.history[-1] != action:
            raise ValueError('Recorded chip movement does not match replay.')
        while not state.current_player_id and not state.result:
            state = engine.advance(state)
    if not state.result or state.board != final.board or state.result != final.result or any(
        p.stack != next(q.stack for q in final.players if q.id == p.id) for p in state.players
    ) or state.contributions != final.contributions:
        raise ValueError('Replayed payouts differ from the saved result.')
    frames.append({'label': 'Final result', 'hand': project_hand(final, viewer_id), 'decision': None})
    return frames
