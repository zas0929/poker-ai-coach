"""Versioned educational cash-game presets. No solver or equilibrium claim."""
from math import ceil
from app.services.range_service import RangeService
from app.services.betting_rules import betting_options, highest_bet

RANKS='23456789TJQKA'

def expand(text):
    result=set()
    for item in text.split():
        base=item.rstrip('+'); hi,lo=base[:2]
        if item.endswith('+'):
            if hi==lo:result.update(r+r for r in RANKS[RANKS.index(lo):])
            else:result.update(hi+r+base[2:] for r in RANKS[RANKS.index(lo):RANKS.index(hi)])
        else:result.add(base)
    return result

OPEN={
 'early':expand('77+ AJs+ KQs AQo+'),
 'middle':expand('66+ ATs+ KJs+ QJs JTs AJo+ KQo'),
 'cutoff':expand('44+ A2s+ KTs+ QTs+ JTs T9s 98s A9o+ KJo+ QJo'),
 'button':expand('22+ A2s+ K7s+ Q8s+ J8s+ T8s+ 97s 98s 87s 76s 65s 54s A2o+ K9o+ QTo+ JTo'),
 'small_blind':expand('22+ A2s+ K9s+ Q9s+ J9s+ T9s 98s 87s 76s A8o+ KTo+ QTo+ JTo'),
}
ISOLATE=expand('77+ ATs+ KJs+ QJs AJo+ KQo')
RERAISE_EARLY=expand('QQ+ AKs AKo')
RERAISE_LATE=expand('JJ+ AQs+ AKo')
CALL_EARLY=expand('77+ AQs AJs KQs AQo')
CALL_LATE=expand('55+ ATs+ KJs+ QJs JTs AQo AJo KQo')
DEFEND_BB=expand('22+ A2s+ K9s+ Q9s+ J9s+ T9s 98s 87s 76s 65s ATo+ KTo+ QTo+ JTo')
SHORT_CONTINUE=expand('88+ AJs+ AQo+')
SPECULATIVE=expand('22 33 44 55 66 76s 65s 54s 87s 98s')


def group(position,count):
    if position=='small_blind_button':return 'button'
    if position in ('button','cutoff','small_blind'):return position
    if position=='hijack':return 'middle'
    if position=='under_the_gun':return 'early' if count>=6 else 'middle' if count==5 else 'cutoff'
    return 'early'


def advise(state,player,equity,required,call):
    live=[p for p in state.players if p.id!=player.id and p.status.value!='folded']
    if not live:return None
    history=[a for a in state.history if a.street.value=='preflop']
    raises=[a for a in history if a.action in ('raise','bet')]
    limpers={a.player_id for a in history if a.action=='call' and a.player_id!=player.id} if not raises else set()
    opener=next((p for p in state.players if raises and p.id==raises[0].player_id),None)
    total=player.stack+player.current_bet
    effective={p.id:min(total,p.stack+p.current_bet)/state.big_blind for p in live}
    reference=effective.get(opener.id) if opener else max(effective.values())
    reference=reference if reference is not None else max(effective.values())
    band='Short stack' if reference<=20 else 'Medium stack' if reference<=40 else 'Standard stack' if reference<=100 else 'Deep stack'
    own_group=group(player.position,len(state.players))
    late=opener is not None and group(opener.position,len(state.players)) in ('button','cutoff','small_blind')
    notation=RangeService.notation(tuple(player.cards))
    # Original seats determine position; folded players do not turn UTG into BTN.
    ids=[p.id for p in state.players];button=ids.index(state.dealer_player_id)
    order=ids[button+1:]+ids[:button+1]
    active_order=[pid for pid in order if pid==player.id or any(p.id==pid for p in live)]
    in_position=active_order.index(player.id)>active_order.index(opener.id) if opener and opener.id in active_order else own_group=='button'
    covered=True; amount=None
    fallback='check' if call==0 else 'fold'
    reason='The hand is outside this situation-specific educational range.'
    purpose='Avoid a marginal preflop entry'
    if len(raises)>=2 or any(a.player_id==player.id for a in raises) or any(p.stack==0 for p in live):
        scenario='Reraise or all-in: limited coverage';covered=False
        action='call' if call and notation in RERAISE_EARLY and equity>=required else fallback
        reason='Reraises and all-ins are outside this preset. The conservative fallback does not solve this situation.'
        selected=set()
    elif not raises:
        scenario='Limped pot' if limpers else 'Unopened pot'
        selected=set(ISOLATE if limpers else OPEN.get(own_group,OPEN['early']))
        if reference<=20:selected-=SPECULATIVE
        if notation in selected:
            action='raise';purpose='Isolate limpers' if limpers else 'Open the pot'
            amount=ceil(state.big_blind*((2.5 if own_group in ('button','cutoff') else 3)+len(limpers)))
            reason='This hand belongs to the opening or isolation preset for your position and effective stack.'
        else:action=fallback
    else:
        callers={a.player_id for a in history[history.index(raises[0])+1:] if a.action=='call' and a.player_id not in (player.id,opener.id)}
        scenario='Raise and callers' if callers else 'Facing one raise'
        strong=RERAISE_LATE if late else RERAISE_EARLY
        selected=set(CALL_LATE if late else CALL_EARLY)
        if player.position=='big_blind' and late and not callers and highest_bet(state)<=3*state.big_blind:selected|=DEFEND_BB
        if callers or not in_position:selected-=SPECULATIVE
        if reference<=20:selected&=SHORT_CONTINUE
        if reference>40 and in_position and call and min(player.stack-call,opener.stack)>=20*call:
            selected|=expand('22+') if not callers else expand('77+')
        open_total=highest_bet(state)
        if notation in strong and opener.stack>0:
            action='raise';purpose='Preflop value raise'
            amount=ceil(open_total*((3 if in_position else 4)+len(callers)))
            reason='The value-raise preset accounts for the opener position, your position and callers.'
        elif notation in selected and equity>=required and open_total<=5*state.big_blind and call<=.2*total:
            action='call';purpose='Continue within the response range'
            reason='The hand belongs to the response preset and the call passes the price and stack guards.'
        else:
            action=fallback
            if notation in selected:
                reason=('The call does not clear the estimated equity threshold.' if equity<required else
                        'The hand is in the preset, but the call exceeds its price or stack limits.')
        selected|=strong
    options=betting_options(state,player.id)
    if action=='raise':
        minimum=options.min_raise_to
        if 'raise' not in options.legal_actions or minimum is None:
            action='call' if call and equity>=required else 'check' if not call else 'fold';amount=None
            purpose='Legal continuation';reason='The recommendation was adjusted to the legal betting options.'
        else:
            amount=min(options.max_raise_to,max(minimum,amount))
            if amount>=.4*total and notation not in expand('QQ+ AKs AKo'):
                action='call' if raises and notation in selected and equity>=required and call<=.2*total else fallback
                amount=None;covered=False;purpose='Limit stack commitment'
                reason='The raise would commit a large part of the stack. Push/fold strategy is outside this preset.'
    status='Not covered by this preset' if not covered else 'In the situation range' if notation in selected else 'Outside the situation range'
    return {'version':'preflop_rules_v1','action':action,'amount':amount,'hand_label':notation,'board_texture':[],
      'purpose':purpose,'reason':reason,'live_opponents':len(live),'close_price':bool(call and abs(equity-required)<.03),
      'limitations':'Educational cash-game presets, not GTO. Rake, antes and opponent-specific adjustments are not modelled.',
      'scenario':scenario,'position_group':own_group,'opener_position':opener.position if opener else None,
      'effective_stack_bb':round(reference,1),'effective_stacks_bb':effective,'stack_band':band,
      'range_status':status,'range_covered':covered,'range_hands':sorted(selected)}
