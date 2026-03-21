from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .config import RagConfig
from .schemas import OllamaMessage


class ModelClientError(RuntimeError):
    pass


class StructuredOutputError(ModelClientError):
    def __init__(self, message: str, raw_content: str) -> None:
        super().__init__(message)
        self.raw_content = raw_content


class ModelClientProtocol(Protocol):
    repair_model: str | None

    async def ensure_models_available(self, models: list[str]) -> None: ...

    async def embed_texts(self, texts: list[str], *, model: str | None = None) -> list[list[float]]: ...

    async def chat_structured(
        self,
        messages: list[OllamaMessage],
        schema: dict[str, Any],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        num_ctx: int = 4096,
    ) -> dict[str, Any]: ...

    async def chat_text(
        self,
        messages: list[OllamaMessage],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        num_ctx: int = 4096,
        num_predict: int | None = None,
    ) -> str: ...


class OllamaClient(ModelClientProtocol):
    def __init__(self, config: RagConfig) -> None:
        self.base_url = config.ollama_base_url
        self.timeout = config.ollama_timeout_seconds
        self.generation_model = config.generation_model
        self.embed_model = config.embed_model
        self.embed_batch_size = config.embed_batch_size
        self.generation_max_tokens = config.generation_max_tokens
        self.repair_model = config.repair_model or config.generation_model
        self._model_cache: set[str] | None = None

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/tags")
        if response.status_code >= 400:
            raise ModelClientError(f"Ollama tags request failed: {response.status_code} {response.text}")
        data = response.json()
        models = [item.get("name", "") for item in data.get("models", []) if item.get("name")]
        self._model_cache = set(models)
        return models

    async def ensure_models_available(self, models: list[str]) -> None:
        available = self._model_cache or set(await self.list_models())
        missing = [model for model in models if not self._model_present(model, available)]
        if missing:
            raise ModelClientError(
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
            raise ModelClientError(f"Ollama embed request failed: {response.status_code} {response.text}")
        data = response.json()
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            raise ModelClientError("Ollama embed response does not contain embeddings")
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
            raise ModelClientError(f"Ollama chat request failed: {response.status_code} {response.text}")
        data = response.json()
        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelClientError("Ollama chat response does not contain structured content")
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            raise StructuredOutputError(
                f"Ollama returned invalid JSON: {error}",
                content,
            ) from error

    async def chat_text(
        self,
        messages: list[OllamaMessage],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        num_ctx: int = 4096,
        num_predict: int | None = None,
    ) -> str:
        payload = {
            "model": model or self.generation_model,
            "messages": [message.model_dump() for message in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
                "num_predict": num_predict or self.generation_max_tokens,
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
        if response.status_code >= 400:
            raise ModelClientError(f"Ollama chat request failed: {response.status_code} {response.text}")
        data = response.json()
        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelClientError("Ollama chat response does not contain text content")
        return content


@dataclass(frozen=True)
class _ApiResponseContent:
    text: str


class ApiModelClient(ModelClientProtocol):
    def __init__(self, config: RagConfig) -> None:
        self.base_url = config.model_api_base_url.rstrip("/") if config.model_api_base_url else ""
        self.api_key = config.model_api_key
        self.timeout = config.ollama_timeout_seconds
        self.generation_model = config.generation_model
        self.embed_model = config.embed_model
        self.embed_batch_size = config.embed_batch_size
        self.generation_max_tokens = config.generation_max_tokens
        self.repair_model = config.repair_model or config.generation_model

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _require_config(self) -> None:
        if not self.base_url:
            raise ModelClientError("RAG_API_BASE_URL is required when RAG_MODEL_PROVIDER=api")
        if not self.api_key:
            raise ModelClientError("RAG_API_KEY is required when RAG_MODEL_PROVIDER=api")

    async def ensure_models_available(self, models: list[str]) -> None:
        self._require_config()
        if not models:
            return None
        return None

    async def embed_texts(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        self._require_config()
        if not texts:
            return []
        payload = {
            "model": model or self.embed_model,
            "input": texts,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json=payload,
            )
        if response.status_code >= 400:
            raise ModelClientError(f"API embeddings request failed: {response.status_code} {response.text}")
        data = response.json()
        items = data.get("data")
        if not isinstance(items, list):
            raise ModelClientError("API embeddings response does not contain data list")
        embeddings = [item.get("embedding") for item in items if isinstance(item, dict)]
        if len(embeddings) != len(texts) or any(not isinstance(item, list) for item in embeddings):
            raise ModelClientError("API embeddings response does not contain valid embedding vectors")
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
        response = await self._chat_completion(
            messages,
            model=model,
            temperature=temperature,
            num_ctx=num_ctx,
            num_predict=self.generation_max_tokens,
            schema=schema,
        )
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as error:
            raise StructuredOutputError(f"API model returned invalid JSON: {error}", response.text) from error

    async def chat_text(
        self,
        messages: list[OllamaMessage],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        num_ctx: int = 4096,
        num_predict: int | None = None,
    ) -> str:
        response = await self._chat_completion(
            messages,
            model=model,
            temperature=temperature,
            num_ctx=num_ctx,
            num_predict=num_predict or self.generation_max_tokens,
            schema=None,
        )
        return response.text

    async def _chat_completion(
        self,
        messages: list[OllamaMessage],
        *,
        model: str | None,
        temperature: float,
        num_ctx: int,
        num_predict: int,
        schema: dict[str, Any] | None,
    ) -> _ApiResponseContent:
        self._require_config()
        payload: dict[str, Any] = {
            "model": model or self.generation_model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "max_tokens": num_predict,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "rag_structured_output",
                    "schema": schema,
                },
            }
        extra_body = {
            "num_ctx": num_ctx,
        }
        payload["extra_body"] = extra_body
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
        if response.status_code >= 400:
            raise ModelClientError(f"API chat request failed: {response.status_code} {response.text}")
        data = response.json()
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelClientError("API chat response does not contain choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ModelClientError("API chat response does not contain a message payload")
        content = self._extract_message_content(message)
        if not content.strip():
            raise ModelClientError("API chat response does not contain text content")
        return _ApiResponseContent(text=content)

    @staticmethod
    def _extract_message_content(message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if isinstance(item.get("text"), str):
                        parts.append(item["text"])
                    elif item.get("type") == "output_text" and isinstance(item.get("text"), str):
                        parts.append(item["text"])
            return "\n".join(part for part in parts if part)
        refusal = message.get("refusal")
        if isinstance(refusal, str) and refusal.strip():
            raise ModelClientError(f"API model refused the request: {refusal}")
        return ""


def create_model_client(config: RagConfig) -> ModelClientProtocol:
    provider = config.model_provider.strip().lower()
    if provider == "ollama":
        return OllamaClient(config)
    if provider == "api":
        return ApiModelClient(config)
    raise ModelClientError(f"Unsupported RAG_MODEL_PROVIDER: {config.model_provider}")
