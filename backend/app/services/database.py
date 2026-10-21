"""Local SQLite and hosted PostgreSQL connections for the same private stores."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class DatabaseFailure(RuntimeError):
    pass


DATABASE_ERRORS = (sqlite3.Error, DatabaseFailure)
POSTGRES_NOW = "to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"


def is_postgres(source):
    return str(source).startswith(('postgres://', 'postgresql://'))


class PostgresConnection:
    """A qmark interface for our fixed application SQL, with explicit transactions.

    Autocommit keeps read-only calls out of idle transactions. A `with` block
    groups a room snapshot, journal and payouts (or a decision and exercises).
    Application SQL uses qmarks only as placeholders, never inside SQL literals.
    """
    def __init__(self, source):
        import psycopg
        self.driver = psycopg
        self.source = source
        query = parse_qs(urlsplit(source).query)
        if query.get('sslmode', ['require'])[-1] not in {'require', 'verify-ca', 'verify-full'}:
            raise ValueError('Hosted PostgreSQL requires TLS.')
        self.sslmode = query.get('sslmode', ['require'])[-1]
        self.transactions = []
        self._connect()

    def _connect(self):
        try:
            self.raw = self.driver.connect(str(self.source), autocommit=True, connect_timeout=10,
                                           sslmode=self.sslmode, prepare_threshold=None)
            self.raw.execute('SET search_path = poker_private')
            self.raw.execute("SET timezone = 'UTC'")
            self.raw.execute('SET statement_timeout = 15000')
        except self.driver.Error as exc:
            raise DatabaseFailure('Could not connect to hosted storage.') from exc

    def _ensure_open(self):
        if self.raw.closed or self.raw.broken:
            self._connect()

    def execute(self, sql, parameters=()):
        try:
            self._ensure_open()
            return self.raw.execute(sql.replace('?', '%s'), parameters)
        except self.driver.Error as exc:
            raise DatabaseFailure('Hosted storage query failed.') from exc

    def executescript(self, script):
        with self:
            for statement in script.split(';'):
                if statement.strip():
                    self.execute(statement)

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()

    def __enter__(self):
        self._ensure_open()
        transaction = self.raw.transaction()
        try:
            transaction.__enter__()
        except self.driver.Error as exc:
            raise DatabaseFailure('Hosted storage transaction failed.') from exc
        self.transactions.append(transaction)
        return self

    def __exit__(self, kind, value, traceback):
        try:
            return self.transactions.pop().__exit__(kind, value, traceback)
        except self.driver.Error as exc:
            raise DatabaseFailure('Hosted storage transaction failed.') from exc


def connect(source, threaded=False):
    if is_postgres(source):
        return PostgresConnection(source)
    return sqlite3.connect(str(Path(source)), timeout=5, check_same_thread=not threaded)


def initialize_postgres(connection):
    connection.executescript((Path(__file__).with_name('postgres_schema.sql')).read_text())
