from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .errors import HttpError

SESSION_TTL_SECONDS = 60 * 60


class GithubSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, str]] = {}

    def create(self, token: str, github_login: str, provider: str = "github") -> dict[str, str]:
        now = datetime.now(timezone.utc)
        prefix = "gls" if provider == "gitlab" else "ghs"
        session = {
            "id": f"{prefix}_{uuid4()}",
            "token": token,
            "githubLogin": github_login,
            "provider": provider,
            "createdAt": now.isoformat().replace("+00:00", "Z"),
            "expiresAt": (now + timedelta(seconds=SESSION_TTL_SECONDS)).isoformat().replace("+00:00", "Z"),
        }
        self._sessions[session["id"]] = session
        self.cleanup_expired()
        return session

    def get(self, session_id: str) -> dict[str, str]:
        session = self._sessions.get(session_id)
        if not session:
            raise HttpError(404, "github_session_not_found", f"GitHub session not found: {session_id}")

        expires_at = datetime.fromisoformat(session["expiresAt"].replace("Z", "+00:00"))
        if expires_at <= datetime.now(timezone.utc):
            self._sessions.pop(session_id, None)
            raise HttpError(401, "github_session_expired", f"GitHub session expired: {session_id}")

        return session

    def get_for_provider(self, session_id: str, provider: str) -> dict[str, str]:
        session = self.get(session_id)
        if session.get("provider") != provider:
            raise HttpError(404, "session_not_found", f"{provider} session not found: {session_id}")
        return session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        for session_id in list(self._sessions.keys()):
            expires_at = datetime.fromisoformat(self._sessions[session_id]["expiresAt"].replace("Z", "+00:00"))
            if expires_at <= now:
                self._sessions.pop(session_id, None)
