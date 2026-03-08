from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "rag-ml" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rag_ml.config import load_config
from rag_ml.service import build_artifacts


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Build local RAG KB artifacts")
    parser.add_argument("--namespace", action="append", dest="namespaces", default=[])
    args = parser.parse_args()
    namespaces = set(args.namespaces) if args.namespaces else None
    manifest = await build_artifacts(load_config(), namespaces=namespaces)
    print(json.dumps(manifest.model_dump(), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(async_main())
