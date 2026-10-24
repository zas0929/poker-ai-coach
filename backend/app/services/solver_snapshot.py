"""Provider-neutral PUBLIC decision snapshots for 2–6 player solver research.

This module prepares inputs, not a solution. No solver binary, network request,
LLM call or fallback heads-up decomposition is performed here.
"""
from hashlib import sha256
import json
from app.models.poker import HandState, PlayerStatus, Street
from app.services.range_service import RangeService

SUITS={'spades':'s','hearts':'h','diamonds':'d','clubs':'c'}
BOARD_COUNTS={Street.PREFLOP:0,Street.FLOP:3,Street.TURN:4,Street.RIVER:5}

def card_text(card):
    return card.rank.value+SUITS[card.suit.value]

class UnsupportedSolverState(ValueError):
    pass

def prepare_solver_snapshot(state: HandState) -> dict:
    """Preserve all seats, dead money, unequal stacks and public action amounts.

    Uses only public cards/actions/positions. The inferred ranges remain
    uncalibrated heuristics; they are NOT labelled GTO or independently weighted
    beliefs that account for folded-hand bunching.
    """
    if state.result or state.street not in BOARD_COUNTS:
        raise UnsupportedSolverState('Pass a decision snapshot before the hand ended.')
    if not 2<=len(state.players)<=6:
        raise UnsupportedSolverState('Supported table size is 2–6 players.')
    ids=[p.id for p in state.players]
    if len(set(ids))!=len(ids) or state.dealer_player_id not in ids:
        raise UnsupportedSolverState('Invalid seats or button.')
    if state.current_player_id not in ids:
        raise UnsupportedSolverState('A current acting player is required.')
    active=[p for p in state.players if p.status!=PlayerStatus.FOLDED]
    actor=next(p for p in state.players if p.id==state.current_player_id)
    if len(active)<2 or actor.status!=PlayerStatus.ACTIVE or actor.stack<=0:
        raise UnsupportedSolverState('At least two live players and a valid decision are required.')
    board=[card_text(c) for c in state.board]
    if len(board)!=BOARD_COUNTS[state.street] or len(set(board))!=len(board):
        raise UnsupportedSolverState('Board does not match the decision street.')
    if state.pot<=0 or state.small_blind<=0 or state.big_blind<=state.small_blind:
        raise UnsupportedSolverState('Invalid pot or blinds.')
    if any(p.stack<0 or p.current_bet<0 or (p.status==PlayerStatus.ALL_IN and p.stack!=0) for p in state.players):
        raise UnsupportedSolverState('Invalid stack or street commitment.')
    # These are real engine snapshots, not an invented reconstruction of a final result.
    if set(state.contributions)!=set(ids) or any(c<0 for c in state.contributions.values()) or sum(state.contributions.values())!=state.pot:
        raise UnsupportedSolverState('Complete contributions matching the pot are required.')
    if any(state.contributions[p.id]<p.current_bet for p in state.players):
        raise UnsupportedSolverState('Street commitment exceeds total contributions.')
    order={Street.PREFLOP:0,Street.FLOP:1,Street.TURN:2,Street.RIVER:3}
    last=0
    for action in state.history:
        if action.player_id not in ids or action.street not in order or not last<=order[action.street]<=order[state.street]:
            raise UnsupportedSolverState('History includes an invalid actor, street or future action.')
        if action.action not in {'small_blind','big_blind','check','call','bet','raise','fold'} or (action.amount is not None and action.amount<0):
            raise UnsupportedSolverState('Unsupported public action.')
        last=order[action.street]
    # Postflop order begins left of the button, including when only two remain
    # from a larger original table. Positions are never guessed from player names.
    button=ids.index(state.dealer_player_id)
    clockwise=ids[button+1:]+ids[:button+1]
    postflop_order=[pid for pid in clockwise if any(p.id==pid for p in active)]
    ranges=RangeService()
    players=[]
    for seat,p in enumerate(state.players):
        public={'id':p.id,'seat':seat,'position':p.position,'status':p.status.value,'stack':p.stack,'street_committed':p.current_bet,'total_committed':state.contributions[p.id]}
        if p.status!=PlayerStatus.FOLDED:
            inferred=ranges.infer_public(state,p.id)
            maximum=max(c.weight for c in inferred.combos)
            public['range']=[{'cards':card_text(c.cards[0])+card_text(c.cards[1]),'weight':c.weight/maximum} for c in inferred.combos]
        players.append(public)
    payload={'schema_version':1,'street':state.street.value,'board':board,'pot':state.pot,'small_blind':state.small_blind,'big_blind':state.big_blind,'button_id':state.dealer_player_id,'actor_id':state.current_player_id,'dealt_player_count':len(ids),'live_player_count':len(active),'postflop_order':postflop_order,'players':players,'history':[{'player_id':a.player_id,'action':a.action,'amount_added':a.amount,'street':a.street.value} for a in state.history], 'range_model':'public_action_heuristic_v1','assumptions':['Ranges use public actions and board only; no player hole cards are read.','Weights are heuristic, not calibrated solver frequencies.','Folded hand card-bunching is not modelled.','No rake or tournament ICM is modelled.','History amounts are chips ADDED, not raise-to totals.']}
    payload['information_key']=sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return payload


def solver_availability(snapshot: dict) -> dict:
    """Only verified local capabilities are advertised; candidates stay disabled."""
    count=snapshot['live_player_count']
    return {'required_live_players':count,'required_street':snapshot['street'],'configured_provider':None,'can_solve':False,'reason':'No licensed production solver is configured.','local_prototype':{'name':'TexasSolver','max_live_players':2,'streets':['river'],'matches_player_count':count==2,'scope':'Synthetic offline river probe only; no automatic live-hand integration.'},'multiway_candidate':{'name':'MonkerSolver','status':'Vendor advertises multiway support; API, commercial hosting rights and actual 2–6 player resource tests unverified.'}}
