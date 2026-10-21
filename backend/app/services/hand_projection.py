"""A shared private-card boundary for live tables and archived hands."""
from app.models.poker import HandState, PlayerStatus


def project_hand(state: HandState, viewer_id: str) -> dict:
    hand = state.model_dump(mode='json')
    revealed = set()
    for player in hand['players']:
        if player['id'] == viewer_id or (
            hand['result'] and hand['result']['reason'] == 'showdown'
            and player['status'] != PlayerStatus.FOLDED.value
        ):
            revealed.add(player['id'])
        else:
            player['cards'] = []
    if hand['result']:
        for result in hand['result']['player_results']:
            if result['player_id'] not in revealed:
                result['hand_strength'] = None
    hand.pop('acted_at_bet', None)
    hand['notes'] = []
    return hand
