from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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


def build_missing_artifacts(build_root: Path, generation_model: str, inventory_cmd: list[str], build_cmd: list[str]) -> None:
    manifest_path = build_root / "build-manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = None
        if isinstance(manifest, dict) and manifest.get("embeddingModel"):
            print(f"[bootstrap] Reusing existing RAG artifacts from {build_root}", flush=True)
            return

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
    generation_model = (os.getenv("RAG_GENERATION_MODEL") or "qwen2.5-coder:7b").strip()
    repair_model = (os.getenv("RAG_REPAIR_MODEL") or generation_model).strip()
    embed_model = (os.getenv("RAG_EMBED_MODEL") or "nomic-embed-text").strip()
    build_root = Path(os.getenv("RAG_BUILD_DIR") or "/rag-ml/build")
    timeout_seconds = int(os.getenv("RAG_BOOTSTRAP_TIMEOUT_SECONDS", "900"))

    if provider == "ollama":
        wait_for_ollama(ollama_base_url, timeout_seconds)
        ensure_ollama_models(ollama_base_url, [embed_model, generation_model, repair_model])
    else:
        print(f"[bootstrap] Skipping Ollama bootstrap because RAG_MODEL_PROVIDER={provider}", flush=True)

    build_missing_artifacts(
        build_root,
        generation_model,
        [sys.executable, "../rag-ml/scripts/inventory.py"],
        [sys.executable, "../rag-ml/scripts/build_indexes.py"],
    )
    print("[bootstrap] RAG bootstrap completed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
