from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def parse_bool(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


RAG_SRC_ROOT = Path(__file__).resolve().parents[2] / "rag-ml" / "src"
if str(RAG_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(RAG_SRC_ROOT))

try:
    from rag_ml.service import analyze_request, runtime_status
except Exception as error:  # pragma: no cover - surfaced at runtime with actionable message
    analyze_request = None
    runtime_status = None
    IMPORT_ERROR = error
else:
    IMPORT_ERROR = None


async def analyze_with_rag(request: dict[str, Any]) -> dict[str, Any]:
    if not parse_bool(os.getenv("RAG_ENABLED"), default=True):
        return {"suggestions": [], "partialFailures": 0}

    if analyze_request is None:
        raise RuntimeError(
            "RAG runtime import failed. "
            f"Expected package under {RAG_SRC_ROOT}. Root cause: {IMPORT_ERROR}"
        )

    return await analyze_request(request)


async def get_rag_status() -> dict[str, Any]:
    if not parse_bool(os.getenv("RAG_ENABLED"), default=True):
        return {
            "enabled": False,
            "ready": True,
            "message": "RAG disabled by configuration",
        }

    if analyze_request is None or runtime_status is None:
        return {
            "enabled": True,
            "ready": False,
            "message": (
                "RAG runtime import failed. "
                f"Expected package under {RAG_SRC_ROOT}. Root cause: {IMPORT_ERROR}"
            ),
        }

    return await runtime_status()
