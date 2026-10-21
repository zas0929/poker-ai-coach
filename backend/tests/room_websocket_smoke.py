import asyncio
import json
import os
import urllib.request
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

BASE = os.environ.get('POKER_TEST_API_BASE', 'http://127.0.0.1:8000').rstrip('/')
def post(path, data):
    request=urllib.request.Request(BASE+path, data=json.dumps(data).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request) as response:
        return json.load(response)
async def state(ws, revision=None):
    for _ in range(30):
        item=json.loads(await asyncio.wait_for(ws.recv(), 5))
        if item['type']=='state' and (revision is None or item['revision']>=revision):
            return item
    raise AssertionError('No snapshot')
async def command(ws, view, kind, **data):
    payload={'command_id':str(view['revision'])+kind,'revision':view['revision'],'kind':kind,**data}
    await ws.send(json.dumps(payload))
    return await state(ws,view['revision']+1),payload
async def main():
    a=post('/api/rooms',{'name':'Host'})
    b=post('/api/rooms/'+a['code']+'/join',{'name':'Guest'})
    url=BASE.replace('http://', 'ws://').replace('https://', 'wss://')+'/api/rooms/'+a['code']+'/ws'
    try:
        async with connect(url,origin='https://untrusted.example'):
            raise AssertionError('Untrusted origin accepted')
    except InvalidStatus:
        pass
    async with connect(url,origin='http://localhost:3000') as host, connect(url,origin='http://localhost:3000') as guest:
        await host.send(json.dumps({'token':a['token']})); await guest.send(json.dumps({'token':b['token']}))
        hv=await state(host); gv=await state(guest)
        hv,_=await command(host,hv,'ready',ready=True)
        gv=await state(guest,hv['revision'])
        gv,_=await command(guest,gv,'ready',ready=True)
        hv=await state(host,gv['revision'])
        hv,_=await command(host,hv,'start')
        gv=await state(guest,hv['revision'])
        assert hv['hand']['players'][1]['cards']==[] and gv['hand']['players'][0]['cards']==[]
        assert len(hv['hand']['players'][0]['cards'])==2
        hv,payload=await command(host,hv,'action',action='call',hand_id=hv['hand']['hand_id'])
        revision=hv['revision']; pot=hv['hand']['pot']
        await host.send(json.dumps(payload))
        hv=await state(host,revision)
        assert hv['revision']==revision and hv['hand']['pot']==pot
        gv=await state(guest,revision)
        gv,_=await command(guest,gv,'action',action='check',hand_id=gv['hand']['hand_id'])
        assert gv['hand']['street']=='flop'
        hv=await state(host,gv['revision'])
        assert hv['hand']['board']==gv['hand']['board'] and hv['hand']['pot']==gv['hand']['pot']
        current=hv['hand']['current_player_id']
    async with connect(url,origin='http://localhost:3000') as reconnected:
        await reconnected.send(json.dumps({'token':b['token']}))
        restored=await state(reconnected)
        assert restored['viewer_id']==b['player_id']
        assert restored['hand']['current_player_id']==current
        assert restored['hand']['players'][0]['cards']==[]
    print('WebSocket integration: origin guard, two seats, private cards, ready/start, duplicate action, automatic flop, matching board and reconnect: OK')
if __name__ == '__main__':
    asyncio.run(main())
