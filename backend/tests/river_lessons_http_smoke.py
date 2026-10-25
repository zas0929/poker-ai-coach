"""Explicit localhost-only integration check; creates disposable browser profiles."""
import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def check(base):
    if urlsplit(base).hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('This smoke check is for an explicit local test server only.')
    def call(path, method='GET', body=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                          method=method, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                return response.status, json.load(response), {k.lower():v for k,v in response.headers.items()}
        except HTTPError as error:
            return error.code, json.loads(error.read()), {k.lower():v for k,v in error.headers.items()}
    status, catalog, _ = call('/api/river-lessons')
    assert status == 200 and catalog['enabled']
    _, a, _ = call('/api/training/profiles', 'POST')
    _, b, _ = call('/api/training/profiles', 'POST')
    a, b = a['token'], b['token']
    def submit(lesson):
        return call('/api/river-lessons/jobs', 'POST', {'lesson_id':lesson, 'version':catalog['version']}, a)
    assert call('/api/river-lessons/jobs', 'POST', {'lesson_id':'river-1', 'version':catalog['version']})[0] == 401
    _, original, _ = call('/api/hand/start', 'POST', token=a)
    rows = []
    for example in catalog['lessons']:
        started = time.monotonic()
        status, job, headers = submit(example['id'])
        assert status == 200 and 'no-store' in headers['cache-control'] and 'Authorization' in headers['vary']
        path = '/api/river-lessons/jobs/' + job['ticket_id']
        assert call(path, token=b)[0] == 404 and call(path, 'DELETE', token=b)[0] == 404
        deadline = time.monotonic() + 15
        while True:
            status, current, _ = call(path, token=a)
            assert status == 200
            if current['state'] in ('completed', 'error', 'cancelled', 'stale'):
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        result = current['result']
        assert result['status'] == 'ready'
        assert result['candidate']['own_hand'] == example['own_hand']
        assert result['candidate']['actions'] == example['actions']
        assert abs(sum(result['candidate']['probabilities'])-1) < 1e-8
        assert result['quality']['passed'] and not result['admission']['live_advice_allowed']
        rows.append({'lesson_id':example['id'], 'opponents':example['opponents'], 'status':result['status'],
            'quality_pct_pot':result['quality']['value'], 'actions':result['candidate']['actions'],
            'probabilities':result['candidate']['probabilities'], 'elapsed_seconds':round(time.monotonic()-started,3)})
    _, after, _ = call('/api/hand/state', token=a)
    assert original['hand_id'] == after['hand_id'] and original['history'] == after['history'] and original['players'] == after['players']
    _, old, _ = submit('river-5')
    _, new, _ = submit('river-5')
    assert old['ticket_id'] != new['ticket_id']
    assert call('/api/river-lessons/jobs/'+old['ticket_id'], 'DELETE', token=a)[0] == 404
    status, cancelled, _ = call('/api/river-lessons/jobs/'+new['ticket_id'], 'DELETE', token=a)
    assert status == 200 and cancelled['state'] == 'cancelled'
    return {'scope':'Real localhost HTTP -> profile-isolated lesson API -> bounded native subprocess. Synthetic models only. No live hand mutation.',
        'fixture_sha256':catalog['version'], 'checks':{'unauthorized_rejected':True, 'foreign_poll_cancel_rejected':True,
        'private_no_store':True, 'live_hand_preserved':True, 'rapid_restart_old_cancel_rejected':True, 'cancelled':True}, 'results':rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8011')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = json.dumps(check(args.url.rstrip('/')), indent=2) + '\n'
    if args.output:
        args.output.write_text(report)
    print(report, end='')
