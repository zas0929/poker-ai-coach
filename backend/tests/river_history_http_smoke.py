"""Local disposable-profile integration: finish real hands, then review snapshots."""
import argparse
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
import uuid


def check(base):
    if urlsplit(base).hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Use an explicit local test API only.')
    def call(path,method='GET',body=None,token=None):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        request=Request(base+path,method=method,headers=headers,data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(request,timeout=30) as response:
                return response.status,json.load(response),{k.lower():v for k,v in response.headers.items()}
        except HTTPError as error:
            return error.code,json.loads(error.read()),{k.lower():v for k,v in error.headers.items()}
    assert call('/api/river-lessons/history')[0]==401
    _,a,_=call('/api/training/profiles','POST');_,b,_=call('/api/training/profiles','POST')
    token,foreign=a['token'],b['token'];rows=[]
    for count in range(2,7):
        status,state,_=call('/api/hand/start?player_count='+str(count),'POST',token=token);assert status==200
        hand=state['hand_id'];river_ids=[]
        for _ in range(100):
            if state['result']:break
            if state['current_player_id'] is None:
                status,state,_=call('/api/hand/advance','POST',token=token);assert status==200;continue
            action='check' if 'check' in state['betting']['legal_actions'] else 'call'
            if state['current_player_id']=='hero':
                if state['street']=='river':
                    status,page,_=call('/api/river-lessons/history',token=token)
                    assert status==200 and all(row['hand_id']!=hand for row in page['items'])
                status,moved,_=call('/api/training/decision','POST',{'command_id':str(uuid.uuid4()),'hand_id':hand,
                    'history_length':len(state['history']),'action':action},token)
                assert status==200
                if state['street']=='river':river_ids.append(moved['decision_id'])
                state=moved['state']
            else:
                status,state,_=call('/api/hand/action','POST',{'player_id':state['current_player_id'],'action':action},token);assert status==200
        assert state['result'] and river_ids
        decision=river_ids[0];path='/api/river-lessons/history/'+str(decision)
        status,detail,headers=call(path,token=token);assert status==200
        assert 'no-store' in headers['cache-control'] and 'Authorization' in headers['vary']
        assert call(path,token=foreign)[0]==404
        body={'version':detail['source_version'],**detail['model']}
        assert call(path+'/jobs','POST',body,foreign)[0]==404
        assert call(path+'/jobs','POST',{**body,'version':'0'*64},token)[0]==409
        assert call(path+'/jobs','POST',{**body,'snapshot':{}},token)[0]==422
        _,live_before,_=call('/api/hand/start','POST',token=token)
        status,submitted,_=call(path+'/jobs','POST',body,token);assert status==200
        assessment=submitted['assessment']
        row={'players':count,'decision_id':decision,'supported':assessment['supported'],'reason':assessment['reason'],
             'coverage':assessment['coverage'],'chosen_action':assessment['chosen_action']}
        if submitted['ticket_id']:
            deadline=time.monotonic()+20
            while True:
                status,job,_=call('/api/river-lessons/jobs/'+submitted['ticket_id'],token=token);assert status==200
                if job['state'] in ('completed','error','cancelled','stale'):break
                assert time.monotonic()<deadline;time.sleep(.1)
            result=job['result'];row.update(status=result['status'],quality=result['quality'])
            assert result['status'] in ('ready','quality_rejected','budget_exceeded')
            if result['status']=='ready':
                values=result['action_values'];assert all(math.isfinite(v) for v in values['ev_chips'])
                assert values['own_hand']==assessment['lesson']['own_hand'] and values['actor_id']=='hero'
                assert abs(values['policy_ev_chips']-sum(p*v for p,v in zip(result['candidate']['probabilities'],values['ev_chips'])))<1e-7
                row.update(actions=values['actions'],ev_chips=values['ev_chips'],probabilities=result['candidate']['probabilities'])
            else:
                assert result['candidate'] is None and 'action_values' not in result
        _,live_after,_=call('/api/hand/state',token=token)
        assert live_before==live_after
        # Finish the fresh active hand before switching table size in the next case.
        if not live_after['result']:
            for _ in range(100):
                if live_after['result']:break
                if live_after['current_player_id'] is None:
                    status,live_after,_=call('/api/hand/advance','POST',token=token)
                else:
                    status,live_after,_=call('/api/hand/action','POST',{'player_id':live_after['current_player_id'],
                        'action':'check' if 'check' in live_after['betting']['legal_actions'] else 'fold'},token)
                assert status==200
        rows.append(row)
    return {'scope':'Real completed trainer decisions, original public snapshots, manual small-range models; localhost only.',
            'checks':{'unauthorized_rejected':True,'active_hand_not_listed':True,'foreign_profile_rejected':True,
                      'hidden_request_fields_rejected':True,'stale_version_rejected':True,'private_no_store':True,'live_hand_unchanged':True},'results':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',default='http://127.0.0.1:8011');parser.add_argument('--output',type=Path);args=parser.parse_args()
    report=json.dumps(check(args.url.rstrip('/')),indent=2)+'\n'
    if args.output:args.output.write_text(report)
    print(report,end='')
