from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import patch

from backend.app.postgres_store import PostgresStore
from backend.app.store import InMemoryStore
from backend.app.store_factory import create_store


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(str(query).split()).upper()
        if normalized.startswith("SELECT STATE FROM RUNTIME_STORE_STATE"):
            row_id = params[0]
            payload = self.rows.get(row_id)
            return _FakeResult((json.loads(payload),) if payload is not None else None)
        if "INSERT INTO RUNTIME_STORE_STATE" in normalized:
            row_id, payload = params
            self.rows[row_id] = payload
            return _FakeResult(None)
        return _FakeResult(None)


class _FakePsycopg(types.SimpleNamespace):
    def __init__(self):
        self.rows = {}
        super().__init__(connect=self.connect)

    def connect(self, _dsn, autocommit=True):
        assert autocommit is True
        return _FakeConnection(self.rows)


class PostgresStoreTests(unittest.TestCase):
    def test_create_store_uses_in_memory_without_database_url(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            store = create_store()
        self.assertIsInstance(store, InMemoryStore)

    def test_postgres_store_persists_state_between_instances(self) -> None:
        fake_psycopg = _FakePsycopg()
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            first = PostgresStore("postgres://example/app")
            repo = first.upsert_repository(
                {
                    "provider": "github",
                    "accountLogin": "team",
                    "owner": "team",
                    "name": "service",
                    "fullName": "team/service",
                    "defaultBranch": "main",
                }
            )
            pr = first.get_or_create_pr(repo["id"], 42, {"title": "Persist me"})

            second = PostgresStore("postgres://example/app")

        loaded_repo = second.get_repo(repo["id"])
        loaded_pr = second.get_pr(pr["id"])
        self.assertEqual(loaded_repo["fullName"], "team/service")
        self.assertEqual(loaded_pr["title"], "Persist me")

    def test_create_store_uses_postgres_when_database_url_is_set(self) -> None:
        fake_psycopg = _FakePsycopg()
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            with patch.dict("os.environ", {"DATABASE_URL": "postgres://example/app"}, clear=True):
                store = create_store()
        self.assertIsInstance(store, PostgresStore)


if __name__ == "__main__":
    unittest.main()
