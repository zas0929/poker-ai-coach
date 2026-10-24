"""Original, bounded multi-player river CFR experiment; NEVER a production GTO claim.

One bet size, no raises, equal stacks, one betting round, explicit small ranges.
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
    def __init__(self, board, ranges, pot=100, bet=50, stack=100):
        n=len(ranges)
        if not 2<=n<=6 or len(board)!=5 or len(set(board))!=5 or not all(re.fullmatch(r'[2-9TJQKA][cdhs]', c) for c in board):
            raise ValueError('Two to six players and five distinct river cards required.')
        board_cards=cards(''.join(board))
        if len(board_cards)!=5:raise ValueError('Invalid board.')
        if any(type(v) is not int or not 0<v<=10000 for v in (pot,bet,stack)) or bet>stack:
            raise ValueError('Positive integer pot/bet/stack, bet <= equal stack required.')
        if math.prod(len(r) for r in ranges)>64 or any(not r for r in ranges):
            raise ValueError('At most 64 raw joint combinations; ranges are never silently truncated.')
        self.n=n;self.pot=pot;self.bet=bet;self.ranges=ranges;self.nodes=[]
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
        for lineup in itertools.product(*ranges):
            texts=tuple(c for c,_ in lineup);keys=[t[i:i+2] for t in texts for i in (0,2)]
            if len(keys)!=len(set(keys)):continue
            self.deals.append((texts,math.prod(w for _,w in lineup),tuple(scores[t] for t in texts)))
        total=sum(w for _,w,_ in self.deals)
        if not math.isfinite(total) or total<=0:raise ValueError('No positive compatible joint deal.')
        self.deals=[(t,w/total,s) for t,w,s in self.deals]
        def responses(history, pending, alive, invested):
            if len(alive)==1 or not pending:return terminal(history,alive,invested)
            actor=pending[0]
            called=list(invested);called[actor]=bet
            return decision(actor,history,('FOLD','CALL'),(
                responses(history+((actor,'FOLD'),),pending[1:],tuple(p for p in alive if p!=actor),invested),
                responses(history+((actor,'CALL'),),pending[1:],alive,tuple(called))))
        def opening(actor,history):
            if actor==n:return terminal(history,tuple(range(n)),(0,)*n)
            invested=[0]*n;invested[actor]=bet
            return decision(actor,history,('CHECK',f'BET {bet}'),(
                opening(actor+1,history+((actor,'CHECK'),)),
                responses(history+((actor,f'BET {bet}'),),tuple(range(actor+1,n))+tuple(range(actor)),tuple(range(n)),tuple(invested))))
        def decision(actor,history,actions,children):
            node=Node(actor,history,actions,children);self.nodes.append(node);return node
        def terminal(history,alive,invested):
            node=Node(-1,history,invested=invested,alive=alive);self.nodes.append(node);return node
        self.root=opening(0,())
        self.utilities={}
        for node in self.nodes:
            if node.actor!=-1:continue
            for index,(_,_,scores_) in enumerate(self.deals):
                best=max(scores_[p] for p in node.alive)
                winners=[p for p in node.alive if scores_[p]==best]
                award=(pot+sum(node.invested))/len(winners)
                values=tuple((award if p in winners else 0)-node.invested[p]-pot/n for p in range(n))
                if abs(sum(values))>1e-7:raise ValueError('Payoffs must be zero-sum.')
                self.utilities[(id(node),index)]=values
        # An information set contains only the acting player's cards and public history.
        self.keys={(node.actor,texts[node.actor],node.history) for node in self.nodes if node.actor!=-1 for texts,_,_ in self.deals}

    def key(self,node,deal):return (node.actor,self.deals[deal][0][node.actor],node.history)

    def train(self, iterations=200, method='cfr'):
        if method not in ('cfr', 'cfr_plus'):
            raise ValueError('Choose cfr or cfr_plus.')
        if method == 'cfr_plus':
            return self._train_plus(iterations)
        return self._train_classic(iterations)

    def _train_classic(self, iterations):
        if type(iterations) is not int or not 1<=iterations<=2000:raise ValueError('1–2000 iterations required.')
        regrets={k:[0.,0.] for k in self.keys};average={k:[0.,0.] for k in self.keys}
        for _ in range(iterations):
            # Freeze the policy for the entire iteration, including all chance deals.
            policy={k:([max(0,v)/sum(max(0,x) for x in r) for v in r] if any(x>0 for x in r) else [.5,.5]) for k,r in regrets.items()}
            delta={k:[0.,0.] for k in self.keys}
            def visit(node,deal,reach,chance):
                if node.actor==-1:return self.utilities[(id(node),deal)]
                actor=node.actor;key=self.key(node,deal);strategy=policy[key];children=[]
                for a,child in enumerate(node.children):
                    next_reach=list(reach);next_reach[actor]*=strategy[a]
                    children.append(visit(child,deal,next_reach,chance))
                value=tuple(sum(strategy[a]*children[a][p] for a in range(2)) for p in range(self.n))
                counterfactual=chance*math.prod(reach[p] for p in range(self.n) if p!=actor)
                for a in range(2):
                    delta[key][a]+=counterfactual*(children[a][actor]-value[actor])
                    average[key][a]+=chance*reach[actor]*strategy[a]
                return value
            for deal,(_,chance,_) in enumerate(self.deals):visit(self.root,deal,[1.]*self.n,chance)
            for key in regrets:
                for a in range(2):regrets[key][a]+=delta[key][a]
        return {k:[v/sum(row) for v in row] if sum(row)>0 else [.5,.5] for k,row in average.items()}

    def _train_plus(self, iterations):
        """Alternating regret-matching+ updates with linear policy averaging.

        Each player's policy is frozen across ALL compatible chance deals before
        its regrets are clipped. Other players update only on their own pass.
        This is not a convergence guarantee for multi-player games.
        """
        if type(iterations) is not int or not 1<=iterations<=2000:
            raise ValueError('1–2000 iterations required.')
        regrets={k:[0.,0.] for k in self.keys};average={k:[0.,0.] for k in self.keys}
        policy={k:[.5,.5] for k in self.keys}
        # Cache information-set keys so recursive traversal does not rebuild histories.
        keys={(id(node),d):self.key(node,d) for node in self.nodes if node.actor!=-1 for d in range(len(self.deals))}
        for iteration in range(1,iterations+1):
            for target in range(self.n):
                delta={k:[0.,0.] for k in self.keys if k[0]==target}
                def visit(node,deal,reach,chance):
                    if node.actor==-1:return self.utilities[(id(node),deal)][target]
                    actor=node.actor;key=keys[(id(node),deal)];strategy=policy[key]
                    values=[]
                    for a,child in enumerate(node.children):
                        next_reach=list(reach);next_reach[actor]*=strategy[a]
                        values.append(visit(child,deal,next_reach,chance))
                    value=strategy[0]*values[0]+strategy[1]*values[1]
                    if actor==target:
                        counterfactual=chance*math.prod(reach[p] for p in range(self.n) if p!=actor)
                        for a in range(2):
                            delta[key][a]+=counterfactual*(values[a]-value)
                            average[key][a]+=iteration*chance*reach[actor]*strategy[a]
                    return value
                for deal,(_,chance,_) in enumerate(self.deals):
                    visit(self.root,deal,[1.]*self.n,chance)
                for key,changes in delta.items():
                    r=regrets[key]
                    for a in range(2):r[a]=max(0.,r[a]+changes[a])
                    total=sum(r);policy[key]=[v/total for v in r] if total else [.5,.5]
        return {k:[v/sum(row) for v in row] if sum(row)>0 else [.5,.5] for k,row in average.items()}

    def measure(self,policy):
        """Exact BR at each own-hand/public-history information set, never per deal."""
        if set(policy)!=self.keys or any(len(r)!=2 or any(not math.isfinite(p) or not 0<=p<=1 for p in r) or abs(sum(r)-1)>1e-8 for r in policy.values()):
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
        return {'policy_payoffs':values,'best_response_payoffs':best,'unilateral_gains':gains,'nash_conv_chips':sum(gains),'max_unilateral_gain_pct_pot':max(gains)/self.pot*100}


def demo_ranges(n):
    # Distinct synthetic hands with a little private uncertainty, not player models.
    hands=[('AhAd','3h3d'),('KhKd','5h5d'),('QhQd','6h6d'),('ThTd','8h8d'),('AcKc','7c7s'),('QcTc','9c9d')]
    return [[(a,1),(b,1)] for a,b in hands[:n]]

if __name__=='__main__':
    import argparse,json,platform
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--iterations',type=int,default=100);parser.add_argument('--method',choices=['cfr','cfr_plus'],default='cfr_plus');args=parser.parse_args()
    results=[]
    for n in range(2,7):
        started=time.perf_counter();game=RiverGame(['2c','4d','7h','9s','Jc'],demo_ranges(n));uniform={k:[.5,.5] for k in game.keys}
        before=game.measure(uniform);policy=game.train(args.iterations,method=args.method);after=game.measure(policy)
        results.append({'players':n,'joint_deals':len(game.deals),'public_nodes':len(game.nodes),'information_sets':len(game.keys),'iterations':args.iterations,'seconds':round(time.perf_counter()-started,3),'before':before,'after':after,'root_policy':[{'hand':combo,'actions':game.root.actions,'probabilities':policy[(0,combo,())]} for combo,_ in game.ranges[0]]})
    print(json.dumps({'method':args.method,'scope':'Restricted synthetic river game. No raises, side pots or future streets. Not production GTO.','platform':platform.platform(),'results':results},indent=2))
