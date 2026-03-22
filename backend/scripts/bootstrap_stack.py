from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen


def parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def get_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    with urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def wait_for_ollama(base_url: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_error: str | None = None
    while time.time() < deadline:
        try:
            get_json(f"{base_url}/api/tags")
            print(f"[bootstrap] Ollama is ready at {base_url}", flush=True)
            return
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as error:
            last_error = str(error)
            time.sleep(2)
    raise RuntimeError(f"Timed out waiting for Ollama at {base_url}. Last error: {last_error}")


def ensure_ollama_models(base_url: str, models: list[str]) -> None:
    if not models:
        return
    payloads = []
    for model in models:
        clean = (model or "").strip()
        if clean and clean not in payloads:
            payloads.append(clean)

    tags = get_json(f"{base_url}/api/tags")
    available = {
        item.get("name", "")
        for item in tags.get("models", [])
        if isinstance(item, dict) and item.get("name")
    }
    for model in payloads:
        if model in available or (":" not in model and f"{model}:latest" in available):
            print(f"[bootstrap] Ollama model already available: {model}", flush=True)
            continue
        print(f"[bootstrap] Pulling Ollama model: {model}", flush=True)
        post_json(f"{base_url}/api/pull", {"name": model, "stream": False})


def validate_api_mode(base_url: str | None, api_key: str | None, generation_model: str, embed_model: str, dense_enabled: bool) -> None:

    missing: list[str] = []
    if not (base_url or '').strip():
        missing.append('RAG_API_BASE_URL')
    if not (api_key or '').strip():
        missing.append('RAG_API_KEY')
    if missing:
        raise RuntimeError(
            'API bootstrap is missing required configuration: ' + ', '.join(missing)
        )
    masked_key = (api_key or '')[:6] + '...' if api_key else '<missing>'
    print(
        f"[bootstrap] API mode enabled: base_url={base_url} generation_model={generation_model} embed_model={embed_model} dense_enabled={dense_enabled} api_key={masked_key}",

        flush=True,
    )


def validate_yandex_mode(
    base_url: str | None,
    folder_id: str | None,
    api_key: str | None,
    generation_model: str,
    embed_model: str,
    query_embed_model: str,
    dense_enabled: bool,
) -> None:
    missing: list[str] = []
    if not (base_url or "").strip():
        missing.append("RAG_YANDEX_BASE_URL")
    if not (folder_id or "").strip():
        missing.append("RAG_YANDEX_FOLDER_ID")
    if not (api_key or "").strip():
        missing.append("RAG_YANDEX_API_KEY")
    if not (generation_model or "").strip():
        missing.append("RAG_GENERATION_MODEL")
    if dense_enabled and not (embed_model or "").strip():
        missing.append("RAG_EMBED_MODEL")
    if dense_enabled and not (query_embed_model or "").strip():
        missing.append("RAG_QUERY_EMBED_MODEL")
    if missing:
        raise RuntimeError(
            "Yandex bootstrap is missing required configuration: " + ", ".join(missing)
        )
    masked_key = (api_key or "")[:6] + "..." if api_key else "<missing>"
    print(
        "[bootstrap] Yandex mode enabled: "
        f"base_url={base_url} folder_id={folder_id} generation_model={generation_model} "
        f"embed_model={embed_model} query_embed_model={query_embed_model} dense_enabled={dense_enabled} api_key={masked_key}",
        flush=True,
    )


def build_missing_artifacts(
    build_root: Path,
    generation_model: str,
    embed_model: str,
    query_embed_model: str,
    dense_enabled: bool,
    inventory_cmd: list[str],
    build_cmd: list[str],
) -> None:

    manifest_path = build_root / "build-manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = None
        if isinstance(manifest, dict) and manifest.get("embeddingModel"):
            manifest_dense_enabled = manifest.get("denseRetrievalEnabled", True)
            manifest_embed_model = manifest.get("embeddingModel")
            manifest_query_embed_model = manifest.get("queryEmbeddingModel") or manifest_embed_model
            if (
                manifest_dense_enabled == dense_enabled
                and manifest_embed_model == embed_model
                and manifest_query_embed_model == query_embed_model
            ):
                print(f"[bootstrap] Reusing existing RAG artifacts from {build_root}", flush=True)
                return
            print(
                "[bootstrap] Rebuilding RAG artifacts because embedding configuration changed: "
                f"manifest_dense={manifest_dense_enabled} env_dense={dense_enabled} "
                f"manifest_embed={manifest_embed_model} env_embed={embed_model} "
                f"manifest_query_embed={manifest_query_embed_model} env_query_embed={query_embed_model}",
                flush=True,
            )


    print("[bootstrap] Building RAG inventory", flush=True)
    subprocess.run(inventory_cmd, check=True)
    print(f"[bootstrap] Building RAG indexes for model pipeline ({generation_model})", flush=True)
    subprocess.run(build_cmd, check=True)


def main() -> int:
    if parse_bool(os.getenv("RAG_SKIP_BOOTSTRAP"), default=False):
        print("[bootstrap] RAG bootstrap skipped by configuration", flush=True)
        return 0

    provider = (os.getenv("RAG_MODEL_PROVIDER") or "ollama").strip().lower()
    ollama_base_url = (os.getenv("RAG_OLLAMA_BASE_URL") or "http://ollama:11434").rstrip("/")
    yandex_folder_id = (os.getenv("RAG_YANDEX_FOLDER_ID") or "").strip()
    default_yandex_generation_model = (
        f"gpt://{yandex_folder_id}/yandexgpt/latest" if yandex_folder_id else "gpt://folder-id/yandexgpt/latest"
    )
    default_yandex_doc_embed_model = (
        f"emb://{yandex_folder_id}/text-search-doc/latest"
        if yandex_folder_id
        else "emb://folder-id/text-search-doc/latest"
    )
    default_yandex_query_embed_model = (
        f"emb://{yandex_folder_id}/text-search-query/latest"
        if yandex_folder_id
        else "emb://folder-id/text-search-query/latest"
    )

    generation_model = (os.getenv("RAG_GENERATION_MODEL") or default_yandex_generation_model).strip()
    repair_model = (os.getenv("RAG_REPAIR_MODEL") or generation_model).strip()
    embed_model = (os.getenv("RAG_EMBED_MODEL") or default_yandex_doc_embed_model).strip()
    query_embed_model = (os.getenv("RAG_QUERY_EMBED_MODEL") or default_yandex_query_embed_model).strip()
    api_base_url = (os.getenv("RAG_API_BASE_URL") or "").strip()
    api_key = (os.getenv("RAG_API_KEY") or "").strip()
    yandex_base_url = (os.getenv("RAG_YANDEX_BASE_URL") or "https://llm.api.cloud.yandex.net/v1").strip()
    yandex_api_key = (os.getenv("RAG_YANDEX_API_KEY") or "").strip()
    build_root = Path(os.getenv("RAG_BUILD_DIR") or "/rag-ml/build")
    dense_enabled = parse_bool(os.getenv("RAG_ENABLE_DENSE"), default=True)

    timeout_seconds = int(os.getenv("RAG_BOOTSTRAP_TIMEOUT_SECONDS", "900"))

    print(f"[bootstrap] Starting bootstrap with provider={provider}", flush=True)

    if provider == "ollama":
        wait_for_ollama(ollama_base_url, timeout_seconds)
        required_models = [generation_model, repair_model]
        if dense_enabled:
            required_models.insert(0, embed_model)
        ensure_ollama_models(ollama_base_url, required_models)
    elif provider == "yandex":
        validate_yandex_mode(
            yandex_base_url,
            yandex_folder_id,
            yandex_api_key,
            generation_model,
            embed_model,
            query_embed_model,
            dense_enabled,
        )
    else:
        validate_api_mode(api_base_url, api_key, generation_model, embed_model, dense_enabled)

        print(f"[bootstrap] Skipping Ollama bootstrap because RAG_MODEL_PROVIDER={provider}", flush=True)

    build_missing_artifacts(
        build_root,
        generation_model,
        embed_model,
        query_embed_model,
        dense_enabled,

        [sys.executable, "../rag-ml/scripts/inventory.py"],
        [sys.executable, "../rag-ml/scripts/build_indexes.py"],
    )
    print("[bootstrap] RAG bootstrap completed", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"[bootstrap] Fatal error: {error}", flush=True)
        traceback.print_exc()
        raise
