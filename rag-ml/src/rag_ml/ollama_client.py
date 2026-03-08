from __future__ import annotations

import json
from typing import Any

import httpx

from .config import RagConfig
from .schemas import OllamaMessage


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, config: RagConfig) -> None:
        self.base_url = config.ollama_base_url
        self.timeout = config.ollama_timeout_seconds
        self.generation_model = config.generation_model
        self.embed_model = config.embed_model
        self.embed_batch_size = config.embed_batch_size
        self.generation_max_tokens = config.generation_max_tokens
        self._model_cache: set[str] | None = None

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/tags")
        if response.status_code >= 400:
            raise OllamaError(f"Ollama tags request failed: {response.status_code} {response.text}")
        data = response.json()
        models = [item.get("name", "") for item in data.get("models", []) if item.get("name")]
        self._model_cache = set(models)
        return models

    async def ensure_models_available(self, models: list[str]) -> None:
        available = self._model_cache or set(await self.list_models())
        missing = [model for model in models if not self._model_present(model, available)]
        if missing:
            raise OllamaError(
                "Missing Ollama models: "
                + ", ".join(missing)
                + ". Install them with `ollama pull ...` before running RAG."
            )

    @staticmethod
    def _model_present(model: str, available: set[str]) -> bool:
        return model in available or (":" not in model and f"{model}:latest" in available)

    async def embed_texts(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": model or self.embed_model,
            "input": texts,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/embed", json=payload)
        if response.status_code >= 400:
            raise OllamaError(f"Ollama embed request failed: {response.status_code} {response.text}")
        data = response.json()
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            raise OllamaError("Ollama embed response does not contain embeddings")
        return embeddings

    async def chat_structured(
        self,
        messages: list[OllamaMessage],
        schema: dict[str, Any],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        num_ctx: int = 4096,
    ) -> dict[str, Any]:
        payload = {
            "model": model or self.generation_model,
            "messages": [message.model_dump() for message in messages],
            "stream": False,
            "format": schema,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
                "num_predict": self.generation_max_tokens,
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
        if response.status_code >= 400:
            raise OllamaError(f"Ollama chat request failed: {response.status_code} {response.text}")
        data = response.json()
        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaError("Ollama chat response does not contain structured content")
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            raise OllamaError(f"Ollama returned invalid JSON: {error}") from error
