from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "rag-ml" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rag_ml.config import load_config
from rag_ml.language_mapper import to_slug
from rag_ml.service import _load_runtime  # noqa: SLF001


async def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect retrieval hits for a query")
    parser.add_argument("--language", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--category", default="bugs")
    args = parser.parse_args()

    config = load_config()
    runtime = _load_runtime(config)
    language_slug = to_slug(args.language) or args.language.lower()
    namespaces = [language_slug]
    query_text = f"language={language_slug}\ncategory={args.category}\ncode={args.query}"
    vector = np.asarray((await runtime.client.embed_texts([query_text]))[0], dtype=np.float32)
    hits = runtime.retriever.search(namespaces, query_text, vector, top_k=config.default_topk)
    print(json.dumps([hit.model_dump() for hit in hits], indent=2, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
