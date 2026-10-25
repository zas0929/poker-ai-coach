import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Response
from pydantic import ValidationError
from app.api.hand import training_owner
from app.api import river_lessons as api
from research.river_lessons import RiverLessons, LessonError
from research.river_snapshot import build_river_from_snapshot


class TestExecutor:
    def __init__(self):
        self.items = {}
        self.closed = False
        self.full = False

    def submit(self, context, request, limits):
        if self.full:
            return {'status': 'queue_full', 'ticket_id': None}
        ticket = 'ticket-' + str(len(self.items)+1)
        self.items[ticket] = {'state': 'queued', 'result': None, 'context': context}
        return {'status': 'queued', 'ticket_id': ticket, 'job_id': ticket}

    def poll(self, ticket):
        row = self.items.get(ticket, {'state': 'expired', 'result': None})
        return {'ticket_id': ticket, 'state': row['state'], 'result': row['result']}

    def cancel(self, ticket):
        self.items[ticket]['state'] = 'cancelled'
        return True

    def close(self):
        self.closed = True


class RiverLessonTests(unittest.TestCase):
    def setUp(self):
        self.executor = TestExecutor()
        self.lessons = RiverLessons(self.executor)

    def test_catalog_models_cover_2_to_6_seats_and_are_defensive_copies(self):
        catalog = self.lessons.catalog()
        self.assertEqual([l['opponents'] for l in catalog['lessons']], [1,2,3,4,5])
        for row in self.lessons.examples.values():
            request = row['request']
            game, _ = build_river_from_snapshot(request['snapshot'], request['selected_hands'], **request['input'])
            self.assertGreater(len(game.deals), 0)
            self.assertLessEqual(len(game.deals), 64)
            self.assertIn(request['own_hand'], request['selected_hands'][request['snapshot']['actor_id']])
            self.assertEqual(list(game.root.actions), ['CHECK', 'BET 10', 'BET 20'])
            self.assertTrue(all(len(p['range']) == 2 and 'cards' not in p and 'name' not in p
                                for p in request['snapshot']['players']))
        catalog['lessons'][0]['players'].clear()
        self.assertEqual(len(self.lessons.catalog()['lessons'][0]['players']), 2)

    def test_foreign_profile_cannot_poll_cancel_or_replace_another_ticket(self):
        a = self.lessons.submit('alice', 'river-1', self.lessons.version)
        b = self.lessons.submit('bob', 'river-1', self.lessons.version)
        self.assertNotEqual(a['ticket_id'], b['ticket_id'])
        for operation in (self.lessons.poll, self.lessons.cancel):
            with self.assertRaises(LessonError) as e:
                operation('bob', a['ticket_id'])
            self.assertEqual(e.exception.status, 404)
        self.assertEqual(self.lessons.poll('alice', a['ticket_id'])['lesson_id'], 'river-1')
        next_job = self.lessons.submit('alice', 'river-5', self.lessons.version)
        with self.assertRaises(LessonError):
            self.lessons.poll('alice', a['ticket_id'])
        self.assertEqual(self.lessons.poll('alice', next_job['ticket_id'])['lesson_id'], 'river-5')
        restarted = self.lessons.submit('alice', 'river-5', self.lessons.version)
        self.assertNotEqual(restarted['ticket_id'], next_job['ticket_id'])
        with self.assertRaises(LessonError):
            self.lessons.cancel('alice', next_job['ticket_id'])
        self.assertEqual(self.lessons.poll('alice', restarted['ticket_id'])['state'], 'queued')
        self.assertEqual(self.lessons.poll('bob', b['ticket_id'])['state'], 'queued')

    def test_wrong_version_unknown_example_and_full_queue_never_admit_jobs(self):
        for args, status in [(('alice','river-1','0'*64),409), (('alice','unknown',self.lessons.version),404),
                             ((None,'river-1',self.lessons.version),401)]:
            with self.assertRaises(LessonError) as e:
                self.lessons.submit(*args)
            self.assertEqual(e.exception.status,status)
        self.assertFalse(self.executor.items)
        self.executor.full = True
        with self.assertRaises(LessonError) as e:
            self.lessons.submit('alice','river-1',self.lessons.version)
        self.assertEqual(e.exception.code,'LESSON_BUSY')
        self.assertFalse(self.lessons.owners)

    def test_retention_never_evicts_active_profiles_but_reuses_finished_capacity(self):
        for i in range(64):
            self.lessons.submit(str(i),'river-1',self.lessons.version)
        with self.assertRaises(LessonError):
            self.lessons.submit('next','river-1',self.lessons.version)
        self.executor.items['ticket-1']['state'] = 'completed'
        self.lessons.submit('next','river-1',self.lessons.version)
        self.assertEqual(len(self.lessons.owners),64)
        self.assertNotIn('0',self.lessons.owners)
        self.assertIn('1',self.lessons.owners)

    def test_api_requires_profile_restricts_payload_and_preserves_private_identity(self):
        body = api.LessonRequest(lesson_id='river-1',version=self.lessons.version)
        with patch.object(api.river_lessons,'service',return_value=self.lessons):
            binding = training_owner.set(None)
            try:
                with self.assertRaises(HTTPException) as e:
                    api.submit(body)
                self.assertEqual(e.exception.status_code,401)
            finally:training_owner.reset(binding)
            binding = training_owner.set('alice')
            try:
                job = api.submit(body)
                self.assertEqual(api.poll(job['ticket_id'])['lesson_id'],'river-1')
                self.assertEqual(api.cancel(job['ticket_id'])['state'],'cancelled')
            finally:training_owner.reset(binding)
        for extra in ({'snapshot':{}}, {'iterations':2000}, {'lesson_id':True}, {'version':'stale'}):
            with self.assertRaises(ValidationError):
                api.LessonRequest(**{**body.model_dump(),**extra})
        with patch.object(api.river_lessons,'catalog',return_value={'enabled':False}):
            response=Response();self.assertFalse(api.catalog(response)['enabled'])
            self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_default_app_does_not_import_or_start_research(self):
        env=dict(os.environ)
        env.pop('POKER_LOCAL_RIVER_LESSONS',None)
        env.pop('POKER_LOCAL_TRAINER_SHADOW',None)
        code='import json,sys;import app.main;from app.services.river_lessons import catalog;print(json.dumps([catalog(),[m for m in sys.modules if m=="research" or m.startswith("research.")]]))'
        result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True,timeout=10,check=True)
        catalog,modules=json.loads(result.stdout)
        self.assertFalse(catalog['enabled'])
        self.assertEqual(modules,[])
