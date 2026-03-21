from __future__ import annotations

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
from rag_ml.model_client import ApiModelClient, ModelClientError, create_model_client


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
            import asyncio

            asyncio.run(client.ensure_models_available([config.generation_model]))


if __name__ == "__main__":
    unittest.main()
