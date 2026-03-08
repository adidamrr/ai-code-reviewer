from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "rag-ml" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rag_ml.service import analyze_request

EXTENSION_LANGUAGE_MAP = {
    ".py": "Python",
    ".dart": "Dart",
    ".swift": "Swift",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
}


def detect_language(file_path: str) -> str:
    return EXTENSION_LANGUAGE_MAP.get(Path(file_path).suffix.lower(), "PlainText")


async def main() -> None:
    mocks_dir = REPO_ROOT / "frontend" / "src" / "debug" / "mocks"
    eval_dir = REPO_ROOT / "rag-ml" / "build" / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    for mock_path in sorted(mocks_dir.glob("*.json")):
        if mock_path.name == "manifest.json":
            continue
        payload = json.loads(mock_path.read_text(encoding="utf-8"))
        preset = payload["preset"]
        sync_payload = payload["syncPayload"]
        request = {
            "jobId": f"eval-{preset['id']}",
            "snapshotId": f"eval-{preset['id']}",
            "scope": preset.get("scope") or ["bugs"],
            "files": [
                {
                    "path": item["path"],
                    "language": detect_language(item["path"]),
                    "patch": item.get("patch") or "",
                    "hunks": [],
                    "lineMap": [],
                }
                for item in sync_payload.get("files", [])
            ],
            "limits": {"maxComments": preset.get("maxComments", 20), "maxPerFile": 3},
        }
        try:
            result = await analyze_request(request)
            error = None
        except Exception as exc:  # pragma: no cover - script-level operational fallback
            result = None
            error = str(exc)
        output = {
            "preset": preset,
            "source": payload["source"],
            "result": result,
            "error": error,
        }
        output_path = eval_dir / f"{mock_path.stem}.eval.json"
        output_path.write_text(json.dumps(output, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"saved {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
