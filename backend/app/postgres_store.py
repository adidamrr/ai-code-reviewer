from __future__ import annotations

import importlib
import json
import os
from typing import Any

from .store import InMemoryStore

STATE_ROW_ID = "default"


class PostgresStore(InMemoryStore):
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = (database_url or os.getenv("DATABASE_URL") or "").strip()
        if not self.database_url:
            raise ValueError("DATABASE_URL is required for PostgresStore")
        self._psycopg = self._load_psycopg()
        super().__init__()
        self._ensure_schema()
        state = self._load_state()
        if state is None:
            self._save_state()
        else:
            self.import_state(state)

    def _load_psycopg(self) -> Any:
        try:
            return importlib.import_module("psycopg")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Postgres support requires the 'psycopg' package. Install backend dependencies again."
            ) from exc

    def _connect(self) -> Any:
        return self._psycopg.connect(self.database_url, autocommit=True)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_store_state (
                  id TEXT PRIMARY KEY,
                  state JSONB NOT NULL,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    def _load_state(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM runtime_store_state WHERE id = %s",
                (STATE_ROW_ID,),
            ).fetchone()
        if not row:
            return None
        payload = row[0] if isinstance(row, tuple) else row["state"]
        if isinstance(payload, str):
            return json.loads(payload)
        return dict(payload)

    def _save_state(self) -> None:
        payload = json.dumps(self.export_state(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_store_state (id, state, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (id) DO UPDATE
                SET state = EXCLUDED.state,
                    updated_at = NOW()
                """,
                (STATE_ROW_ID, payload),
            )

    def _mutate(self, callback):
        result = callback()
        self._save_state()
        return result

    def _mutate_with_super(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        return self._mutate(lambda: getattr(super(PostgresStore, self), method_name)(*args, **kwargs))

    def _store_feature_snapshot(self, suggestion: dict[str, Any]) -> None:
        super()._store_feature_snapshot(suggestion)
        self._save_state()

    def retrain_adaptation_model(self) -> dict[str, Any]:
        return self._mutate_with_super("retrain_adaptation_model")

    def upsert_github_installation(self, installation_id: int, account_login: str) -> dict[str, Any]:
        return self._mutate_with_super("upsert_github_installation", installation_id, account_login)

    def upsert_repository(self, data: dict[str, str]) -> dict[str, Any]:
        return self._mutate_with_super("upsert_repository", data)

    def get_or_create_pr(self, repo_id: str, number: int, payload: dict[str, Any] | None) -> dict[str, Any]:
        return self._mutate_with_super("get_or_create_pr", repo_id, number, payload)

    def sync_pull_request(self, repo_id: str, pr_number: int, payload: dict[str, Any] | None) -> dict[str, Any]:
        return self._mutate_with_super("sync_pull_request", repo_id, pr_number, payload)

    async def create_analysis_job(self, pr_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        job = await super().create_analysis_job(pr_id, payload)
        self._save_state()
        return job

    async def run_analysis_job(self, job_id: str, files: list[dict[str, Any]]) -> None:
        await super().run_analysis_job(job_id, files)
        self._save_state()

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._mutate_with_super("cancel_job", job_id)

    def publish(
        self,
        pr_id: str,
        job_id: str,
        mode: str,
        dry_run: bool,
        provider_comments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._mutate_with_super("publish", pr_id, job_id, mode, dry_run, provider_comments)

    def upsert_feedback(self, comment_id: str, user_id: str, vote: str, reason: str | None) -> dict[str, Any]:
        return self._mutate_with_super("upsert_feedback", comment_id, user_id, vote, reason)

    def append_job_event(
        self,
        job_id: str,
        level: str,
        message: str,
        file_path: str | None = None,
        meta: dict[str, Any] | None = None,
        stage: str | None = None,
    ) -> None:
        super().append_job_event(job_id, level, message, file_path, meta, stage)
        self._save_state()
