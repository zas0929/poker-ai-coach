"""Deterministic engine -> public snapshot -> bounded tree transport controls.
These deliberately tiny selected ranges do not validate coaching quality.
"""
import argparse
import json
import sys
from app.models.poker import ActionType,Street
from app.services.poker_engine import PokerEngine
from app.services.solver_snapshot import prepare_solver_snapshot
from research.custom_river import demo_ranges
from research.river_reference import cards
from research.river_snapshot import build_river_from_snapshot
from research.sidepot_reference import compare_every_path


def control(n,mode='plain'):
    engine=PokerEngine()
    state=engine.start_hand(player_count=n,starting_stacks=[30,100,200] if mode=='prior_sidepot' else None)
    board=['2c','4d','7h','9s','Jc']
    # Deterministic test setup only; the adapter never receives these holdings.
    for p,r in zip(state.players,demo_ranges(n)):p.cards=cards(r[0][0])
    used={(c.rank,c.suit) for p in state.players for c in p.cards+cards(''.join(board))}
    state._deck=[c for c in engine._create_deck() if (c.rank,c.suit) not in used]+list(reversed(cards(''.join(board))))
    if mode=='prior_sidepot':
        engine.apply_action(state,'hero',ActionType.RAISE,30)
        engine.apply_action(state,'villain',ActionType.RAISE,60)
        engine.apply_action(state,'villain_2',ActionType.CALL)
    folded=False
    while state.street!=Street.RIVER:
        if state.current_player_id is None:engine.advance(state)
        elif mode=='folded' and not folded and state.street==Street.FLOP:
            engine.apply_action(state,state.current_player_id,ActionType.FOLD);folded=True
        else:engine.apply_action(state,state.current_player_id,ActionType.CALL if state.betting.call_amount else ActionType.CHECK)
    return prepare_solver_snapshot(state)


def select(snapshot):
    used=set(snapshot['board']);chosen={}
    for p in snapshot['players']:
        if p['status']=='folded':continue
        text=next(c['cards'] for c in p['range'] if not used.intersection((c['cards'][:2],c['cards'][2:])))
        chosen[p['id']]=[text];used.update((text[:2],text[2:]))
    return chosen


def benchmark(iterations=20):
    rows=[]
    for n,mode in [(n,'plain') for n in range(2,7)]+[(4,'folded'),(3,'prior_sidepot')]:
        snapshot=control(n,mode);chosen=select(snapshot)
        game,meta=build_river_from_snapshot(snapshot,chosen,bet_sizes=(10,),raise_sizes=(20,),max_raises=1)
        checks=compare_every_path(game)
        metrics=game.measure(game.train(iterations,method='cfr_plus'))
        rows.append({'players':n,'scenario':mode,'metadata':meta,'selected_hands':chosen,
                     'board':game.board,'pot':game.pot,'stacks':game.stacks,'prior_contributions':game.initial_contributions,
                     'bet_sizes':[10],'raise_sizes':[20],'max_raises':1,'public_nodes':len(game.nodes),
                     'joint_deals':len(game.deals),'engine_comparison':checks,'metrics':metrics})
        print(f'{n} {mode}: {checks}',file=sys.stderr,flush=True)
    return {'iterations':iterations,'method':'cfr_plus',
            'scope':'Seven deterministic public snapshot transport controls. One explicitly selected public hand per live seat. Not full-range coaching quality validation.',
            'results':rows,'terminal_deal_checks':sum(r['engine_comparison']['terminal_deal_checks'] for r in rows)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--iterations',type=int,default=20)
    args=parser.parse_args();print(json.dumps(benchmark(args.iterations),indent=2))
