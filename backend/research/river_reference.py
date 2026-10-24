"""Exact best-response check for the probe's small, two-player river trees.
Each response chooses with its own cards and action history only; it cannot see
its opponent's hand. Bet/raise strings in TexasSolver exports are added chips,
NOT the application's raise-to convention. Player 0 is IP, player 1 is OOP.
"""
from app.models.poker import Card, Rank, Suit
from app.services.hand_evaluator import HandEvaluator

SUITS=dict(c=Suit.CLUBS,d=Suit.DIAMONDS,h=Suit.HEARTS,s=Suit.SPADES)
def cards(text):
    return [Card(rank=Rank(text[i]),suit=SUITS[text[i+1]]) for i in range(0,len(text),2)]
def row(node, hand):
    rows=node['strategy']['strategy']
    return rows.get(hand,rows.get(hand[2:]+hand[:2]))

def check_solution(spec, tree):
    ranges=[spec['ip'],spec['oop']]; evaluator=HandEvaluator();board=cards(''.join(spec['board']))
    scores={combo:evaluator.score([*cards(combo),*board]) for side in ranges for combo,_ in side}
    matchups=[(a,b,wa*wb) for a,wa in ranges[0] for b,wb in ranges[1] if not set((a[:2],a[2:])).intersection((b[:2],b[2:]))]
    total=sum(w for _,_,w in matchups)
    if total<=0: raise ValueError('No possible matchup.')
    def payoff(me, own, opponents, invested, winner=None):
        value=0
        for other,weight in opponents:
            if winner is None:
                a,b=scores[own],scores[other]
                share=.5 if a==b else float(a>b)
            else: share=float(winner==me)
            value+=weight*(share*(spec['pot']+sum(invested))-spec['pot']/2-invested[me])
        return value
    def visit(node,me,own,opponents,invested,best_response):
        if not node or node.get('node_type')!='action_node':
            return payoff(me,own,opponents,invested)
        actor=node['player'];values=[];own_probs=row(node,own) if actor==me else None
        if actor==me and own_probs is None:raise ValueError('Missing own hand in strategy.')
        for index,action in enumerate(node['actions']):
            weighted=opponents
            if actor!=me:
                weighted=[]
                for other,weight in opponents:
                    probs=row(node,other)
                    if probs is None:raise ValueError('Missing opponent hand in strategy.')
                    weighted.append((other,weight*probs[index]))
            next_invested=list(invested)
            if action=='FOLD': value=payoff(me,own,weighted,invested,winner=1-actor)
            else:
                if action=='CALL': next_invested[actor]=max(invested)
                elif action.startswith(('BET ','RAISE ')):next_invested[actor]+=float(action.split()[1])
                elif action!='CHECK':raise ValueError('Unsupported action.')
                if max(next_invested)>spec['stack']+1e-6:raise ValueError('Tree exceeds effective stack.')
                value=visit(node.get('childrens',{}).get(action,{}),me,own,weighted,next_invested,best_response)
            values.append(value)
        if actor!=me:return sum(values)
        if best_response:return max(values)
        return sum(p*v for p,v in zip(own_probs,values))
    profile=[];best=[]
    for me in (0,1):
        policy=br=0
        for own,_ in ranges[me]:
            opponents=[(b if me==0 else a,w/total) for a,b,w in matchups if (a if me==0 else b)==own]
            if not opponents:continue
            policy+=visit(tree,me,own,opponents,[0,0],False)
            br+=visit(tree,me,own,opponents,[0,0],True)
        profile.append(policy);best.append(br)
    if abs(sum(profile))>1e-5:raise ValueError('Reference payoffs are not zero-sum.')
    gap=sum(best)/(2*spec['pot'])*100
    if gap < -1e-5:raise ValueError('Invalid best response bound.')
    return {'strategy_payoff_ip_oop_chips':[round(v,6) for v in profile], 'independent_exploitability_percent_pot':round(max(0,gap),8), 'legal_joint_matchups':len(matchups)}
