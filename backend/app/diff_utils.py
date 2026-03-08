from __future__ import annotations

import re
from typing import Any

HUNK_REGEX = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$")
IMPORT_REGEXES = (
    re.compile(r"^\+\s*import\s+['\"]([^'\"]+)['\"]"),
    re.compile(r"^\+\s*import\s+.+?\s+from\s+['\"]([^'\"]+)['\"]"),
    re.compile(r"^\+\s*from\s+([A-Za-z0-9_\.]+)\s+import\s+"),
)
SYMBOL_REGEXES = (
    re.compile(r"^\+\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\+\s*(?:class|enum|typedef|extension)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\+\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\+\s*(?:const|final|var|let)\s+([A-Za-z_][A-Za-z0-9_]*)\s*="),
)

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


def extract_imports_from_patch(patch: str) -> list[str]:
    imports: list[str] = []
    seen: set[str] = set()
    for line in patch.split("\n"):
        for pattern in IMPORT_REGEXES:
            match = pattern.search(line)
            if not match:
                continue
            value = match.group(1).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            imports.append(value)
    return imports[:20]


def extract_changed_symbols_from_patch(patch: str) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for line in patch.split("\n"):
        for pattern in SYMBOL_REGEXES:
            match = pattern.search(line)
            if not match:
                continue
            value = match.group(1).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            symbols.append(value)
    return symbols[:20]


def extract_surrounding_code_from_patch(patch: str, *, limit: int = 12) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    current_new = 1
    for line in patch.split("\n"):
        match = HUNK_REGEX.match(line)
        if match:
            current_new = int(match.group(3))
            continue
        if line.startswith("-") and not line.startswith("---"):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            context.append({"lineNumber": current_new, "text": line[1:]})
            current_new += 1
            continue
        if line.startswith(" "):
            context.append({"lineNumber": current_new, "text": line[1:]})
            current_new += 1
            continue
    if len(context) <= limit:
        return context
    head = context[: limit // 2]
    tail = context[-(limit - len(head)) :]
    return head + tail


def detect_language(file_path: str) -> str:
    chunks = file_path.split(".")
    if len(chunks) < 2:
        return "PlainText"

    extension = chunks[-1].lower()
    return EXTENSION_LANGUAGE_MAP.get(extension, "PlainText")
