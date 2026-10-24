"""Real-process offline shadow queue controls. No game endpoints or deploys."""
import json
from hashlib import sha256
from pathlib import Path
import research.shadow_executor as executor_module
import time
from research.analysis_contract import ResearchLimits
from research.benchmark_midriver_ranges import make_case
from research.shadow_executor import ShadowExecutor


def request(n,widths,seed):
    case=make_case('shadow',n,widths,seed)
    result={k:case[k] for k in ('snapshot','selected_hands','input')}
    result['own_hand']=case['selected_hands'][case['snapshot']['actor_id']][0]
    return result


def wait_for(callback,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=callback()
        if value:return value
        time.sleep(.01)
    raise AssertionError('Shadow control did not reach the expected state')


def terminal(executor,tid):
    state=executor.poll(tid)
    return state if state['state'] in ('completed','stale','cancelled','error') else None


def benchmark():
    small=request(2,[3,3],20261047);large=request(6,[3]*6,20261045);rows=[]
    with ShadowExecutor(max_pending=1,max_retained=16,max_events=64) as executor:
        a=executor.submit('first',small);b=executor.submit('second',small)
        assert a['job_id']==b['job_id']
        executor.advance('first','b'*64)
        stale=executor.poll(a['ticket_id']);ready=wait_for(lambda:terminal(executor,b['ticket_id']))
        assert stale['state']=='stale' and stale['result']['candidate'] is None
        assert ready['result']['status']=='ready'
        assert sum(e['event']=='started' for e in executor.events())==1
        rows.append({'control':'shared_job_one_stale_one_ready','stale':stale,'ready':ready})
        active=executor.submit('large',large,ResearchLimits(wall_seconds=20))
        wait_for(lambda:executor.poll(active['ticket_id'])['state']=='running')
        # The six-seat build is intentionally long enough to exercise cancellation in flight.
        time.sleep(.5)
        waiting=executor.submit('waiting',small,ResearchLimits(iterations=101))
        full=executor.submit('overflow',small,ResearchLimits(iterations=102))
        assert full['status']=='queue_full'
        assert executor.cancel(waiting['ticket_id'])
        cancel_start=time.monotonic()
        assert executor.cancel(active['ticket_id'])
        wait_for(lambda:executor.stats()['jobs']==0)
        cancellation_seconds=time.monotonic()-cancel_start
        finished=next(e for e in executor.events() if e['event']=='finished' and e['job_id']==active['job_id'])
        assert finished['analysis_status']=='cancelled' and finished['analysis_wall_seconds']>0
        rows.append({'control':'cancel_active_and_waiting_backpressure','cancel_to_reaped_seconds':cancellation_seconds,
                     'cancelled_process_evidence':finished,
                     'active':executor.poll(active['ticket_id']),'waiting':executor.poll(waiting['ticket_id']),
                     'overflow':full,'after_cancel':executor.stats()})
        recovery=executor.submit('recovery',small)
        recovered=wait_for(lambda:terminal(executor,recovery['ticket_id']))
        assert recovered['result']['status']=='ready'
        executor.advance('recovery','c'*64)
        obsolete=executor.poll(recovery['ticket_id'])
        assert obsolete['state']=='stale' and obsolete['result']['candidate'] is None
        rows.append({'control':'worker_recovers_after_cancel','result':recovered,'after_advance':obsolete})
        journal=executor.events()
        assert all('own_hand' not in e and 'selected_hands' not in e for e in journal)
    stats=executor.stats();assert stats['jobs']==0 and stats['closed']
    assert all(row['result']['admission']['live_advice_allowed'] is False for row in (ready,recovered))
    return {'executor_version':1,'executor_source_sha256':sha256(Path(executor_module.__file__).read_bytes()).hexdigest(),
            'scope':'Offline single-worker shadow executor; real native calculations with cooperative cancellation.',
            'summary':{'controls':len(rows),'passed':len(rows)},'results':rows,'events':journal,'closed_stats':stats}


if __name__=='__main__':print(json.dumps(benchmark(),indent=2,allow_nan=False))
