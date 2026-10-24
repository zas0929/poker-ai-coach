import copy
from dataclasses import asdict
import json
from threading import Event,Lock
import time
import unittest
from research.analysis_contract import ResearchLimits,provenance,finish,CONTRACT_VERSION
from research.benchmark_midriver_ranges import make_case
from research.river_snapshot import digest
from research.shadow_executor import ShadowExecutor


def response(request,limits):
    base={'contract_version':CONTRACT_VERSION,'provenance':provenance(),'request_key':digest(request),
          'source_information_key':request['snapshot']['information_key'],'limits':asdict(limits)}
    # A well-formed refusal suffices to test scheduling independently from solver quality.
    return finish(base,'quality_rejected','QUALITY_GATE_FAILED','Fixture refusal.','test')


def until(predicate,timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.005)
    raise AssertionError('Expected executor state did not arrive')


class BlockedAnalyzer:
    def __init__(self):self.started=Event();self.release=Event();self.cancelled=Event();self.calls=[];self.lock=Lock()
    def __call__(self,request,limits,cancel_event=None):
        with self.lock:self.calls.append(copy.deepcopy(request))
        self.started.set()
        until(lambda:self.release.is_set() or cancel_event.is_set())
        if cancel_event.is_set():self.cancelled.set()
        return response(request,limits)


class ShadowExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        case=make_case('shadow',2,[3,3],20261047)
        cls.request={k:case[k] for k in ('snapshot','selected_hands','input')}
        cls.request['own_hand']=case['selected_hands'][case['snapshot']['actor_id']][0]

    def other(self):
        request=copy.deepcopy(self.request)
        actor=request['snapshot']['actor_id']
        request['own_hand']=request['selected_hands'][actor][1]
        return request

    def done(self,executor,ticket):
        return until(lambda:(s if s['state'] in ('completed','stale','cancelled','error') else None) if (s:=executor.poll(ticket)) else None)

    def test_submit_returns_before_analysis_finishes_and_duplicates_share_one_job(self):
        fake=BlockedAnalyzer()
        with ShadowExecutor(analyzer=fake) as executor:
            a=executor.submit('first',self.request)
            self.assertTrue(fake.started.wait(2));self.assertFalse(fake.release.is_set())
            same=executor.submit('first',self.request)
            b=executor.submit('second',self.request)
            self.assertEqual(same['status'],'reused');self.assertEqual(same['ticket_id'],a['ticket_id'])
            self.assertEqual(a['job_id'],b['job_id'])
            self.assertEqual(executor.poll(a['ticket_id'])['state'],'running')
            fake.release.set()
            for receipt in (a,b):self.assertEqual(self.done(executor,receipt['ticket_id'])['result']['status'],'quality_rejected')
            self.assertEqual(len(fake.calls),1)

    def test_queue_backpressure_and_same_source_supersession_free_slots(self):
        fake=BlockedAnalyzer()
        with ShadowExecutor(max_pending=1,analyzer=fake) as executor:
            a=executor.submit('a',self.request);self.assertTrue(fake.started.wait(2))
            b=executor.submit('b',self.other())
            c=executor.submit('c',self.other(),ResearchLimits(iterations=101))
            self.assertEqual(c['status'],'queue_full')
            replacement=executor.submit('b',self.other(),ResearchLimits(iterations=102))
            self.assertEqual(replacement['status'],'queued')
            self.assertEqual(executor.poll(b['ticket_id'])['state'],'stale')
            self.assertEqual(executor.stats()['pending'],1)
            fake.release.set();self.done(executor,replacement['ticket_id'])
            self.assertEqual(len(fake.calls),2)

    def test_advance_one_subscriber_preserves_others_and_ready_cannot_reappear(self):
        fake=BlockedAnalyzer()
        with ShadowExecutor(analyzer=fake) as executor:
            a=executor.submit('a',self.request);self.assertTrue(fake.started.wait(2))
            b=executor.submit('b',self.request)
            executor.advance('a','b'*64)
            self.assertEqual(executor.poll(a['ticket_id'])['state'],'stale')
            self.assertFalse(fake.cancelled.is_set())
            fake.release.set();self.done(executor,b['ticket_id'])
            self.assertEqual(executor.poll(a['ticket_id'])['result']['candidate'],None)
            self.assertEqual(executor.poll(a['ticket_id'])['state'],'stale')

    def test_last_subscriber_cancels_active_job_and_queued_job_never_runs(self):
        fake=BlockedAnalyzer()
        with ShadowExecutor(analyzer=fake) as executor:
            a=executor.submit('a',self.request);self.assertTrue(fake.started.wait(2))
            queued=executor.submit('b',self.other())
            self.assertTrue(executor.cancel(queued['ticket_id']))
            self.assertTrue(executor.cancel(a['ticket_id']))
            self.assertTrue(fake.cancelled.wait(2))
            until(lambda:executor.stats()['jobs']==0)
            self.assertEqual(len(fake.calls),1)
            self.assertEqual(executor.poll(a['ticket_id'])['state'],'cancelled')
            self.assertFalse(executor.cancel(a['ticket_id']))

    def test_inputs_results_events_and_retention_are_isolated_and_bounded(self):
        fake=BlockedAnalyzer();request=copy.deepcopy(self.request)
        with ShadowExecutor(max_retained=2,max_events=4,analyzer=fake) as executor:
            a=executor.submit('private-context',request);self.assertTrue(fake.started.wait(2))
            request['own_hand']='QhQd'
            fake.release.set();state=self.done(executor,a['ticket_id'])
            self.assertEqual(fake.calls[0]['own_hand'],self.request['own_hand'])
            state['result']['candidate']={'bad':True}
            self.assertIsNone(executor.poll(a['ticket_id'])['result']['candidate'])
            for i in range(4):
                receipt=executor.submit('context-'+str(i),self.request)
                self.done(executor,receipt['ticket_id'])
            self.assertEqual(executor.poll(a['ticket_id'])['state'],'expired')
            self.assertLessEqual(executor.stats()['retained_tickets'],2)
            self.assertLessEqual(executor.stats()['contexts'],2)
            events=executor.events();self.assertLessEqual(len(events),4)
            encoded=json.dumps(events)
            self.assertNotIn('private-context',encoded);self.assertNotIn(self.request['own_hand'],encoded)
            self.assertNotIn('selected_hands',encoded)
            self.assertEqual(len(fake.calls),5) # completed results are not cached

    def test_worker_errors_do_not_stop_queue_and_failed_results_are_not_published(self):
        calls=[]
        def failing(request,limits,cancel_event=None):
            calls.append(1)
            if len(calls)==1:raise RuntimeError('private details')
            if len(calls)==2:return {'status':'ready'}
            return response(request,limits)
        with ShadowExecutor(analyzer=failing) as executor:
            for i,expected in enumerate(('error','error','completed')):
                receipt=executor.submit(str(i),self.request)
                outcome=self.done(executor,receipt['ticket_id'])
                self.assertEqual(outcome['state'],expected)
                self.assertIsNone(outcome['result']['candidate'])
            self.assertNotIn('private details',json.dumps(executor.events()))

    def test_returning_to_old_source_key_never_reattaches_cancelled_work(self):
        fake=BlockedAnalyzer()
        with ShadowExecutor(analyzer=fake) as executor:
            old=executor.submit('same',self.request);self.assertTrue(fake.started.wait(2))
            executor.advance('same','b'*64)
            new=executor.submit('same',self.request)
            self.assertNotEqual(old['job_id'],new['job_id'])
            until(lambda:len(fake.calls)==2)
            fake.release.set();self.done(executor,new['ticket_id'])
            self.assertEqual(executor.poll(old['ticket_id'])['state'],'stale')
            self.assertEqual(executor.poll(new['ticket_id'])['state'],'completed')

    def test_close_cancels_and_joins_active_and_waiting_work(self):
        fake=BlockedAnalyzer();executor=ShadowExecutor(analyzer=fake)
        a=executor.submit('a',self.request);self.assertTrue(fake.started.wait(2))
        b=executor.submit('b',self.other())
        executor.close();executor.close()
        self.assertFalse(executor._thread.is_alive())
        self.assertEqual(executor.stats()['jobs'],0)
        for r in (a,b):self.assertEqual(executor.poll(r['ticket_id'])['state'],'cancelled')
        self.assertEqual(executor.submit('c',self.request)['status'],'closed')

    def test_capacities_privacy_and_limits_are_strict(self):
        for kwargs in ({'max_pending':0},{'max_retained':True},{'max_events':4097},{'analyzer':None}):
            with self.assertRaises(ValueError):ShadowExecutor(**kwargs)
        fake=BlockedAnalyzer()
        with ShadowExecutor(max_retained=1,analyzer=fake) as executor:
            a=executor.submit('a',self.request);self.assertTrue(fake.started.wait(2))
            self.assertEqual(executor.submit('b',self.request)['status'],'capacity_rejected')
            bad=copy.deepcopy(self.request);bad['snapshot']['players'][0]['cards']=['private']
            self.assertEqual(executor.submit('c',bad)['status'],'invalid_input')
            with self.assertRaises(ValueError):executor.submit('',self.request)
            with self.assertRaises(ValueError):executor.submit('c',self.request,False)
            fake.release.set();self.done(executor,a['ticket_id'])
