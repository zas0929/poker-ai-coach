"""Strict offline adapter from public schema-v1 snapshots to bounded river games.
Only start-of-river decisions are accepted. Never reads a HandState or holdings.
"""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from app.services.solver_snapshot import UnsupportedSolverState
from research.custom_river import RiverGame


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def combo_key(text):
    if not isinstance(text,str) or not re.fullmatch(r'(?:[2-9TJQKA][cdhs]){2}',text):
        raise UnsupportedSolverState('Invalid selected/public combo notation.')
    key=tuple(sorted((text[:2],text[2:])))
    if key[0]==key[1]:raise UnsupportedSolverState('A combo must contain two different cards.')
    return key


def build_river_from_snapshot(snapshot,selected_hands=None,*,bet_sizes=(50,),raise_sizes=(),max_raises=0,max_nodes=20000,max_joint_combos=64,utility_storage='dict'):
    try:
        return _build(snapshot,selected_hands,bet_sizes,raise_sizes,max_raises,max_nodes,max_joint_combos,utility_storage)
    except UnsupportedSolverState:
        raise
    except (KeyError,TypeError,IndexError,ValueError) as error:
        raise UnsupportedSolverState('Unsupported research input: '+str(error)) from error


def _build(snapshot,selected_hands,bet_sizes,raise_sizes,max_raises,max_nodes,max_joint_combos,utility_storage):
    payload={k:v for k,v in snapshot.items() if k!='information_key'}
    if snapshot['information_key']!=digest(payload):
        raise UnsupportedSolverState('Public snapshot information key does not match contents.')
    if type(snapshot['schema_version']) is not int or snapshot['schema_version']!=1 or snapshot['street']!='river':
        raise UnsupportedSolverState('Only schema-v1 river snapshots are supported.')
    players=snapshot['players'];n=len(players)
    ids=[p['id'] for p in players]
    if not 2<=n<=6 or any(not isinstance(pid,str) or not pid for pid in ids) or len(set(ids))!=n:
        raise UnsupportedSolverState('Two to six distinct public seat ids required.')
    if [p['seat'] for p in players]!=list(range(n)) or any(type(p['seat']) is not int for p in players):
        raise UnsupportedSolverState('Seats must retain their original clockwise indices.')
    if snapshot['dealt_player_count']!=n or snapshot['button_id'] not in ids:
        raise UnsupportedSolverState('Invalid original table size/button.')
    folded=[i for i,p in enumerate(players) if p['status']=='folded']
    live=[i for i in range(n) if i not in folded]
    if len(live)<2 or snapshot['live_player_count']!=len(live):
        raise UnsupportedSolverState('At least two live seats required.')
    for p in players:
        if p['status'] not in ('active','all_in','folded') or type(p['stack']) is not int or p['stack']<0:
            raise UnsupportedSolverState('Invalid public status/stack.')
        if (p['status']=='all_in' and p['stack']!=0) or (p['status']=='active' and p['stack']==0):
            raise UnsupportedSolverState('Stack does not match public status.')
        if type(p['street_committed']) is not int or p['street_committed']!=0:
            raise UnsupportedSolverState('Mid-river commitments are not supported; pass start of river.')
    if any(a['street']=='river' for a in snapshot['history']):
        raise UnsupportedSolverState('Mid-river history is not supported, even after a check/fold.')
    last=0;street_order={'preflop':0,'flop':1,'turn':2}
    for action in snapshot['history']:
        street=action['street'];amount=action['amount_added']
        if street not in street_order or street_order[street]<last or action['player_id'] not in ids or action['action'] not in ('small_blind','big_blind','check','call','bet','raise','fold'):
            raise UnsupportedSolverState('Invalid public history.')
        if amount is not None and (type(amount) is not int or amount<0):
            raise UnsupportedSolverState('History uses nonnegative integer amounts added.')
        last=street_order[street]
    if any(type(snapshot[k]) is not int for k in ('small_blind','big_blind')) or not 0<snapshot['small_blind']<snapshot['big_blind']:
        raise UnsupportedSolverState('Invalid public blinds.')
    dealer=ids.index(snapshot['button_id'])
    order=[(dealer+offset)%n for offset in range(1,n+1) if (dealer+offset)%n in live]
    if snapshot['postflop_order']!=[ids[i] for i in order]:
        raise UnsupportedSolverState('Public postflop order does not match original seats.')
    live_ids={ids[i] for i in live}
    if selected_hands is not None and (not isinstance(selected_hands,dict) or set(selected_hands)!=live_ids):
        raise UnsupportedSolverState('Explicit hand selection must cover exactly the live ids.')
    ranges=[];counts=[]
    for i,p in enumerate(players):
        if i in folded:
            if 'range' in p:raise UnsupportedSolverState('Folded seats must not supply private ranges.')
            ranges.append([]);counts.append({'id':p['id'],'public':0,'selected':0});continue
        public={}
        for row in p['range']:
            key=combo_key(row['cards']);weight=row['weight']
            if set(key).intersection(snapshot['board']) or key in public or type(weight) not in (int,float) or not math.isfinite(weight) or weight<=0:
                raise UnsupportedSolverState('Public combos must be unique with positive finite weights.')
            public[key]=(row['cards'],weight)
        chosen=list(public) if selected_hands is None else [combo_key(t) for t in selected_hands[p['id']]]
        if not chosen or len(set(chosen))!=len(chosen) or any(k not in public for k in chosen):
            raise UnsupportedSolverState('Selected hands must be distinct members of the public range.')
        ranges.append([public[k] for k in chosen])
        counts.append({'id':p['id'],'public':len(public),'selected':len(chosen)})
    spec={'board':snapshot['board'],'ranges':ranges,'pot':snapshot['pot'],
          'stacks':[p['stack'] for p in players],'initial_contributions':[p['total_committed'] for p in players],
          'dealer':dealer,'folded':folded,'bet_sizes':tuple(bet_sizes),'raise_sizes':tuple(raise_sizes),
          'max_raises':max_raises,'utility_storage':utility_storage,'max_joint_combos':max_joint_combos,'min_bet':snapshot['big_blind'],'max_nodes':max_nodes}
    game=RiverGame(**spec)
    if game.root.actor==-1 or ids[game.root.actor]!=snapshot['actor_id']:
        raise UnsupportedSolverState('Actor is not the first pending river decision; no reconstruction is guessed.')
    metadata={'source_information_key':snapshot['information_key'],'task_key':digest(spec),
              'seat_ids':ids,'actor_id':snapshot['actor_id'],'folded_seats':folded,
              'range_selection':'full_public' if selected_hands is None else 'explicit_subset',
              'range_counts':counts,'utility_storage':game.utility_storage,'max_joint_combos':game.max_joint_combos,'folded_card_bunching_modelled':False,
              'scope':'Offline start-of-river abstraction only; selected subsets are not full-range/GTO advice.'}
    return game,metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot_json',type=Path)
    parser.add_argument('--selected-hands',type=Path,help='JSON mapping every live id to explicit combo strings')
    parser.add_argument('--bet-sizes',type=int,nargs='+',default=[50])
    parser.add_argument('--raise-sizes',type=int,nargs='*',default=[])
    parser.add_argument('--max-raises',type=int,default=0)
    parser.add_argument('--iterations',type=int,default=200)
    parser.add_argument('--max-joint-combos',type=int,default=64)
    parser.add_argument('--utility-storage',choices=['dict','compact'],default='dict')
    parser.add_argument('--method',choices=['cfr_plus','cfr_plus_indexed','cfr_plus_native'],default='cfr_plus')
    args=parser.parse_args();raw=json.loads(args.snapshot_json.read_text())
    snapshot=raw.get('snapshot',raw)
    selected=json.loads(args.selected_hands.read_text()) if args.selected_hands else None
    game,metadata=build_river_from_snapshot(snapshot,selected,bet_sizes=args.bet_sizes,
                                          raise_sizes=args.raise_sizes,max_raises=args.max_raises,max_joint_combos=args.max_joint_combos,utility_storage=args.utility_storage)
    policy=game.train(args.iterations,method=args.method)
    root=game.root
    print(json.dumps({'metadata':metadata,'method':args.method,'iterations':args.iterations,
                      'public_nodes':len(game.nodes),'joint_deals':len(game.deals),'metrics':game.measure(policy),
                      'root_policy':[{'hand':hand,'actions':root.actions,'probabilities':policy[(root.actor,hand,())]}
                                     for hand,_ in game.ranges[root.actor]]},indent=2))
