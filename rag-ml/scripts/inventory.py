from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "rag-ml" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rag_ml.config import load_config
from rag_ml.kb_inventory import build_inventory, write_inventory


def main() -> None:
    config = load_config()
    output = write_inventory(config)
    inventory = build_inventory(config)
    print(f"Inventory written to {output}")
    print(json.dumps([item.model_dump() for item in inventory], indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
