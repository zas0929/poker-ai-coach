"""Explicit staging acceptance: disposable profiles only; no room/user access."""
import argparse
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import uuid

ALLOWED={'https://poker-ai-coach-api.onrender.com','http://127.0.0.1:8011'}


def response_headers(headers):
    # Edge proxies may append separate Vary fields; their union is authoritative.
    return {key.lower(): ', '.join(headers.get_all(key)) for key in headers.keys()}


def check(base):
    if base not in ALLOWED:
        raise ValueError('Only the named poker staging API or isolated local preview is allowed.')
    def call(path,method='GET',body=None,token=None):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        request=Request(base+path,method=method,headers=headers,data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(request,timeout=90) as response:
                return response.status,json.load(response),response_headers(response.headers)
        except HTTPError as error:
            return error.code,json.loads(error.read()),response_headers(error.headers)
    status,catalog,_=call('/api/river-lessons');assert status==200 and catalog['enabled'],catalog
    assert call('/api/river-lessons/history')[0]==401
    status,a,_=call('/api/training/profiles','POST');assert status==200
    status,b,_=call('/api/training/profiles','POST');assert status==200
    token,other=a['token'],b['token']
    rows=[]
    def finish_job(submitted):
        path='/api/river-lessons/jobs/'+submitted['ticket_id']
        assert call(path,token=other)[0]==404
        deadline=time.monotonic()+45
        while True:
            status,job,_=call(path,token=token);assert status==200
            if job['state'] in ('completed','error','cancelled','stale'):break
            assert time.monotonic()<deadline;time.sleep(.5)
        result=job['result'];assert result['status']=='ready',result.get('reasons')
        assert result['quality']['passed'] and not result['admission']['live_advice_allowed']
        values=result['action_values'];assert all(math.isfinite(v) for v in values['ev_chips'])
        return result
    for lesson in catalog['lessons']:
        start=time.monotonic()
        status,submitted,headers=call('/api/river-lessons/jobs','POST',{'lesson_id':lesson['id'],'version':catalog['version']},token)
        assert status==200 and 'no-store' in headers['cache-control'] and 'authorization' in headers['vary'].lower()
        result=finish_job(submitted)
        rows.append({'opponents':lesson['opponents'],'status':result['status'],
                     'quality_pct_pot':result['quality']['value'],'elapsed_seconds':round(time.monotonic()-start,3)})
    status,state,_=call('/api/hand/start?player_count=2','POST',token=token);assert status==200
    decision=None
    for _ in range(100):
        if state['result']:break
        if state['current_player_id'] is None:
            status,state,_=call('/api/hand/advance','POST',token=token);assert status==200;continue
        action='check' if 'check' in state['betting']['legal_actions'] else 'call'
        if state['current_player_id']=='hero':
            status,moved,_=call('/api/training/decision','POST',{'command_id':str(uuid.uuid4()),'hand_id':state['hand_id'],
                'history_length':len(state['history']),'action':action},token);assert status==200
            if state['street']=='river':decision=moved['decision_id']
            state=moved['state']
        else:
            status,state,_=call('/api/hand/action','POST',{'player_id':state['current_player_id'],'action':action},token);assert status==200
    assert state['result'] and decision is not None
    path='/api/river-lessons/history/'+str(decision)
    status,detail,_=call(path,token=token);assert status==200 and detail['supported'],detail.get('reason')
    assert call(path,token=other)[0]==404
    status,submitted,_=call(path+'/jobs','POST',{'version':detail['source_version'],**detail['model']},token);assert status==200
    result=finish_job(submitted)
    return {'api':base,'fixture_sha256':catalog['version'],'models':rows,
            'completed_river_review':result['status'],'private_profiles_verified':True,
            'scope':'New disposable profiles; synthetic lessons and their own passive trainer hand only. No existing users or rooms.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=json.dumps(check(args.url.rstrip('/')),indent=2)+'\n'
    if args.output:args.output.write_text(result)
    print(result,end='')
