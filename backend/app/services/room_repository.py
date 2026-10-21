"""Private, local SQLite snapshots and an atomic room event journal."""
from __future__ import annotations

import json
import os
from pathlib import Path
from app.services.database import connect, is_postgres, initialize_postgres, POSTGRES_NOW


class RoomStorageError(RuntimeError):
    pass


class RoomRepository:
    def __init__(self, path):
        self.source = str(path)
        self.postgres = is_postgres(path)
        self.path = None if self.postgres else Path(path)
        self.connection = None

    def open(self):
        if self.postgres:
            self.connection = connect(self.source)
            initialize_postgres(self.connection)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        self.connection = connect(self.source)
        self.connection.execute('PRAGMA journal_mode=DELETE')
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS rooms (
                code TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS room_events (
                id INTEGER PRIMARY KEY, code TEXT NOT NULL, revision INTEGER NOT NULL,
                kind TEXT NOT NULL, command_id TEXT, player_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS completed_hands (
                code TEXT NOT NULL, hand_id TEXT NOT NULL, payload TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (code, hand_id)
            );
        ''')
        self.connection.commit()

    def load(self):
        return [json.loads(row[0]) for row in self.connection.execute('SELECT payload FROM rooms ORDER BY code')]

    def save(self, record, kind, command_id=None, player_id=None):
        # One transaction includes the authoritative state, replay protection and journal.
        now = POSTGRES_NOW if self.postgres else 'CURRENT_TIMESTAMP'
        with self.connection:
            self.connection.execute(f'''
                INSERT INTO rooms(code, payload, updated_at) VALUES (?, ?, {now})
                ON CONFLICT(code) DO UPDATE SET payload=excluded.payload, updated_at={now}
            ''', (record['code'], json.dumps(record)))
            self.connection.execute('INSERT INTO room_events(code,revision,kind,command_id,player_id) VALUES(?,?,?,?,?)',
                                    (record['code'], record['revision'], kind, command_id, player_id))
            hand = record.get('hand')
            if hand and hand['result']:
                self.connection.execute('INSERT INTO completed_hands(code,hand_id,payload) VALUES(?,?,?) ON CONFLICT(code,hand_id) DO NOTHING',
                                        (record['code'], hand['hand_id'], json.dumps(hand)))

    def history_page(self, code, player_id, limit=20, before=None):
        cursor = 'h.id' if self.postgres else 'h.rowid'
        membership = ("EXISTS (SELECT 1 FROM jsonb_array_elements(h.payload::jsonb->'players') p WHERE p->>'id'=?)"
                      if self.postgres else
                      "EXISTS (SELECT 1 FROM json_each(h.payload, '$.players') p WHERE json_extract(p.value, '$.id')=?)")
        rows = self.connection.execute(f'''SELECT {cursor}, h.completed_at, h.payload
            FROM completed_hands h WHERE h.code=? AND (CAST(? AS BIGINT) IS NULL OR {cursor} < ?)
            AND {membership} ORDER BY {cursor} DESC LIMIT ?''',
            (code, before, before, player_id, limit + 1)).fetchall()
        from app.services.hand_archive import hand_summary
        items = [hand_summary(json.loads(payload), player_id, cursor, completed_at)
                 for cursor, completed_at, payload in rows[:limit]]
        return {'items': items, 'next_cursor': items[-1]['cursor'] if len(rows) > limit else None}

    def archived_hand(self, code, hand_id, player_id):
        row = self.connection.execute('SELECT payload FROM completed_hands WHERE code=? AND hand_id=?',
                                      (code, hand_id)).fetchone()
        if row is None:
            raise ValueError('Archived hand not found.')
        from app.services.hand_archive import replay_hand
        return replay_hand(json.loads(row[0]), player_id)

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None
