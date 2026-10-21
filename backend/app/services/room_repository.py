"""Private, local SQLite snapshots and an atomic room event journal."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


class RoomStorageError(RuntimeError):
    pass


class RoomRepository:
    def __init__(self, path):
        self.path = Path(path)
        self.connection = None

    def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        self.connection = sqlite3.connect(str(self.path), timeout=5)
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
        with self.connection:
            self.connection.execute('''
                INSERT INTO rooms(code, payload, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(code) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP
            ''', (record['code'], json.dumps(record)))
            self.connection.execute('INSERT INTO room_events(code,revision,kind,command_id,player_id) VALUES(?,?,?,?,?)',
                                    (record['code'], record['revision'], kind, command_id, player_id))
            hand = record.get('hand')
            if hand and hand['result']:
                self.connection.execute('INSERT OR IGNORE INTO completed_hands(code,hand_id,payload) VALUES(?,?,?)',
                                        (record['code'], hand['hand_id'], json.dumps(hand)))

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None
