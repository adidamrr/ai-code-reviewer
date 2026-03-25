from __future__ import annotations

import os

from .postgres_store import PostgresStore
from .store import InMemoryStore


def create_store() -> InMemoryStore:
    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        return InMemoryStore()
    return PostgresStore(database_url)
