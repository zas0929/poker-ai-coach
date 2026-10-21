import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.database import DatabaseFailure, PostgresConnection, connect, is_postgres


class DatabaseTests(unittest.TestCase):
    def driver(self):
        driver = SimpleNamespace(Error=type('PostgresError', (Exception,), {}), connect=MagicMock())
        raw = driver.connect.return_value
        raw.closed = raw.broken = False
        return driver, raw

    def test_local_sqlite_connection_keeps_transaction_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / 'local.sqlite3')
            connection.execute('CREATE TABLE records(id INTEGER PRIMARY KEY)')
            with self.assertRaises(sqlite3.Error):
                with connection:
                    connection.execute('INSERT INTO records VALUES(1)')
                    connection.execute('INSERT INTO records VALUES(1)')
            self.assertEqual(connection.execute('SELECT count(*) FROM records').fetchone()[0], 0)
            connection.close()

    def test_postgres_uses_tls_and_disables_prepared_statements_for_pooler(self):
        driver, raw = self.driver()
        with patch.dict(sys.modules, {'psycopg': driver}):
            connection = connect('postgresql://test@database.invalid/poker')
            self.assertIsInstance(connection, PostgresConnection)
            self.assertTrue(driver.connect.call_args.kwargs['autocommit'])
            self.assertEqual(driver.connect.call_args.kwargs['sslmode'], 'require')
            self.assertIsNone(driver.connect.call_args.kwargs['prepare_threshold'])
            self.assertIn('SET search_path = poker_private', [call.args[0] for call in raw.execute.call_args_list])

    def test_hosted_connection_rejects_disabled_tls(self):
        driver, raw = self.driver()
        with patch.dict(sys.modules, {'psycopg': driver}):
            for mode in ['disable', 'prefer', 'allow']:
                with self.assertRaises(ValueError):
                    connect('postgresql://test@database.invalid/poker?sslmode=' + mode)
            driver.connect.assert_not_called()

    def test_values_are_bound_without_sql_interpolation(self):
        driver, raw = self.driver()
        with patch.dict(sys.modules, {'psycopg': driver}):
            connection = connect('postgresql://test@database.invalid/poker')
            value = "x'); DROP TABLE rooms;--?"
            connection.execute('SELECT payload FROM rooms WHERE code=?', (value,))
            raw.execute.assert_called_with('SELECT payload FROM rooms WHERE code=%s', (value,))

    def test_explicit_transaction_rolls_back_on_storage_error_and_next_call_works(self):
        driver, raw = self.driver()
        with patch.dict(sys.modules, {'psycopg': driver}):
            connection = connect('postgresql://test@database.invalid/poker')
            transaction = raw.transaction.return_value
            raw.execute.side_effect = driver.Error('private diagnostic')
            with self.assertRaises(DatabaseFailure):
                with connection:
                    connection.execute('INSERT INTO rooms VALUES(?, ?, ?)', ('test', '{}', 'now'))
            self.assertIs(transaction.__exit__.call_args.args[0], DatabaseFailure)
            raw.execute.side_effect = None
            connection.execute('SELECT 1')
            self.assertFalse(connection.transactions)

    def test_closed_connections_reopen_before_the_next_operation(self):
        driver, raw = self.driver()
        with patch.dict(sys.modules, {'psycopg': driver}):
            connection = connect('postgresql://test@database.invalid/poker')
            raw.closed = True
            connection.execute('SELECT 1')
            self.assertEqual(driver.connect.call_count, 2)

    def test_connection_errors_do_not_expose_a_secret_in_the_public_error(self):
        driver, raw = self.driver()
        driver.connect.side_effect = driver.Error('password=private-test-secret')
        with patch.dict(sys.modules, {'psycopg': driver}):
            with self.assertRaises(DatabaseFailure) as error:
                connect('postgresql://test@database.invalid/poker')
            self.assertNotIn('private-test-secret', str(error.exception))

    def test_schema_keeps_cards_tokens_and_answers_outside_the_public_api(self):
        schema = Path(__file__).parents[1] / 'app/services/postgres_schema.sql'
        text = schema.read_text()
        self.assertIn('REVOKE ALL ON SCHEMA poker_private FROM PUBLIC', text)
        for table in ['rooms', 'room_events', 'completed_hands', 'training_profiles', 'training_decisions', 'training_questions', 'training_attempts']:
            self.assertIn('ALTER TABLE ' + table + ' ENABLE ROW LEVEL SECURITY', text)
        self.assertTrue(is_postgres('postgres://user@host/db'))
        self.assertFalse(is_postgres('/private/tmp/test.sqlite3'))
