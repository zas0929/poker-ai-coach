"""Explicit acceptance probe: disposable profiles only, passive training hands."""
import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from app.models.poker import HandState
from app.services.trainer_solver import position_text

ALLOWED = {'http://127.0.0.1:8012', 'https://poker-ai-coach-api.onrender.com'}


def run(base):
    if base not in ALLOWED:
        raise ValueError('Only the dedicated local preview or authorized staging API is allowed.')

    def call(path, token=None, body=None, method=None):
        req = Request(base+path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type':'application/json', **({'Authorization':'Bearer '+token} if token else {})},
                      method=method or ('POST' if body is not None else 'GET'))
        try:
            with urlopen(req, timeout=60) as response:
                return response.status, json.load(response), response.headers
        except HTTPError as error:
            return error.code, json.load(error), error.headers

    assert call('/api/hand/solver',body={'position':'[]','nonce':'probe'})[0] == 401
    rows=[]
    for count in range(2,7):
        _, profile, _ = call('/api/training/profiles', body={})
        token=profile['token']
        _, other, _ = call('/api/training/profiles', body={})
        status,state,_=call('/api/hand/start?player_count='+str(count),token,{},'POST')
        assert status==200
        for _ in range(120):
            if state['street']=='river' and state['current_player_id']=='hero':break
            assert not state['result']
            if state['current_player_id'] is None:
                status,state,_=call('/api/hand/advance',token,{},'POST')
            else:
                action='check' if 'check' in state['betting']['legal_actions'] else 'call'
                status,state,_=call('/api/hand/action',token,{'player_id':state['current_player_id'],'action':action})
            assert status==200
        assert state['street']=='river' and state['current_player_id']=='hero'
        position=position_text(HandState.model_validate(state))
        start=time.monotonic()
        status,job,headers=call('/api/hand/solver',token,{'position':position,'nonce':'first'})
        assert status==200,(status,job)
        assert 'no-store' in headers.get('Cache-Control','')
        ticket=job['ticket_id'];assert ticket,job
        assert call('/api/hand/solver/'+ticket,other['token'])[0]==404
        read=time.monotonic();assert call('/api/hand/state',token)[0]==200
        responsive=time.monotonic()-read
        assert responsive<2.0,responsive
        while job['state'] in ('queued','running'):
            assert time.monotonic()-start<30
            time.sleep(.15)
            status,job,_=call('/api/hand/solver/'+ticket,token)
            assert status==200,(status,job)
        assert job['state'] in ('ready','unavailable'),job
        if job['state']=='ready':
            assert job['actions'] and job['quality']['passed']
            assert not job['replaces_heuristic']
        status,reused,_=call('/api/hand/solver',token,{'position':position,'nonce':'second'})
        assert status==200 and reused['ticket_id']!=ticket
        assert reused['state']==job['state']
        call('/api/hand/solver/'+ticket,token,method='DELETE')
        assert call('/api/hand/solver/'+reused['ticket_id'],token)[1]['state']==job['state']
        action='check' if 'check' in state['betting']['legal_actions'] else 'call'
        assert call('/api/hand/action',token,{'player_id':'hero','action':action})[0]==200
        stale=call('/api/hand/solver/'+reused['ticket_id'],token)[1]
        assert stale['state']=='stale' and stale['actions'] is None,stale
        assert call('/api/hand/solver',token,{'position':position,'nonce':'old'})[0]==409
        rows.append({'opponents':count-1,'state':job['state'],'reason':job.get('reason'),
                     'quality':job.get('quality',{}).get('value') if job.get('quality') else None,
                     'total_seconds':round(time.monotonic()-start,3),
                     'concurrent_state_read_seconds':round(responsive,3),
                     'cached_job_reused':True,'foreign_profile_rejected':True,'stale_result_removed':True})
        print(json.dumps(rows[-1]),flush=True)
    return {'api':base,'scope':'Disposable passive training profiles, actual native worker, no existing rooms', 'results':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8012')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(); result=run(args.url)
    if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n')
