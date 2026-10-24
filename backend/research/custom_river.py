"""Original, bounded multi-player river CFR experiment; NEVER a production GTO claim.

Explicit bet/raise totals, bounded raises, unequal stacks/side pots, one betting round, small ranges.
For 3+ players CFR is an experiment, without the 2-player zero-sum convergence
claim. Exact unilateral best responses measure the resulting policy instead.
"""
import itertools
import math
import re
import time
from dataclasses import dataclass
from app.services.hand_evaluator import HandEvaluator
from research.river_reference import cards

@dataclass
class Node:
    actor: int
    history: tuple
    actions: tuple = ()
    children: tuple = ()
    invested: tuple = ()
    alive: tuple = ()

class RiverGame:
    def __init__(self, board, ranges, pot=100, bet=50, stack=100, *,
                 bet_sizes=None, raise_sizes=(), max_raises=0, min_bet=1, max_nodes=20000,
                 stacks=None, initial_contributions=None, dealer=None, folded=(), max_joint_combos=64, utility_storage='dict', river_actions=()):
        n=len(ranges)
        if not 2<=n<=6 or len(board)!=5 or len(set(board))!=5 or not all(re.fullmatch(r'[2-9TJQKA][cdhs]', c) for c in board):
            raise ValueError('Two to six players and five distinct river cards required.')
        self.river_actions=tuple(tuple(a) for a in river_actions)
        self.folded=tuple(folded)
        if any(type(p) is not int or not 0<=p<n for p in self.folded) or len(set(self.folded))!=len(self.folded) or n-len(self.folded)<2:
            raise ValueError('Distinct folded seat indices and at least two live seats required.')
        self.live=tuple(p for p in range(n) if p not in self.folded)
        if any(ranges[p] for p in self.folded):
            raise ValueError('Folded seats must have empty ranges; hidden folded cards are not modelled.')
        board_cards=cards(''.join(board))
        if len(board_cards)!=5:raise ValueError('Invalid board.')
        if type(pot) is not int or not 0<pot<=10000:
            raise ValueError('Positive integer pot up to 10000 required.')
        if stacks is None:
            if type(stack) is not int or not 0<stack<=10000:
                raise ValueError('Positive integer equal stack required.')
            stacks=(stack,)*n
        self.stacks=tuple(stacks)
        if len(self.stacks)!=n or any(type(v) is not int or not 0<=v<=10000 for v in self.stacks):
            raise ValueError('One integer remaining stack (0–10000) per seat required.')
        ceiling=max(self.stacks[p] for p in self.live)
        if type(min_bet) is not int or not 1<=min_bet<=10000:
            raise ValueError('Positive integer minimum bet up to 10000 required.')
        self.dealer=n-1 if dealer is None else dealer
        if type(self.dealer) is not int or not 0<=self.dealer<n:
            raise ValueError('Dealer must be a seat index.')
        from research.river_replay import replay_river
        self.root_state=replay_river(self.stacks,self.dealer,min_bet,self.folded,self.river_actions)
        river_folders={a[0] for a in self.river_actions if a[1]=='fold'}
        initial_live=set(self.live)|river_folders
        self.integer_payouts=initial_contributions is not None
        self.initial_contributions=tuple(initial_contributions) if self.integer_payouts else (pot/n,)*n
        if self.integer_payouts:
            if len(self.initial_contributions)!=n or any(type(v) is not int or v<0 for v in self.initial_contributions) or sum(self.initial_contributions)!=pot:
                raise ValueError('Nonnegative integer prior contributions must sum to pot.')
            highest=max(self.initial_contributions)
            if any(chips>0 and prior!=highest for p,(chips,prior) in enumerate(zip(self.stacks,self.initial_contributions)) if p in initial_live):
                raise ValueError('Funded players must have matched prior streets; lower contributors must be all-in.')
        if type(max_raises) is not int or not 0<=max_raises<=3:
            raise ValueError('0–3 raises per betting line required.')
        if type(max_nodes) is not int or not 1<=max_nodes<=20000:
            raise ValueError('1–20000 public nodes required.')
        def sizes(values):
            values=tuple(values)
            if len(values)>4 or len(set(values))!=len(values) or any(type(v) is not int or not 1<=v<=(ceiling or 10000) for v in values):
                raise ValueError('At most four distinct integer totals within largest remaining stack required.')
            return tuple(sorted(values))
        self.bet_sizes=sizes((bet,) if bet_sizes is None else bet_sizes)
        self.raise_sizes=sizes(raise_sizes)
        if not self.bet_sizes or any(v<min_bet and v not in tuple(self.stacks[p] for p in self.live) for v in self.bet_sizes):
            raise ValueError('Opening sizes must meet minimum bet (except short all-in).')
        self.max_raises=max_raises;self.stack=stack;self.min_bet=min_bet
        if type(max_joint_combos) is not int or not 1<=max_joint_combos<=4096:
            raise ValueError('Explicit joint-combo budget must be an integer from 1 to 4096.')
        self.max_joint_combos=max_joint_combos
        if math.prod(max(1,len(r)) for r in ranges)>max_joint_combos or any(not ranges[p] for p in self.live):
            raise ValueError(f'At most {max_joint_combos} raw joint combinations; ranges are never silently truncated.')
        self.board=tuple(board);self.n=n;self.pot=pot;self.bet=bet;self.ranges=ranges;self.nodes=[]
        evaluator=HandEvaluator();scores={}
        for r in ranges:
            seen=set()
            for text,weight in r:
                if not re.fullmatch(r'(?:[2-9TJQKA][cdhs]){2}',text):raise ValueError('Invalid hole cards.')
                pair=cards(text)
                key=frozenset(text[i:i+2] for i in (0,2))
                if len(text)!=4 or len(key)!=2 or key.intersection(board) or key in seen:
                    raise ValueError('Invalid, duplicate or board-blocked combo.')
                if not math.isfinite(weight) or weight<=0:raise ValueError('Positive finite weights required.')
                seen.add(key);scores[text]=evaluator.score([*pair,*board_cards])
        self.deals=[]
        for lineup in itertools.product(*(r if p in self.live else [(None,1)] for p,r in enumerate(ranges))):
            texts=tuple(c for c,_ in lineup);keys=[t[i:i+2] for t in texts if t is not None for i in (0,2)]
            if len(keys)!=len(set(keys)):continue
            self.deals.append((texts,math.prod(w for _,w in lineup),tuple(scores[t] if t is not None else None for t in texts)))
        total=sum(w for _,w,_ in self.deals)
        if not math.isfinite(total) or total<=0:raise ValueError('No positive compatible joint deal.')
        self.deals=[(t,w/total,s) for t,w,s in self.deals]
        def save(node):
            if len(self.nodes)>=max_nodes:
                raise ValueError('Public tree exceeds node budget; choose fewer sizes/raises.')
            self.nodes.append(node)
            return node
        def build(history, pending, alive, invested, current, increment, raises, acted):
            funded=tuple(p for p in alive if invested[p]<self.stacks[p])
            pending=tuple(p for p in pending if p in funded)
            if len(alive)==1 or not pending or (len(funded)==1 and invested[funded[0]]>=current):
                return save(Node(-1,history,invested=invested,alive=alive))
            actor=pending[0];rest=pending[1:];actions=[];children=[]
            def add(action, next_pending, next_alive, next_invested,
                    next_current=current, next_increment=increment, next_raises=raises):
                actions.append(action)
                next_acted=list(acted)
                if action!='FOLD':next_acted[actor]=next_current
                children.append(build(history+((actor,action),),next_pending,next_alive,
                                      next_invested,next_current,next_increment,next_raises,tuple(next_acted)))
            facing=current>invested[actor]
            if facing:
                add('FOLD',rest,tuple(p for p in alive if p!=actor),invested)
                called=list(invested);called[actor]=min(current,self.stacks[actor])
                add('CALL',rest,alive,tuple(called))
            else:
                add('CHECK',rest,alive,invested)
            # Clamp configured totals at the actor's all-in, then deduplicate.
            # Short raises reopen only after cumulative increases reach a full raise.
            reopened=acted[actor] is None or current-acted[actor]>=increment
            targets=self.bet_sizes if current==0 else (self.raise_sizes if raises<max_raises and reopened else ())
            if len(funded)<2:targets=()
            for total in sorted({min(v,self.stacks[actor]) for v in targets}):
                minimum=increment if current==0 else current+increment
                if total<=current or (total<minimum and total!=self.stacks[actor]):
                    continue
                paid=list(invested);paid[actor]=total
                responders=tuple((actor+offset)%n for offset in range(1,n)
                                 if (actor+offset)%n in funded)
                add(('BET ' if current==0 else 'RAISE ')+str(total),responders,alive,tuple(paid),
                    total,max(increment,total-current),raises+int(current>0))
            return save(Node(actor,history,tuple(actions),tuple(children),invested,alive))
        cursor=self.root_state
        # max_raises bounds future branches, not the already fixed public prefix.
        self.root=build(cursor.history,cursor.pending,cursor.alive,cursor.invested,cursor.current,cursor.increment,0,cursor.acted)
        self.decision_pot=pot+sum(cursor.invested)
        if len(self.nodes)*len(self.deals)>1000000:
            raise ValueError('Tree/deal product exceeds one million; reduce explicit ranges/tree.')
        if utility_storage not in ('dict','compact'):raise ValueError('Choose dict or compact utility storage.')
        self.utility_storage=utility_storage
        if utility_storage=='compact':
            from research.compact_utilities import CompactUtilities
            self.utilities=CompactUtilities(self.nodes,len(self.deals),n)
        else:self.utilities={}
        for node in self.nodes:
            if node.actor!=-1:continue
            for index,(_,_,scores_) in enumerate(self.deals):
                awards,_,_=self.settle(node,scores_)
                values=tuple(awards[p]-node.invested[p]-self.initial_contributions[p] for p in range(n))
                if abs(sum(values))>1e-7:raise ValueError('Payoffs must be zero-sum.')
                if utility_storage=='compact':self.utilities.put(node,index,values)
                else:self.utilities[(id(node),index)]=values
        # An information set contains only the acting player's cards and public history.
        self.keys={(node.actor,texts[node.actor],node.history) for node in self.nodes if node.actor!=-1 for texts,_,_ in self.deals}
        self.action_counts={(node.actor,texts[node.actor],node.history):len(node.actions)
                            for node in self.nodes if node.actor!=-1 for texts,_,_ in self.deals}

    def settle(self,node,scores):
        """Independent terminal accounting: return uncalled street chips, layer pots.

        Explicit integer prior contributions enable table-style odd-chip allocation.
        Legacy implicit equal pot funding retains fractional mathematical splits.
        Awards include refunds; neither refunds nor folded chips can win a side pot.
        """
        if node.actor!=-1:raise ValueError('Settlement requires a terminal node.')
        paid=list(node.invested);refunds=[0]*self.n
        order=sorted(range(self.n),key=lambda p:paid[p],reverse=True)
        high,second=order[:2]
        excess=paid[high]-paid[second]
        paid[high]-=excess;refunds[high]=excess
        totals=[self.initial_contributions[p]+paid[p] for p in range(self.n)]
        awards=list(refunds);pots=[];prior=0
        seats=[(self.dealer+i)%self.n for i in range(1,self.n+1)]
        for level in sorted(set(totals)-{0}):
            contributors=[p for p in range(self.n) if totals[p]>=level]
            amount=(level-prior)*len(contributors);prior=level
            eligible=[p for p in contributors if p in node.alive]
            if not eligible:raise ValueError('Pot without eligible player.')
            if pots and pots[-1]['eligible']==eligible:pots[-1]['amount']+=amount
            else:pots.append({'amount':amount,'eligible':eligible})
        for pot in pots:
            best=max(scores[p] for p in pot['eligible'])
            winners=[p for p in seats if p in pot['eligible'] and scores[p]==best]
            if self.integer_payouts:
                share,remainder=divmod(pot['amount'],len(winners))
                payouts={p:share+int(i<remainder) for i,p in enumerate(winners)}
            else:payouts={p:pot['amount']/len(winners) for p in winners}
            pot.update(winners=winners,awards=payouts)
            for p,value in payouts.items():awards[p]+=value
        if abs(sum(awards)-self.pot-sum(node.invested))>1e-7:
            raise ValueError('Settlement must conserve all chips.')
        return tuple(awards),tuple(refunds),pots

    def key(self,node,deal):return (node.actor,self.deals[deal][0][node.actor],node.history)

    def train(self, iterations=200, method='cfr'):
        if method not in ('cfr', 'cfr_plus', 'cfr_plus_indexed', 'cfr_plus_native'):
            raise ValueError('Choose cfr, cfr_plus, cfr_plus_indexed or cfr_plus_native.')
        if method == 'cfr_plus_native':
            from research.native_cfr import train_native
            return train_native(self,iterations)
        if method == 'cfr_plus_indexed':
            from research.indexed_cfr import train_indexed
            return train_indexed(self,iterations)
        if method == 'cfr_plus':
            return self._train_plus(iterations)
        return self._train_classic(iterations)

    def _train_classic(self, iterations):
        if type(iterations) is not int or not 1<=iterations<=2000:raise ValueError('1–2000 iterations required.')
        regrets={k:[0.]*m for k,m in self.action_counts.items()};average={k:[0.]*m for k,m in self.action_counts.items()}
        for _ in range(iterations):
            # Freeze the policy for the entire iteration, including all chance deals.
            policy={k:([max(0,v)/sum(max(0,x) for x in r) for v in r] if any(x>0 for x in r) else [1/len(r)]*len(r)) for k,r in regrets.items()}
            delta={k:[0.]*m for k,m in self.action_counts.items()}
            def visit(node,deal,reach,chance):
                if node.actor==-1:return self.utilities[(id(node),deal)]
                actor=node.actor;key=self.key(node,deal);strategy=policy[key];children=[]
                for a,child in enumerate(node.children):
                    next_reach=list(reach);next_reach[actor]*=strategy[a]
                    children.append(visit(child,deal,next_reach,chance))
                value=tuple(sum(strategy[a]*children[a][p] for a in range(len(strategy))) for p in range(self.n))
                counterfactual=chance*math.prod(reach[p] for p in range(self.n) if p!=actor)
                for a in range(len(strategy)):
                    delta[key][a]+=counterfactual*(children[a][actor]-value[actor])
                    average[key][a]+=chance*reach[actor]*strategy[a]
                return value
            for deal,(_,chance,_) in enumerate(self.deals):visit(self.root,deal,[1.]*self.n,chance)
            for key in regrets:
                for a in range(len(regrets[key])):regrets[key][a]+=delta[key][a]
        return {k:[v/sum(row) for v in row] if sum(row)>0 else [1/len(row)]*len(row) for k,row in average.items()}

    def _train_plus(self, iterations):
        """Alternating regret-matching+ updates with linear policy averaging.

        Each player's policy is frozen across ALL compatible chance deals before
        its regrets are clipped. Other players update only on their own pass.
        This is not a convergence guarantee for multi-player games.
        """
        if type(iterations) is not int or not 1<=iterations<=2000:
            raise ValueError('1–2000 iterations required.')
        regrets={k:[0.]*m for k,m in self.action_counts.items()};average={k:[0.]*m for k,m in self.action_counts.items()}
        policy={k:[1/m]*m for k,m in self.action_counts.items()}
        # Cache information-set keys so recursive traversal does not rebuild histories.
        keys={(id(node),d):self.key(node,d) for node in self.nodes if node.actor!=-1 for d in range(len(self.deals))}
        for iteration in range(1,iterations+1):
            for target in range(self.n):
                delta={k:[0.]*m for k,m in self.action_counts.items() if k[0]==target}
                def visit(node,deal,reach,chance):
                    if node.actor==-1:return self.utilities[(id(node),deal)][target]
                    actor=node.actor;key=keys[(id(node),deal)];strategy=policy[key]
                    values=[]
                    for a,child in enumerate(node.children):
                        next_reach=list(reach);next_reach[actor]*=strategy[a]
                        values.append(visit(child,deal,next_reach,chance))
                    value=sum(p*v for p,v in zip(strategy,values))
                    if actor==target:
                        counterfactual=chance*math.prod(reach[p] for p in range(self.n) if p!=actor)
                        for a in range(len(strategy)):
                            delta[key][a]+=counterfactual*(values[a]-value)
                            average[key][a]+=iteration*chance*reach[actor]*strategy[a]
                    return value
                for deal,(_,chance,_) in enumerate(self.deals):
                    visit(self.root,deal,[1.]*self.n,chance)
                for key,changes in delta.items():
                    r=regrets[key]
                    for a in range(len(r)):r[a]=max(0.,r[a]+changes[a])
                    total=sum(r);policy[key]=[v/total for v in r] if total else [1/len(r)]*len(r)
        return {k:[v/sum(row) for v in row] if sum(row)>0 else [1/len(row)]*len(row) for k,row in average.items()}

    def measure(self,policy):
        """Exact BR at each own-hand/public-history information set, never per deal."""
        if set(policy)!=self.keys or any(len(r)!=self.action_counts[k] or any(not math.isfinite(p) or not 0<=p<=1 for p in r) or abs(sum(r)-1)>1e-8 for k,r in policy.items()):
            raise ValueError('Complete normalized finite policy required.')
        def recurse(node,me,weights,best_response):
            if node.actor==-1:return sum(w*self.utilities[(id(node),d)][me] for d,w in weights)
            if node.actor==me:
                # Caller groups by the responder's own hand before traversal.
                strategy=policy[self.key(node,weights[0][0])]
                values=[recurse(child,me,weights,best_response) for child in node.children]
                return max(values) if best_response else sum(p*v for p,v in zip(strategy,values))
            return sum(recurse(child,me,[(d,w*policy[self.key(node,d)][a]) for d,w in weights],best_response) for a,child in enumerate(node.children))
        values=[];best=[]
        for me in range(self.n):
            groups={}
            for d,(texts,weight,_) in enumerate(self.deals):groups.setdefault(texts[me],[]).append((d,weight))
            values.append(sum(recurse(self.root,me,g,False) for g in groups.values()))
            best.append(sum(recurse(self.root,me,g,True) for g in groups.values()))
        gains=[max(0,b-v) for b,v in zip(best,values)]
        return {'policy_payoffs':values,'best_response_payoffs':best,'unilateral_gains':gains,'nash_conv_chips':sum(gains),'max_unilateral_gain_pct_pot':max(gains)/self.decision_pot*100}


def demo_ranges(n):
    # Distinct synthetic hands with a little private uncertainty, not player models.
    hands=[('AhAd','3h3d'),('KhKd','5h5d'),('QhQd','6h6d'),('ThTd','8h8d'),('AcKc','7c7s'),('QcTc','9c9d')]
    return [[(a,1),(b,1)] for a,b in hands[:n]]

if __name__=='__main__':
    import argparse,json,platform
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations',type=int,default=100)
    parser.add_argument('--method',choices=['cfr','cfr_plus','cfr_plus_indexed','cfr_plus_native'],default='cfr_plus')
    parser.add_argument('--players',type=int,nargs='+',default=list(range(2,7)))
    parser.add_argument('--bet-sizes',type=int,nargs='+',default=[50])
    parser.add_argument('--raise-sizes',type=int,nargs='*',default=[])
    parser.add_argument('--max-raises',type=int,default=0)
    parser.add_argument('--stack',type=int,default=100)
    parser.add_argument('--stacks',type=int,nargs='+')
    parser.add_argument('--pot',type=int,default=100)
    parser.add_argument('--initial-contributions',type=int,nargs='+')
    parser.add_argument('--min-bet',type=int,default=1)
    parser.add_argument('--max-joint-combos',type=int,default=64)
    parser.add_argument('--utility-storage',choices=['dict','compact'],default='dict')
    args=parser.parse_args()
    if (args.stacks is not None or args.initial_contributions is not None) and len(args.players)!=1:
        parser.error('Use one explicit --players N with --stacks/--initial-contributions.')
    results=[]
    for n in args.players:
        started=time.perf_counter()
        game=RiverGame(['2c','4d','7h','9s','Jc'],demo_ranges(n),stack=args.stack,pot=args.pot,
                       stacks=args.stacks,initial_contributions=args.initial_contributions,bet_sizes=args.bet_sizes,raise_sizes=args.raise_sizes,
                       max_raises=args.max_raises,min_bet=args.min_bet,max_joint_combos=args.max_joint_combos,utility_storage=args.utility_storage)
        uniform={k:[1/m]*m for k,m in game.action_counts.items()}
        before=game.measure(uniform);policy=game.train(args.iterations,method=args.method);after=game.measure(policy)
        results.append({'players':n,'stacks':game.stacks,'initial_contributions':game.initial_contributions,'integer_payouts':game.integer_payouts,'root_actor':game.root.actor,'joint_deals':len(game.deals),'public_nodes':len(game.nodes),'information_sets':len(game.keys),'iterations':args.iterations,'seconds':round(time.perf_counter()-started,3),'before':before,'after':after,'root_policy':[{'hand':combo,'actions':game.root.actions,'probabilities':policy[(game.root.actor,combo,game.root.history)]} for combo,_ in game.ranges[game.root.actor]] if game.root.actor!=-1 else []})
    print(json.dumps({'method':args.method,'bet_sizes':args.bet_sizes,'raise_sizes':args.raise_sizes,
                      'max_raises':args.max_raises,'max_joint_combos':args.max_joint_combos,'stack':args.stack,'min_bet':args.min_bet,
                      'scope':'Restricted synthetic river game with explicit sizes and raise cap. Unequal stacks and layered pots; no future streets. Not production GTO.',
                      'platform':platform.platform(),'results':results},indent=2))
