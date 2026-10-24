"""Single-worker, bounded OFFLINE shadow queue. Never called by live game routes.
One in-flight job may serve multiple contexts. No completed-result cache.
"""
from collections import OrderedDict,deque
import copy
from dataclasses import asdict
from hashlib import sha256
import json
import re
from threading import Condition,Event,Thread
import time
from research.analysis_contract import (CONTRACT_VERSION,ResearchLimits,analyze,finish,
    provenance,recheck_decision,validate_request)
from research.river_snapshot import digest

TERMINAL={'completed','stale','cancelled','error'}


class ShadowExecutor:
    def __init__(self,*,max_pending=2,max_retained=128,max_events=256,analyzer=analyze):
        for value in (max_pending,max_retained,max_events):
            if type(value) is not int or not 1<=value<=4096:raise ValueError('Integer capacities 1–4096 required.')
        if not callable(analyzer):raise ValueError('Callable analyzer required.')
        self.max_pending=max_pending;self.max_retained=max_retained;self.max_events=max_events
        self._analyzer=analyzer;self._cv=Condition();self._queue=deque();self._jobs={};self._identities={}
        self._tickets=OrderedDict();self._contexts={};self._events=deque(maxlen=max_events)
        self._counter=0;self._sequence=0;self._closed=False;self._active=None
        self._thread=Thread(target=self._loop,name='offline-poker-shadow',daemon=False);self._thread.start()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def _id(self,prefix):
        self._counter+=1;return prefix+str(self._counter)

    def _log(self,event,**fields):
        self._sequence+=1
        self._events.append({'sequence':self._sequence,'time_monotonic':time.monotonic(),'event':event,**fields})

    def _envelope(self,ticket,status,code):
        base={'contract_version':CONTRACT_VERSION,'scope':'offline_bounded_river','provenance':ticket['provenance'],
              'request_key':ticket['request_key'],'source_information_key':ticket['source_key'],
              'task_key':None,'limits':asdict(ticket['limits']),'timing':None,'quality':None,'model':None}
        return finish(base,status,code,'Shadow executor did not admit this task.','shadow')

    def _detach(self,ticket,status,code):
        ticket['state']=status;ticket['result']=self._envelope(ticket,status,code)
        job=self._jobs.get(ticket['job_id'])
        self._log(status,ticket_id=ticket['ticket_id'],job_id=ticket['job_id'],reason_code=code)
        if job is None:return
        job['subscribers'].discard(ticket['ticket_id'])
        if job['subscribers']:return
        job['cancel'].set()
        if self._identities.get(job['identity'])==job['job_id']:self._identities.pop(job['identity'])
        if job['state']=='queued':
            self._queue.remove(job['job_id']);self._jobs.pop(job['job_id'])
        else:job['state']='cancelling'
        self._cv.notify_all()

    def _advance(self,context_id,source_key):
        context=self._contexts.get(context_id)
        if context is None:return
        ticket=self._tickets.get(context['ticket_id'])
        if ticket is not None and ticket['state'] not in ('stale','cancelled','error'):
            self._detach(ticket,'stale','STALE_DECISION')
        self._contexts.pop(context_id,None)

    def advance(self,context_id,source_key):
        """Caller signals that a context moved. No automatic room subscription."""
        if type(context_id) is not str or not 1<=len(context_id)<=256 or type(source_key) is not str or not re.fullmatch('[0-9a-f]{64}',source_key):raise ValueError('Nonempty context and source key required.')
        with self._cv:
            current=self._contexts.get(context_id)
            if current is not None and current['source_key']!=source_key:self._advance(context_id,source_key)

    def submit(self,context_id,request,limits=None):
        """Snapshot/canonicalize input, enqueue or reuse. Does not run the solver inline."""
        if type(context_id) is not str or not 1<=len(context_id)<=256:raise ValueError('Nonempty context id required.')
        limits=ResearchLimits() if limits is None else limits
        if not isinstance(limits,ResearchLimits):raise ValueError('ResearchLimits required.')
        try:
            validate_request(request)
            frozen=json.loads(json.dumps(request,allow_nan=False))
            request_key=digest(frozen);engine=provenance()
            identity=digest({'request_key':request_key,'limits':asdict(limits),'provenance':engine})
            source_key=frozen['snapshot']['information_key']
            if type(source_key) is not str or not re.fullmatch('[0-9a-f]{64}',source_key):raise ValueError('Source key required.')
        except (ValueError,TypeError,KeyError):
            return {'status':'invalid_input','ticket_id':None,'job_id':None}
        with self._cv:
            if self._closed:return {'status':'closed','ticket_id':None,'job_id':None}
            current=self._contexts.get(context_id)
            old=self._tickets.get(current['ticket_id']) if current else None
            if old is not None and old['identity']==identity and old['state'] in ('queued','running'):
                self._log('reused',ticket_id=old['ticket_id'],job_id=old['job_id'])
                return {'status':'reused','ticket_id':old['ticket_id'],'job_id':old['job_id']}
            # New context request supersedes its previous request, even for the same public key.
            self._advance(context_id,source_key)
            job_id=self._identities.get(identity);job=self._jobs.get(job_id)
            if job is None and len(self._queue)>=self.max_pending:
                self._log('rejected',reason_code='QUEUE_FULL')
                return {'status':'queue_full','ticket_id':None,'job_id':None}
            while len(self._tickets)>=self.max_retained:
                victim=next((tid for tid,t in self._tickets.items() if t['state'] in TERMINAL),None)
                if victim is None:
                    self._log('rejected',reason_code='TICKET_CAPACITY')
                    return {'status':'capacity_rejected','ticket_id':None,'job_id':None}
                evicted=self._tickets.pop(victim)
                ctx=self._contexts.get(evicted['context_id'])
                if ctx is not None and ctx['ticket_id']==victim:self._contexts.pop(evicted['context_id'])
            if job is None:
                job_id=self._id('job-')
                job={'job_id':job_id,'identity':identity,'request':frozen,'limits':limits,'provenance':engine,
                     'state':'queued','subscribers':set(),'cancel':Event(),'queued_at':time.monotonic()}
                self._jobs[job_id]=job;self._identities[identity]=job_id;self._queue.append(job_id)
            ticket_id=self._id('ticket-')
            ticket={'ticket_id':ticket_id,'job_id':job_id,'identity':identity,'request_key':request_key,
                    'source_key':source_key,'context_id':context_id,'provenance':engine,'limits':limits,
                    'state':job['state'],'result':None,'submitted_at':time.monotonic()}
            self._tickets[ticket_id]=ticket;job['subscribers'].add(ticket_id)
            self._contexts[context_id]={'source_key':source_key,'ticket_id':ticket_id}
            self._log('joined' if len(job['subscribers'])>1 else 'queued',ticket_id=ticket_id,job_id=job_id,
                      context_key=sha256(context_id.encode()).hexdigest(),source_key=source_key)
            self._cv.notify_all()
            return {'status':ticket['state'],'ticket_id':ticket_id,'job_id':job_id}

    def cancel(self,ticket_id):
        with self._cv:
            ticket=self._tickets.get(ticket_id)
            if ticket is None:return False
            if ticket['state'] in TERMINAL:return False
            self._detach(ticket,'cancelled','SHADOW_CANCELLED');return True

    def poll(self,ticket_id):
        with self._cv:
            ticket=self._tickets.get(ticket_id)
            if ticket is None:return {'ticket_id':ticket_id,'state':'expired','result':None}
            return copy.deepcopy({k:ticket[k] for k in ('ticket_id','job_id','state','result')})

    def events(self):
        with self._cv:return copy.deepcopy(list(self._events))

    def stats(self):
        with self._cv:return {'pending':len(self._queue),'active':int(self._active is not None),
            'jobs':len(self._jobs),'retained_tickets':len(self._tickets),'contexts':len(self._contexts),
            'events':len(self._events),'closed':self._closed}

    def close(self,wait=True):
        with self._cv:
            if not self._closed:
                self._closed=True
                for ticket in list(self._tickets.values()):
                    if ticket['state'] not in TERMINAL:self._detach(ticket,'cancelled','EXECUTOR_CLOSED')
                self._cv.notify_all()
        if wait:self._thread.join()

    def _loop(self):
        while True:
            with self._cv:
                self._cv.wait_for(lambda:self._closed or bool(self._queue))
                if self._closed:return
                job_id=self._queue.popleft();job=self._jobs[job_id]
                self._active=job_id;job['state']='running'
                for tid in job['subscribers']:self._tickets[tid]['state']='running'
                self._log('started',job_id=job_id,queue_wait_seconds=time.monotonic()-job['queued_at'])
            try:
                result=self._analyzer(job['request'],job['limits'],cancel_event=job['cancel'])
                json.dumps(result,allow_nan=False)
                if (type(result) is not dict or result.get('provenance')!=job['provenance'] or
                    result.get('request_key')!=digest(job['request']) or
                    result.get('source_information_key')!=job['request']['snapshot']['information_key'] or
                    result.get('admission',{}).get('live_advice_allowed') is not False or
                    result.get('fallback',{}).get('retain_current_advice') is not True):
                    raise ValueError('Invalid shadow result envelope')
                ready=result.get('status')=='ready'
                if (result.get('contract_version')!=CONTRACT_VERSION or result.get('limits')!=asdict(job['limits']) or
                    result.get('status') not in ('ready','invalid_input','unsupported','stale','quality_rejected','budget_exceeded','unavailable','error','cancelled') or
                    result.get('admission',{}).get('offline_analysis_allowed') is not ready or
                    (result.get('candidate') is not None)!=ready or type(result.get('reasons')) is not list or
                    any(type(r) is not dict or type(r.get('code')) is not str for r in result['reasons'])):
                    raise ValueError('Incomplete shadow admission result')
            except Exception:
                # A failed job must not kill the sole queue worker or publish partial advice.
                result=None
            with self._cv:
                self._log('finished',job_id=job_id,analysis_status=result['status'] if result is not None else 'error',
                          analysis_wall_seconds=(result.get('timing') or {}).get('wall_seconds') if result is not None else None,
                          last_phase=(result.get('timing') or {}).get('last_phase') if result is not None else None)
                for tid in list(job['subscribers']):
                    ticket=self._tickets[tid];context=self._contexts.get(ticket['context_id'])
                    if context is None or context['ticket_id']!=tid:
                        self._detach(ticket,'stale','STALE_DECISION');continue
                    if result is None:
                        ticket['state']='error';ticket['result']=self._envelope(ticket,'error','SHADOW_WORKER_FAILED')
                    else:
                        ticket['result']=recheck_decision(result,context['source_key'])
                        ticket['state']='stale' if ticket['result']['status']=='stale' else 'completed'
                    self._log('delivered',job_id=job_id,ticket_id=tid,status=ticket['result']['status'],
                              reason_codes=[r['code'] for r in ticket['result']['reasons']],
                              total_seconds=time.monotonic()-ticket['submitted_at'])
                if self._identities.get(job['identity'])==job_id:self._identities.pop(job['identity'])
                self._jobs.pop(job_id,None);self._active=None;self._cv.notify_all()
                # Do not retain the last completed request in the idle thread frame.
                job=None;result=None;ticket=None;context=None
