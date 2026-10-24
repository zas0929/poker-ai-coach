"""Exact split selection with indexed history supports and cached row deltas.
Q arithmetic, iteration order and tie thresholds match frozen propose_split.
"""
from collections import defaultdict
from research.strategy_abstraction import StrategyView


def propose_split_indexed(game,mapping,records,max_groups_per_seat,max_strategy_rows):
    base=len(StrategyView(game,mapping).keys)
    supports=defaultdict(set);members=defaultdict(list);labels=[]
    for seat,hand,history in game.keys:supports[(seat,hand)].add(history)
    for seat,rows in enumerate(mapping):
        labels.append(set(rows.values()))
        for hand,label in rows.items():members[(seat,label)].append(hand)
    bygroup=defaultdict(list)
    for (seat,hand,history),record in records.items():bygroup[(seat,mapping[seat][hand],history)].append((hand,record))
    row_cache={};best=None
    for (seat,label,history),items in sorted(bygroup.items()):
        if len(labels[seat])>=max_groups_per_seat or len(items)<2:continue
        items=sorted(items);count=len(items[0][1]['q'])
        total=[sum(r['q'][a] for _,r in items) for a in range(count)]
        choices={hand:max(range(count),key=lambda a:r['q'][a]) for hand,r in items}
        for action in sorted(set(choices.values())):
            left=[hand for hand,_ in items if choices[hand]==action]
            if len(left)==len(items):continue
            leftset=set(left);lq=[sum(r['q'][a] for h,r in items if h in leftset) for a in range(count)]
            rq=[total[a]-lq[a] for a in range(count)]
            score=max(lq)+max(rq)-max(total)
            if score<=1e-10:continue
            cache_key=(seat,label,tuple(left))
            if cache_key not in row_cache:
                lh=set();rh=set()
                for hand in members[(seat,label)]:
                    (lh if hand in leftset else rh).update(supports[(seat,hand)])
                # One extra strategy row exactly where BOTH new groups occur.
                row_cache[cache_key]=base+len(lh & rh)
            rows=row_cache[cache_key]
            if rows>max_strategy_rows:continue
            if best is None or score>best['priority_chips']+1e-12:
                best={'seat':seat,'history':history,'group':label,'split_members':left,
                      'priority_chips':score,'grouped_strategy_rows':rows}
    if best is None:return None
    seat=best['seat'];label=best['group'];candidate=[dict(m) for m in mapping]
    suffix=0;new=label+'/split'+str(suffix)
    while new in labels[seat]:suffix+=1;new=label+'/split'+str(suffix)
    for hand in best['split_members']:candidate[seat][hand]=new
    return {'mapping':candidate,**best}
