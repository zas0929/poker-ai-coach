"""Independent public-action replay of a single river round; no private cards."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RiverCursor:
    history: tuple
    invested: tuple
    alive: tuple
    pending: tuple
    current: int
    increment: int
    acted: tuple
    raises: int


def replay_river(stacks,dealer,min_bet,folded,actions):
    n=len(stacks);actions=tuple(tuple(a) for a in actions)
    if len(actions)>128:raise ValueError('At most 128 observed river actions supported.')
    river_folders=[]
    for event in actions:
        if len(event)!=3 or type(event[0]) is not int or not 0<=event[0]<n or event[1] not in ('check','fold','call','bet','raise'):
            raise ValueError('Invalid observed river action.')
        if event[1]=='fold':river_folders.append(event[0])
    if len(set(river_folders))!=len(river_folders) or set(river_folders)-set(folded):
        raise ValueError('Observed folds must match final folded seats.')
    initial_folded=set(folded)-set(river_folders)
    alive=tuple(p for p in range(n) if p not in initial_folded)
    paid=[0]*n;acted=[None]*n;current=0;increment=min_bet;raises=0;history=[]
    pending=tuple((dealer+i)%n for i in range(1,n+1) if (dealer+i)%n in alive)
    def normalized(queue):
        funded=tuple(p for p in alive if paid[p]<stacks[p])
        queue=tuple(p for p in queue if p in funded)
        if len(alive)==1 or not queue or (len(funded)==1 and paid[funded[0]]>=current):return ()
        return queue
    for actor,action,added in actions:
        pending=normalized(pending)
        if not pending or pending[0]!=actor:raise ValueError('Observed action is out of turn or after round closed.')
        remaining=stacks[actor]-paid[actor];owed=current-paid[actor]
        if action in ('check','fold'):
            if added is not None and (type(added) is not int or added!=0):raise ValueError('Check/fold cannot add chips.')
            if action=='check' and owed:raise ValueError('Cannot check facing a bet.')
            if action=='fold':alive=tuple(p for p in alive if p!=actor)
            else:acted[actor]=current
            pending=pending[1:];label=action.upper()
        elif action=='call':
            if not owed or type(added) is not int or added!=min(remaining,owed):raise ValueError('Call amount added does not match public outstanding bet.')
            paid[actor]+=added;acted[actor]=current;pending=pending[1:];label='CALL'
        else:
            if (action=='bet')!=(current==0):raise ValueError('Bet/raise does not match public betting state.')
            funded=[p for p in alive if paid[p]<stacks[p]]
            reopened=acted[actor] is None or current-acted[actor]>=increment
            if len(funded)<2 or (current and not reopened):raise ValueError('Observed raise is not reopened or has no funded opponent.')
            if type(added) is not int or not 0<added<=remaining:raise ValueError('Invalid chips added for wager.')
            total=paid[actor]+added;minimum=min_bet if not current else current+increment
            if total<=current or (total<minimum and total!=stacks[actor]):raise ValueError('Observed wager is below the legal minimum.')
            delta=total-current;paid[actor]=total;increment=max(increment,delta)
            raises+=int(current>0);current=total;acted[actor]=current
            pending=tuple((actor+i)%n for i in range(1,n) if (actor+i)%n in alive and paid[(actor+i)%n]<stacks[(actor+i)%n])
            label=action.upper()+' '+str(total)
        history.append((actor,label))
    pending=normalized(pending)
    if set(alive)!=set(range(n))-set(folded):raise ValueError('Final live seats disagree with observed folds.')
    return RiverCursor(tuple(history),tuple(paid),alive,pending,current,increment,tuple(acted),raises)
