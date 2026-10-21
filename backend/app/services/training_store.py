from __future__ import annotations

import hashlib
import json
import math
import secrets
import sqlite3
import uuid
from pathlib import Path
from threading import RLock

from app.models.poker import ActionType, Card, HandState, Player, Street
from app.services.betting_rules import betting_options, highest_bet
from app.services.hand_projection import project_hand
from app.services.room_repository import RoomStorageError


def action_review(action, analysis):
    matches = action == analysis.recommended_action
    return {
        'hand_id': analysis.hand_id, 'street': analysis.street.value,
        'chosen_action': action, 'recommended_action': analysis.recommended_action,
        'verdict': 'optimal' if matches else 'reconsider',
        'summary': ('Matches the coach heuristic. ' if matches else 'Differs from the coach heuristic; this alone does not establish an error. ') + analysis.coach_summary,
    }


def question_data(state, kind):
    options = betting_options(state, 'hero')
    if state.current_player_id != 'hero' or not options.legal_actions:
        raise ValueError('An exercise requires an active hero decision.')
    public = project_hand(state, 'hero')
    public['betting'] = None  # Legal-action answers are checked on the server.
    context = {'call_amount': options.call_amount, 'pot': state.pot,
               'highest_bet': highest_bet(state), 'last_full_raise': max(state.big_blind, state.last_full_raise),
               'hero_acted_at_bet': state.acted_at_bet.get('hero')}
    if kind == 'legal_actions':
        return {'kind': kind, 'prompt': 'Select every action currently allowed for you.',
                'hand': public, 'context': context}, [a.value for a in options.legal_actions]
    if kind != 'call_price' or len(state.players) != 2 or options.call_amount <= 0:
        raise ValueError('A call-price exercise requires a heads-up decision facing a bet.')
    hero = next(p for p in state.players if p.id == 'hero')
    uncallable = max(0, highest_bet(state) - hero.current_bet - options.call_amount)
    contestable = state.pot - uncallable
    context.update({'uncalled_return': uncallable, 'contestable_pot': contestable})
    return {'kind': kind, 'prompt': 'What equity percentage breaks even on a call, assuming no further betting or rake?',
            'hand': public, 'context': context}, 100 * options.call_amount / (contestable + options.call_amount)


def starter_state(short=False):
    state = HandState(
        hand_id='practice-short-call' if short else 'practice-call', street=Street.FLOP,
        pot=120 if short else 60, small_blind=5, big_blind=10,
        board=[Card(rank='9', suit='hearts'), Card(rank='T', suit='spades'), Card(rank='2', suit='diamonds')],
        players=[Player(id='hero', name='You', position='button', stack=20 if short else 100,
                        cards=[Card(rank='A', suit='hearts'), Card(rank='K', suit='diamonds')]),
                 Player(id='villain', name='Practice opponent', position='big_blind', stack=100,
                        current_bet=100 if short else 20)],
        current_player_id='hero', dealer_player_id='hero', last_full_raise=100 if short else 20,
        contributions={'hero': 10 if short else 20, 'villain': 110 if short else 40},
    )
    state.betting = betting_options(state)
    return state


class TrainingStore:
    def __init__(self, database_path):
        self.path = Path(database_path)
        self.connection = None
        self.lock = RLock()

    def open(self):
        # RoomRepository creates this private database before this store opens it.
        self.connection = sqlite3.connect(str(self.path), timeout=5, check_same_thread=False)
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS training_profiles (
                profile_id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS training_decisions (
                id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL, command_id TEXT NOT NULL,
                request_json TEXT NOT NULL, payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(profile_id, command_id)
            );
            CREATE TABLE IF NOT EXISTS training_questions (
                question_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL,
                source_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                answer_json TEXT NOT NULL, UNIQUE(profile_id, source_id, kind)
            );
            CREATE TABLE IF NOT EXISTS training_attempts (
                id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
                question_id TEXT NOT NULL, request_json TEXT NOT NULL, payload TEXT NOT NULL,
                correct INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(profile_id, attempt_id)
            );
            CREATE INDEX IF NOT EXISTS training_question_profile ON training_questions(profile_id);
            CREATE INDEX IF NOT EXISTS training_attempt_question ON training_attempts(profile_id, question_id, id);
        ''')
        self.connection.commit()

    def close(self):
        with self.lock:
            if self.connection:
                self.connection.close(); self.connection = None

    def create_profile(self):
        profile_id, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        with self.lock:
            try:
                with self.connection:
                    self.connection.execute('INSERT INTO training_profiles VALUES(?,?)',
                                            (profile_id, hashlib.sha256(token.encode()).hexdigest()))
                    for short in [False, True]:
                        for kind in ['call_price', 'legal_actions']:
                            self._add_question(profile_id, 'starter-short' if short else 'starter-standard',
                                               starter_state(short), kind, 'Practice scenario')
            except sqlite3.Error as exc:
                raise RoomStorageError('Could not create a saved training profile.') from exc
        return {'profile_id': profile_id, 'token': token}

    def authenticate(self, token):
        if not isinstance(token, str) or not token:
            raise PermissionError('Training profile authentication is required.')
        with self.lock:
            row = self.connection.execute('SELECT profile_id FROM training_profiles WHERE token_hash=?',
                                          (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None:
            raise PermissionError('Training profile authentication failed.')
        return row[0]

    def _add_question(self, profile_id, source_id, state, kind, source_label):
        public, answer = question_data(state, kind)
        public['source'] = source_label
        question_id = str(uuid.uuid4())
        public['question_id'] = question_id
        self.connection.execute('INSERT OR IGNORE INTO training_questions VALUES(?,?,?,?,?,?)',
                                (question_id, profile_id, source_id, kind, json.dumps(public), json.dumps(answer)))

    def cached_decision(self, profile_id, command_id, fingerprint):
        with self.lock:
            row = self.connection.execute('SELECT id, request_json, payload FROM training_decisions WHERE profile_id=? AND command_id=?',
                                          (profile_id, command_id)).fetchone()
        if row and row[1] != fingerprint:
            raise ValueError('This command ID was used with different contents.')
        return {'decision_id': row[0], **json.loads(row[2])} if row else None

    def save_decision(self, profile_id, command_id, fingerprint, state, analysis, action, amount):
        review = action_review(action.value, analysis)
        payload = {'hand': project_hand(state, 'hero'), 'analysis': analysis.model_dump(mode='json'),
                   'chosen_action': action.value, 'amount': amount, 'review': review}
        with self.lock:
            try:
                with self.connection:
                    cursor = self.connection.execute('INSERT INTO training_decisions(profile_id,command_id,request_json,payload) VALUES(?,?,?,?)',
                                                     (profile_id, command_id, fingerprint, json.dumps(payload)))
                    decision_id = cursor.lastrowid
                    self._add_question(profile_id, str(decision_id), state, 'legal_actions', 'Your saved decision')
                    if len(state.players) == 2 and state.betting.call_amount > 0:
                        self._add_question(profile_id, str(decision_id), state, 'call_price', 'Your saved decision')
            except sqlite3.Error as exc:
                raise RoomStorageError('Decision was not saved. The action was not applied; please retry.') from exc
        return {'decision_id': decision_id, **payload}

    def decisions(self, profile_id, before=None, limit=20):
        with self.lock:
            rows = self.connection.execute('''SELECT id,created_at,payload FROM training_decisions
                WHERE profile_id=? AND (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?''',
                (profile_id, before, before, limit + 1)).fetchall()
            items = []
            for decision_id, created_at, raw in rows[:limit]:
                payload = json.loads(raw)
                questions = self.connection.execute('SELECT question_id,kind FROM training_questions WHERE profile_id=? AND source_id=?',
                                                    (profile_id, str(decision_id))).fetchall()
                items.append({'decision_id': decision_id, 'created_at': created_at + 'Z', **payload,
                              'exercises': {kind: qid for qid, kind in questions}})
        return {'items': items, 'next_cursor': items[-1]['decision_id'] if len(rows) > limit else None}

    def question(self, profile_id, question_id):
        with self.lock:
            row = self.connection.execute('SELECT payload FROM training_questions WHERE profile_id=? AND question_id=?',
                                          (profile_id, question_id)).fetchone()
        if row is None:
            raise ValueError('Exercise not found.')
        return json.loads(row[0])

    def next_question(self, profile_id, kind, exclude=None):
        with self.lock:
            row = self.connection.execute('''SELECT q.payload FROM training_questions q
                LEFT JOIN training_attempts a ON a.id=(SELECT MAX(t.id) FROM training_attempts t
                    WHERE t.profile_id=q.profile_id AND t.question_id=q.question_id)
                WHERE q.profile_id=? AND q.kind=? AND q.question_id != COALESCE(?, '')
                ORDER BY CASE WHEN a.correct=0 THEN 0 WHEN a.id IS NULL THEN 1 ELSE 2 END,
                         COALESCE(a.id,0), q.rowid LIMIT 1''', (profile_id, kind, exclude)).fetchone()
        if row is None and exclude is not None:
            return self.next_question(profile_id, kind)
        if row is None:
            raise ValueError('No exercise of this type is available yet.')
        return json.loads(row[0])

    def answer(self, profile_id, request):
        fingerprint = request.model_dump_json()
        with self.lock:
            cached = self.connection.execute('SELECT request_json,payload FROM training_attempts WHERE profile_id=? AND attempt_id=?',
                                             (profile_id, request.attempt_id)).fetchone()
            if cached:
                if cached[0] != fingerprint:
                    raise ValueError('This attempt ID was used with different contents.')
                return json.loads(cached[1])
            row = self.connection.execute('SELECT kind,payload,answer_json FROM training_questions WHERE profile_id=? AND question_id=?',
                                          (profile_id, request.question_id)).fetchone()
            if row is None:
                raise ValueError('Exercise not found.')
            kind, raw, expected_raw = row
            question, expected = json.loads(raw), json.loads(expected_raw)
            if kind == 'call_price':
                if request.percent is None or request.actions is not None or not math.isfinite(request.percent):
                    raise ValueError('Submit one percentage from 0 to 100.')
                correct = abs(request.percent - expected) <= .5 + 1e-9
                context = question['context']
                explanation = f"{context['call_amount']} / ({context['contestable_pot']} + {context['call_amount']}) = {expected:.1f}%."
                if context['uncalled_return']:
                    explanation += f" Exclude {context['uncalled_return']} uncallable chips returned to the opponent."
                explanation += ' This call price assumes no further betting or rake.'
            else:
                if request.actions is None or request.percent is not None:
                    raise ValueError('Select the legal actions.')
                submitted = [action.value for action in request.actions]
                correct = len(submitted) == len(set(submitted)) and set(submitted) == set(expected)
                explanation = 'Allowed actions: ' + ', '.join(expected) + '. '
                explanation += 'Check requires no outstanding call. Bet opens an unbet street; raise needs another funded opponent, available chips and reopened raise rights.'
            result = {'question_id': request.question_id, 'correct': correct, 'expected': expected,
                      'explanation': explanation, 'tolerance_percentage_points': .5 if kind == 'call_price' else None}
            try:
                with self.connection:
                    self.connection.execute('INSERT INTO training_attempts(profile_id,attempt_id,question_id,request_json,payload,correct) VALUES(?,?,?,?,?,?)',
                                            (profile_id, request.attempt_id, request.question_id, fingerprint, json.dumps(result), int(correct)))
            except sqlite3.Error as exc:
                raise RoomStorageError('Answer was not saved. Please retry.') from exc
            return result

    def progress(self, profile_id):
        with self.lock:
            attempts, correct = self.connection.execute('SELECT count(*),COALESCE(sum(correct),0) FROM training_attempts WHERE profile_id=?',
                                                       (profile_id,)).fetchone()
            total, solved = self.connection.execute('''SELECT count(*),COALESCE(sum(COALESCE((SELECT a.correct
                FROM training_attempts a WHERE a.profile_id=q.profile_id AND a.question_id=q.question_id ORDER BY a.id DESC LIMIT 1),0)),0)
                FROM training_questions q WHERE q.profile_id=?''', (profile_id,)).fetchone()
        return {'attempts': attempts, 'correct_attempts': correct, 'questions': total,
                'last_answer_correct': solved, 'to_review': total - solved}
