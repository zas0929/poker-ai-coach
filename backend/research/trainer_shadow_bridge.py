"""Opt-in LOCAL trainer bridge. Snapshot preparation runs off the hint/action path.
Exact public decision plans only: no implicit sampling/truncation or opponent cards.
"""
from collections import OrderedDict,deque
import copy
from hashlib import sha256
import re
from threading import Condition,Thread
import time
from app.models.poker import HandState
from app.services.solver_snapshot import prepare_solver_snapshot,card_text
from research.analysis_contract import ResearchLimits,TREE_FIELDS
from research.river_snapshot import digest,combo_key
from research.shadow_executor import ShadowExecutor


def read_plan(value):
    if type(value) is not dict or set(value)-{'version','decisions','limits'} or type(value.get('version')) is not int or value['version']!=1:
        raise ValueError('Local shadow plan version 1 required.')
    decisions=value.get('decisions')
    if type(decisions) is not dict or len(decisions)>256:raise ValueError('At most 256 explicit decision plans required.')
    for key,plan in decisions.items():
        if type(key) is not str or not re.fullmatch('[0-9a-f]{64}',key) or type(plan) is not dict or set(plan)!={'selected_hands','input'}:
            raise ValueError('Plan must map public information keys to selected_hands/input.')
        if type(plan['selected_hands']) is not dict or any(type(k) is not str or type(v) is not list or not v for k,v in plan['selected_hands'].items()):raise ValueError('Explicit hand subsets required.')
        for hands in plan['selected_hands'].values():
            for hand in hands:combo_key(hand)
        if type(plan['input']) is not dict or set(plan['input'])-TREE_FIELDS:raise ValueError('Unknown tree setting.')
    limits=value.get('limits',{})
    if type(limits) is not dict:raise ValueError('Limits object required.')
    return copy.deepcopy(decisions),ResearchLimits(**limits)


def public_state(state):
    # Exclude holdings at serialization, rather than copying and clearing opponents later.
    value=state.model_dump(mode='json',exclude={'players':{'__all__':{'cards'}},'notes':True,'result':True})
    value['result']=None if state.result is None else {'ended':True}
    for player in value['players']:
        player['name']=player['id']
        player['cards']=[]
        if player['id']=='hero':player['cards']=[c.model_dump(mode='json') for c in next(p for p in state.players if p.id=='hero').cards]
    return value


class TrainerShadowBridge:
    def __init__(self,plan,*,executor=None,prepare=prepare_solver_snapshot,max_contexts=32,max_pending=8,max_events=256):
        self.plans,self.limits=read_plan(plan)
        for v in (max_contexts,max_pending,max_events):
            if type(v) is not int or not 1<=v<=4096:raise ValueError('Positive bounded capacities required.')
        self.executor=executor if executor is not None else ShadowExecutor()
        self._prepare=prepare;self._cv=Condition();self._contexts=OrderedDict();self._pending=OrderedDict()
        self._events=deque(maxlen=max_events);self._closed=False;self._preparing=None
        self._max_contexts=max_contexts;self._max_pending=max_pending;self._sequence=0
        self._thread=Thread(target=self._loop,name='local-trainer-shadow-prepare',daemon=False);self._thread.start()

    def _context(self,owner):return sha256(('local' if owner is None else 'profile:'+owner).encode()).hexdigest()
    def _log(self,event,**fields):
        self._sequence+=1;self._events.append({'sequence':self._sequence,'event':event,**fields})

    def observe(self,owner,state):
        value=public_state(state) if state is not None else None
        revision=digest(value);context=self._context(owner)
        with self._cv:
            if self._closed:return False
            old=self._contexts.get(context)
            if old is not None and old['revision']==revision:return True
            if old is None and len(self._contexts)>=self._max_contexts:
                victim=next((k for k,v in self._contexts.items() if v['ticket'] is None and k not in self._pending and k!=self._preparing),None)
                if victim is None:
                    self._log('skipped',code='CONTEXT_CAPACITY');return False
                self._contexts.pop(victim)
            self.executor.advance(context,revision)
            self._pending.pop(context,None)
            self._contexts[context]={'revision':revision,'offered':False,'ticket':None,'baseline':None}
            self._log('observed',context_key=context,revision=revision);self._cv.notify_all();return True

    def offer(self,owner,state,analysis):
        if (analysis.player_id!='hero' or analysis.hand_id!=state.hand_id or
            analysis.street!=state.street or analysis.pot!=state.pot):return False
        value=public_state(state);revision=digest(value);context=self._context(owner)
        with self._cv:
            current=self._contexts.get(context)
            if self._closed or current is None or current['revision']!=revision:
                self._log('skipped',code='STALE_HINT');return False
            if current['offered']:return False
            if state.result is not None or state.street.value!='river' or state.current_player_id!='hero':
                current['offered']=True;self._log('skipped',code='UNSUPPORTED_DECISION');return False
            if len(self._pending)>=self._max_pending:
                self._log('skipped',code='PREPARATION_QUEUE_FULL');return False
            current['offered']=True
            baseline={'action':analysis.recommended_action,'amount':analysis.recommended_amount}
            self._pending[context]=(revision,value,baseline)
            self._log('captured',context_key=context,revision=revision);self._cv.notify_all();return True

    def _prepare_one(self,context,revision,value,baseline):
        state=HandState.model_validate(value)
        snapshot=self._prepare(state)
        plan=self.plans.get(snapshot['information_key'])
        if plan is None:return 'NO_EXPLICIT_PLAN'
        own=''.join(card_text(c) for c in next(p for p in state.players if p.id=='hero').cards)
        if combo_key(own) not in [combo_key(h) for h in plan['selected_hands'].get('hero',[])]:return 'OWN_HAND_NOT_SELECTED'
        public=next(p['range'] for p in snapshot['players'] if p['id']=='hero')
        own=next(row['cards'] for row in public if combo_key(row['cards'])==combo_key(own))
        request={'snapshot':snapshot,'selected_hands':plan['selected_hands'],'input':plan['input'],'own_hand':own}
        with self._cv:
            current=self._contexts.get(context)
            if self._closed or current is None or current['revision']!=revision:return 'STALE_PREPARATION'
            receipt=self.executor.submit(context,request,self.limits)
            if receipt['ticket_id'] is None:return 'SOLVER_'+receipt['status'].upper()
            current['ticket']=receipt['ticket_id'];current['baseline']=baseline
            self._log('submitted',context_key=context,revision=revision,source_key=snapshot['information_key'],job_id=receipt['job_id'])
        return None

    def _collect(self):
        with self._cv:
            pending=[(key,c['revision'],c['ticket']) for key,c in self._contexts.items() if c['ticket'] is not None]
        for context,revision,tid in pending:
            polled=self.executor.poll(tid)
            if polled['state'] in ('queued','running'):continue
            with self._cv:
                current=self._contexts.get(context)
                if current is None or current['revision']!=revision or current['ticket']!=tid:continue
                current['ticket']=None
                result=polled.get('result')
                if result is None or result['status']!='ready':
                    self._log('rejected',context_key=context,status=result['status'] if result else polled['state']);continue
                # Diagnostic frequency comparison, never an EV/superiority claim or new advice.
                candidate=result['candidate'];baseline=current['baseline']
                label=baseline['action'].upper()
                if label in ('BET','RAISE'):label+=' '+str(baseline['amount'])
                represented=label in candidate['actions'];probabilities=candidate['probabilities']
                modes=[a for a,p in zip(candidate['actions'],probabilities) if abs(p-max(probabilities))<1e-8]
                self._log('comparison',context_key=context,source_key=result['source_information_key'],
                    baseline_action=label,represented_exactly=represented,solver_most_likely_actions=modes,
                    baseline_probability=probabilities[candidate['actions'].index(label)] if represented else None,
                    matches_most_likely=label in modes if represented else None,
                    quality_pct_pot=result['quality']['value'],live_advice_allowed=False)

    def _loop(self):
        while True:
            with self._cv:
                if self._closed:return
                if self._pending:
                    context,payload=self._pending.popitem(last=False);self._preparing=context
                else:context=None;payload=None
            if payload is not None:
                revision,value,baseline=payload
                try:code=self._prepare_one(context,revision,value,baseline)
                except Exception:code='PREPARATION_FAILED'
                with self._cv:
                    if code:self._log('skipped',context_key=context,code=code)
                    self._preparing=None
                payload=None;value=None;baseline=None
            try:self._collect()
            except Exception:
                with self._cv:self._log('error',code='COLLECTION_FAILED')
            with self._cv:
                if not self._closed and not self._pending:self._cv.wait(timeout=.05)

    def events(self):
        with self._cv:return copy.deepcopy(list(self._events))
    def stats(self):
        with self._cv:return {'contexts':len(self._contexts),'pending_preparations':len(self._pending),
                              'preparing':self._preparing is not None,'closed':self._closed}
    def close(self):
        with self._cv:
            self._closed=True;self._pending.clear();self._cv.notify_all()
        self._thread.join();self.executor.close()
