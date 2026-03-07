from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    port: int
    api_service_token: str | None
    github_webhook_secret: str | None
    serve_frontend: bool
    frontend_dist_path: Path | None


def parse_bool(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> AppConfig:
    raw_port = os.getenv("PORT", "4000").strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = 4000

    api_service_token = (os.getenv("API_SERVICE_TOKEN") or "").strip() or None
    github_webhook_secret = (os.getenv("GITHUB_WEBHOOK_SECRET") or "").strip() or None

    serve_frontend = parse_bool(os.getenv("SERVE_FRONTEND"))
    frontend_dist_path: Path | None = None
    if serve_frontend:
        configured = os.getenv("FRONTEND_DIST_PATH", "../frontend/dist")
        frontend_dist_path = (Path.cwd() / configured).resolve()

    return AppConfig(
        port=port,
        api_service_token=api_service_token,
        github_webhook_secret=github_webhook_secret,
        serve_frontend=serve_frontend,
        frontend_dist_path=frontend_dist_path,
    )
