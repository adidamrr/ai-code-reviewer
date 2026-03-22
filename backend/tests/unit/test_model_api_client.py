from __future__ import annotations

import asyncio
import json

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
RAG_SRC = REPO_ROOT / "rag-ml" / "src"
if str(RAG_SRC) not in sys.path:
    sys.path.insert(0, str(RAG_SRC))

from rag_ml.config import load_config
from rag_ml.model_client import ApiModelClient, ModelClientError, YandexModelClient, create_model_client
from rag_ml.schemas import OllamaMessage


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _RecordingAsyncClient:
    def __init__(self, responses=None, *args, **kwargs):
        self.calls: list[dict] = []
        self.responses = list(responses or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if self.responses:
            return self.responses.pop(0)
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"ok": true}'
                        }
                    }
                ]
            }
        )



class ModelApiClientTests(unittest.TestCase):
    def test_create_model_client_returns_api_client_for_api_provider(self) -> None:
        env = {
            "RAG_MODEL_PROVIDER": "api",
            "RAG_API_BASE_URL": "https://example.test/v1",
            "RAG_API_KEY": "secret",
            "RAG_GENERATION_MODEL": "gpt-4.1-mini",
            "RAG_EMBED_MODEL": "text-embedding-3-small",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("rag_ml.config._CONFIG", None):
                config = load_config()

        client = create_model_client(config)
        self.assertIsInstance(client, ApiModelClient)
        self.assertEqual(config.model_provider, "api")
        self.assertEqual(config.model_api_base_url, "https://example.test/v1")
        self.assertEqual(config.model_api_key, "secret")

    def test_api_client_requires_base_url_and_key(self) -> None:
        with patch.dict(os.environ, {"RAG_MODEL_PROVIDER": "api"}, clear=True):
            with patch("rag_ml.config._CONFIG", None):
                config = load_config()

        client = create_model_client(config)
        with self.assertRaises(ModelClientError):
            asyncio.run(client.ensure_models_available([config.generation_model]))


    def test_api_client_chat_payload_omits_ollama_specific_extra_body(self) -> None:
        env = {
            "RAG_MODEL_PROVIDER": "api",
            "RAG_API_BASE_URL": "https://example.test/v1",
            "RAG_API_KEY": "secret",
            "RAG_GENERATION_MODEL": "gpt-4.1-mini",
            "RAG_EMBED_MODEL": "text-embedding-3-small",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("rag_ml.config._CONFIG", None):
                config = load_config()

        client = create_model_client(config)
        transport = _RecordingAsyncClient()
        with patch("httpx.AsyncClient", return_value=transport):
            payload = asyncio.run(
                client.chat_structured(
                    [OllamaMessage(role="user", content="hello")],
                    {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                    num_ctx=2048,
                )
            )

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(len(transport.calls), 1)
        request_json = transport.calls[0]["json"]
        self.assertNotIn("extra_body", request_json)
        self.assertEqual(request_json["max_tokens"], config.generation_max_tokens)

    def test_create_model_client_returns_yandex_client_for_yandex_provider(self) -> None:
        env = {
            "RAG_MODEL_PROVIDER": "yandex",
            "RAG_YANDEX_BASE_URL": "https://llm.api.cloud.yandex.net/v1",
            "RAG_YANDEX_FOLDER_ID": "folder-123",
            "RAG_YANDEX_API_KEY": "secret",
            "RAG_GENERATION_MODEL": "gpt://folder-123/yandexgpt/latest",
            "RAG_EMBED_MODEL": "emb://folder-123/text-search-doc/latest",
            "RAG_QUERY_EMBED_MODEL": "emb://folder-123/text-search-query/latest",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("rag_ml.config._CONFIG", None):
                config = load_config()

        client = create_model_client(config)
        self.assertIsInstance(client, YandexModelClient)
        self.assertEqual(config.model_provider, "yandex")
        self.assertEqual(config.yandex_folder_id, "folder-123")
        self.assertEqual(config.query_embed_model, "emb://folder-123/text-search-query/latest")

    def test_yandex_client_requires_folder_and_key(self) -> None:
        env = {
            "RAG_MODEL_PROVIDER": "yandex",
            "RAG_YANDEX_BASE_URL": "https://llm.api.cloud.yandex.net/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("rag_ml.config._CONFIG", None):
                config = load_config()

        client = create_model_client(config)
        with self.assertRaises(ModelClientError):
            asyncio.run(client.ensure_models_available([config.generation_model]))

    def test_yandex_chat_payload_sets_project_and_logging_headers(self) -> None:
        env = {
            "RAG_MODEL_PROVIDER": "yandex",
            "RAG_YANDEX_BASE_URL": "https://llm.api.cloud.yandex.net/v1",
            "RAG_YANDEX_FOLDER_ID": "folder-123",
            "RAG_YANDEX_API_KEY": "secret",
            "RAG_YANDEX_DISABLE_DATA_LOGGING": "true",
            "RAG_GENERATION_MODEL": "gpt://folder-123/yandexgpt/latest",
            "RAG_EMBED_MODEL": "emb://folder-123/text-search-doc/latest",
            "RAG_QUERY_EMBED_MODEL": "emb://folder-123/text-search-query/latest",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("rag_ml.config._CONFIG", None):
                config = load_config()

        client = create_model_client(config)
        transport = _RecordingAsyncClient()
        with patch("httpx.AsyncClient", return_value=transport):
            payload = asyncio.run(
                client.chat_structured(
                    [OllamaMessage(role="user", content="hello")],
                    {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                )
            )

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual(call["url"], "https://llm.api.cloud.yandex.net/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(call["headers"]["OpenAI-Project"], "folder-123")
        self.assertEqual(call["headers"]["x-data-logging-enabled"], "false")

    def test_yandex_embeddings_use_single_text_requests_and_model_override(self) -> None:
        env = {
            "RAG_MODEL_PROVIDER": "yandex",
            "RAG_YANDEX_BASE_URL": "https://llm.api.cloud.yandex.net/v1",
            "RAG_YANDEX_FOLDER_ID": "folder-123",
            "RAG_YANDEX_API_KEY": "secret",
            "RAG_GENERATION_MODEL": "gpt://folder-123/yandexgpt/latest",
            "RAG_EMBED_MODEL": "emb://folder-123/text-search-doc/latest",
            "RAG_QUERY_EMBED_MODEL": "emb://folder-123/text-search-query/latest",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("rag_ml.config._CONFIG", None):
                config = load_config()

        client = create_model_client(config)
        transport = _RecordingAsyncClient(
            responses=[
                _FakeResponse({"embedding": [0.1, 0.2]}),
                _FakeResponse({"embedding": [0.3, 0.4]}),
            ]
        )
        with patch("httpx.AsyncClient", return_value=transport):
            vectors = asyncio.run(
                client.embed_texts(
                    ["doc one", "doc two"],
                    model="emb://folder-123/text-search-query/latest",
                )
            )

        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
        self.assertEqual(len(transport.calls), 2)
        first_call = transport.calls[0]
        second_call = transport.calls[1]
        self.assertEqual(first_call["url"], "https://ai.api.cloud.yandex.net/foundationModels/v1/textEmbedding")
        self.assertEqual(first_call["headers"]["Authorization"], "Api-Key secret")
        self.assertEqual(first_call["json"]["text"], "doc one")
        self.assertEqual(second_call["json"]["text"], "doc two")
        self.assertEqual(
            first_call["json"]["modelUri"],
            "emb://folder-123/text-search-query/latest",
        )



if __name__ == "__main__":
    unittest.main()
