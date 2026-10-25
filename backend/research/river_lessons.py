"""Opt-in local teaching catalog backed by the frozen bounded analysis contract."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock

from research.analysis_contract import ResearchLimits, expected_root_actions, validate_request
from research.shadow_executor import ShadowExecutor, TERMINAL
from research.lesson_values import analyze


class LessonError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


class RiverLessons:
    def __init__(self, executor=None, store=None):
        path = Path(__file__).parent / 'fixtures/river-lessons-v1.json'
        raw = path.read_bytes()
        self.version = sha256(raw).hexdigest()
        data = json.loads(raw)
        if data['version'] != 1 or len(data['examples']) != 5:
            raise ValueError('Versioned five-example catalog required.')
        self.examples = {row['id']: row for row in data['examples']}
        if set(self.examples) != {f'river-{n}' for n in range(1, 6)}:
            raise ValueError('Catalog must cover one to five opponents.')
        for row in self.examples.values():
            validate_request(row['request'])
        self.limits = ResearchLimits(iterations=300, wall_seconds=10, memory_mib=128)
        self.executor = executor if executor is not None else ShadowExecutor(max_pending=2, max_retained=64, analyzer=analyze)
        self.store = store
        self.owners = OrderedDict()
        self.lock = RLock()

    def catalog(self):
        lessons = []
        for row in self.examples.values():
            request = row['request']
            snapshot = request['snapshot']
            lessons.append({'id': row['id'], 'opponents': row['opponents'],
                'board': snapshot['board'], 'own_hand': request['own_hand'],
                'actor_id': snapshot['actor_id'], 'button_id': snapshot['button_id'],
                'pot': snapshot['pot'], 'small_blind': snapshot['small_blind'], 'big_blind': snapshot['big_blind'],
                'players': snapshot['players'], 'tree': request['input'],
                'actions': expected_root_actions(request)})
        return deepcopy({'enabled': True, 'version': self.version, 'lessons': lessons,
                         'limits': {'wall_seconds': self.limits.wall_seconds, 'iterations': self.limits.iterations,
                                    'quality_gate_pct_pot': self.limits.quality_gate_pct_pot}})

    def submit(self, owner, lesson_id, version):
        if not owner:
            raise LessonError('PROFILE_REQUIRED', 401)
        if version != self.version:
            raise LessonError('LESSON_VERSION_CHANGED', 409)
        if lesson_id not in self.examples:
            raise LessonError('LESSON_NOT_FOUND', 404)
        return self._submit(owner, lesson_id, version, self.examples[lesson_id]['request'])

    def _submit(self, owner, lesson_id, version, request):
        with self.lock:
            if owner not in self.owners:
                while len(self.owners) >= 64:
                    victim = next((key for key, item in self.owners.items()
                                   if self.executor.poll(item['ticket_id'])['state'] in TERMINAL | {'expired'}), None)
                    if victim is None:
                        raise LessonError('LESSON_BUSY', 503)
                    self.owners.pop(victim)
            previous = self.owners.get(owner)
            if previous is not None and self.executor.poll(previous['ticket_id'])['state'] in ('queued', 'running'):
                # A fresh UI run gets a fresh ticket even for the same example.
                # A delayed DELETE for the previous ticket must not cancel it.
                self.executor.cancel(previous['ticket_id'])
            submitted = self.executor.submit('river-lesson:' + owner, request, self.limits)
            if submitted.get('ticket_id') is None:
                raise LessonError('LESSON_BUSY', 503)
            self.owners[owner] = {'ticket_id': submitted['ticket_id'], 'lesson_id': lesson_id, 'version': version}
            self.owners.move_to_end(owner)
            return {**submitted, 'lesson_id': lesson_id, 'version': version}

    def history(self, owner, before=None):
        if self.store is None:
            raise LessonError('HISTORY_UNAVAILABLE', 503)
        return self.store.completed_river_decisions(owner, before)

    def history_model(self, owner, decision_id, model=None, version=None):
        if self.store is None:
            raise LessonError('HISTORY_UNAVAILABLE', 503)
        try:
            saved = self.store.completed_river_decision(owner, decision_id)
        except ValueError:
            raise LessonError('HISTORY_NOT_FOUND', 404)
        from research.history_river import source, assess
        try:
            snapshot, hand, current, defaults = source(saved)
        except (ValueError, TypeError, KeyError, StopIteration):
            raise LessonError('HISTORY_SNAPSHOT_UNAVAILABLE', 422)
        if version is not None and version != current:
            raise LessonError('LESSON_VERSION_CHANGED', 409)
        return assess(saved, snapshot, hand, current, defaults if model is None else model)

    def history_detail(self, owner, decision_id):
        return self.history_model(owner, decision_id)[0]

    def submit_history(self, owner, decision_id, model, version):
        assessment, request = self.history_model(owner, decision_id, model, version)
        if not assessment['supported']:
            return {'ticket_id':None,'assessment':assessment}
        job = self._submit(owner, assessment['lesson']['id'], assessment['version'], request)
        return {**job,'assessment':assessment}

    def poll(self, owner, ticket_id):
        with self.lock:
            item = self.owners.get(owner)
            if item is None or item['ticket_id'] != ticket_id:
                raise LessonError('LESSON_JOB_NOT_FOUND', 404)
            return {**self.executor.poll(ticket_id), 'lesson_id': item['lesson_id'], 'version': item['version']}

    def cancel(self, owner, ticket_id):
        with self.lock:
            self.poll(owner, ticket_id)
            self.executor.cancel(ticket_id)
            return self.poll(owner, ticket_id)

    def close(self):
        self.executor.close()
