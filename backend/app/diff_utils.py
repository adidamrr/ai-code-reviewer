from __future__ import annotations

import re
from typing import Any

HUNK_REGEX = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$")

EXTENSION_LANGUAGE_MAP = {
    "ts": "TypeScript",
    "tsx": "TypeScript",
    "js": "JavaScript",
    "jsx": "JavaScript",
    "py": "Python",
    "go": "Go",
    "java": "Java",
    "cs": "C#",
    "rb": "Ruby",
    "php": "PHP",
    "rs": "Rust",
    "cpp": "C++",
    "c": "C",
    "h": "C/C++",
    "swift": "Swift",
    "kt": "Kotlin",
    "md": "Markdown",
    "json": "JSON",
    "yml": "YAML",
    "yaml": "YAML",
    "sql": "SQL",
    "dart": "Dart",
}


def count_patch_changes(patch: str) -> dict[str, int]:
    additions = 0
    deletions = 0

    for line in patch.split("\n"):
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1

    return {"additions": additions, "deletions": deletions}


def parse_unified_diff(patch: str) -> dict[str, list[dict[str, Any]]]:
    lines = patch.split("\n")
    hunks: list[dict[str, Any]] = []
    line_map: list[dict[str, Any]] = []

    current_old = 0
    current_new = 0

    for index, line in enumerate(lines):
        match = HUNK_REGEX.match(line)
        if match:
            old_start = int(match.group(1))
            old_lines = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_lines = int(match.group(4) or "1")
            hunks.append(
                {
                    "oldStart": old_start,
                    "oldLines": old_lines,
                    "newStart": new_start,
                    "newLines": new_lines,
                    "header": (match.group(5) or "").strip(),
                }
            )
            current_old = old_start
            current_new = new_start
            continue

        if line.startswith("+") and not line.startswith("+++"):
            line_map.append(
                {
                    "patchLine": index + 1,
                    "oldLine": None,
                    "newLine": current_new,
                    "type": "add",
                }
            )
            current_new += 1
            continue

        if line.startswith("-") and not line.startswith("---"):
            line_map.append(
                {
                    "patchLine": index + 1,
                    "oldLine": current_old,
                    "newLine": None,
                    "type": "del",
                }
            )
            current_old += 1
            continue

        if line.startswith(" "):
            line_map.append(
                {
                    "patchLine": index + 1,
                    "oldLine": current_old,
                    "newLine": current_new,
                    "type": "ctx",
                }
            )
            current_old += 1
            current_new += 1

    return {"hunks": hunks, "lineMap": line_map}


def detect_language(file_path: str) -> str:
    chunks = file_path.split(".")
    if len(chunks) < 2:
        return "PlainText"

    extension = chunks[-1].lower()
    return EXTENSION_LANGUAGE_MAP.get(extension, "PlainText")
