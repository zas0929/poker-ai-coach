"""Replay every explicit tree branch through the production engine as an oracle.
The solver's settlement and betting tree do not call the engine themselves.
This checker is for bounded research fixtures only, not a production adapter.
"""
from app.models.poker import ActionType,HandState,Player,PlayerStatus,Street
from app.services.poker_engine import PokerEngine
from research.river_reference import cards

def compare_every_path(game):
    """Independent game-engine execution, including each private deal and payout."""
    engine=PokerEngine();visited=0;leaves=0
    for d,(texts,_,_) in enumerate(game.deals):
        state=HandState(hand_id='sidepot-control',street=Street.RIVER,pot=game.pot,
                        small_blind=1,big_blind=game.min_bet,board=cards(''.join(game.board)),
                        players=[Player(id=str(i),name=str(i),stack=game.stacks[i],position='',
                                        status=PlayerStatus.ACTIVE if game.stacks[i] else PlayerStatus.ALL_IN,
                                        cards=cards(texts[i])) for i in range(game.n)],
                        current_player_id=str(game.root.actor) if game.root.actor!=-1 else None,
                        dealer_player_id=str(game.dealer),last_full_raise=game.min_bet,
                        contributions={str(i):v for i,v in enumerate(game.initial_contributions)})
        def visit(node,state):
            nonlocal visited,leaves
            visited+=1
            if node.actor==-1:
                leaves+=1
                if state.result is None:engine.advance(state)
                for i,player in enumerate(state.players):
                    expected=game.utilities[(id(node),d)][i]
                    actual=player.stack-game.stacks[i]-game.initial_contributions[i]
                    if abs(expected-actual)>1e-8:
                        raise AssertionError((node.history,i,expected,actual))
                if sum(p.stack for p in state.players)!=sum(game.stacks)+game.pot:
                    raise AssertionError('Conservation failure')
                return
            if state.current_player_id!=str(node.actor):
                raise AssertionError((node.history,node.actor,state.current_player_id))
            for action,child in zip(node.actions,node.children):
                parts=action.split();next_state=state.model_copy(deep=True)
                engine.apply_action(next_state,str(node.actor),ActionType(parts[0].lower()),
                                    int(parts[1]) if len(parts)>1 else None)
                visit(child,next_state)
        visit(game.root,state)
    return {'node_deal_visits':visited,'terminal_deal_checks':leaves}

