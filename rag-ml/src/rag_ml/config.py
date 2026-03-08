from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RAG_ROOT = REPO_ROOT / "rag-ml"
KB_ROOT = RAG_ROOT / "kb"
BUILD_ROOT = RAG_ROOT / "build"
SUPPORTED_LANGUAGES = ("python", "dart", "swift", "cpp", "javascript")
PRIMARY_LANGUAGES = ("python", "dart", "swift")
EXPERIMENTAL_LANGUAGES = ("cpp", "javascript")


def parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_list(value: str | None, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value or not value.strip():
        return default
    items = [entry.strip() for entry in value.split(",") if entry.strip()]
    return tuple(items) if items else default


@dataclass(frozen=True)
class RagConfig:
    repo_root: Path
    rag_root: Path
    kb_root: Path
    build_root: Path
    ollama_base_url: str
    generation_model: str
    eval_generation_model: str
    embed_model: str
    supported_languages: tuple[str, ...]
    primary_languages: tuple[str, ...]
    experimental_languages: tuple[str, ...]
    enable_security: bool
    enable_performance: bool
    default_topk: int
    max_hunks_per_file: int
    max_hotspot_tasks: int
    embed_batch_size: int
    generation_max_tokens: int
    ollama_timeout_seconds: float
    repair_model: str | None = None


_CONFIG: RagConfig | None = None


def load_config() -> RagConfig:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    generation_model = os.getenv("RAG_GENERATION_MODEL", "qwen2.5-coder:7b")
    _CONFIG = RagConfig(
        repo_root=REPO_ROOT,
        rag_root=RAG_ROOT,
        kb_root=Path(os.getenv("RAG_KB_DIR", str(KB_ROOT))).resolve(),
        build_root=Path(os.getenv("RAG_BUILD_DIR", str(BUILD_ROOT))).resolve(),
        ollama_base_url=(os.getenv("RAG_OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/"),
        generation_model=generation_model,
        eval_generation_model=os.getenv("RAG_EVAL_GENERATION_MODEL", "qwen2.5-coder:14b"),
        embed_model=os.getenv("RAG_EMBED_MODEL", "nomic-embed-text"),
        supported_languages=parse_list(os.getenv("RAG_SUPPORTED_LANGUAGES"), default=SUPPORTED_LANGUAGES),
        primary_languages=PRIMARY_LANGUAGES,
        experimental_languages=EXPERIMENTAL_LANGUAGES,
        enable_security=parse_bool(os.getenv("RAG_ENABLE_SECURITY"), default=False),
        enable_performance=parse_bool(os.getenv("RAG_ENABLE_PERFORMANCE"), default=True),
        default_topk=max(1, int(os.getenv("RAG_DEFAULT_TOPK", "4"))),
        max_hunks_per_file=max(1, int(os.getenv("RAG_MAX_HUNKS_PER_FILE", "2"))),
        max_hotspot_tasks=max(1, int(os.getenv("RAG_MAX_HOTSPOT_TASKS", "8"))),
        embed_batch_size=max(1, int(os.getenv("RAG_EMBED_BATCH_SIZE", "64"))),
        generation_max_tokens=max(64, int(os.getenv("RAG_GENERATION_MAX_TOKENS", "160"))),
        ollama_timeout_seconds=float(os.getenv("RAG_OLLAMA_TIMEOUT_SECONDS", "120")),
        repair_model=(os.getenv("RAG_REPAIR_MODEL") or generation_model).strip() or generation_model,
    )
    return _CONFIG
