from __future__ import annotations

import re
from typing import Any

HUNK_REGEX = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$")
IMPORT_REGEXES = (
    re.compile(r"^\+\s*import\s+['\"]([^'\"]+)['\"]"),
    re.compile(r"^\+\s*import\s+.+?\s+from\s+['\"]([^'\"]+)['\"]"),
    re.compile(r"^\+\s*from\s+([A-Za-z0-9_\.]+)\s+import\s+"),
)
PY_BLOCK_REGEXES = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)"),
)
GENERIC_BLOCK_REGEXES = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
)
CALL_SITE_DEFINITION_HINTS = (
    re.compile(r"^\s*(?:async\s+)?def\s+"),
    re.compile(r"^\s*class\s+"),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+"),
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


def infer_file_role(file_path: str) -> str:
    path = file_path.lower()
    if any(token in path for token in ("/docs/", "readme", ".md", ".rst", "changelog", "license")):
        return "docs"
    if any(token in path for token in ("/localization/", "/translations/", "_strings_", "/l10n/", ".arb", ".json", ".yaml", ".yml")):
        return "resource"
    if any(token in path for token in ("/generated/", ".g.dart", ".pb.dart", ".gen.py", "_generated.py")):
        return "generated"
    if any(token in path for token in ("/tests/", "test_", "_test.py", "_test.dart")):
        return "test"
    if any(token in path for token in ("/api/", "/routes/", "handler", "endpoint")):
        return "api"
    if any(token in path for token in ("/repositories/", "/repository/", "/dao/", "/queries/")):
        return "repository"
    if any(token in path for token in ("/services/", "/service/", "/use_cases/", "/usecases/")):
        return "logic"
    if any(token in path for token in ("/models/", "/schemas/", "/entities/")):
        return "model"
    return "logic"


def _block_patterns_for_path(file_path: str) -> tuple[re.Pattern[str], ...]:
    if file_path.lower().endswith(".py"):
        return PY_BLOCK_REGEXES
    return GENERIC_BLOCK_REGEXES


def _find_symbol_and_kind(file_path: str, lines: list[str]) -> tuple[str | None, str]:
    patterns = _block_patterns_for_path(file_path)
    for text in reversed(lines):
        for pattern in patterns:
            match = pattern.search(text)
            if not match:
                continue
            symbol = match.group(1)
            kind = "class" if text.strip().startswith("class ") else "function"
            return symbol, kind
    return None, "block"


def extract_changed_blocks_from_patch(patch: str, file_path: str, *, limit: int = 4) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current_header = ""
    current_new = 1
    current_lines: list[dict[str, Any]] = []

    def flush_block() -> None:
        if not current_lines:
            return
        visible_lines = [item["text"] for item in current_lines if item["type"] in {"ctx", "add"} and item["text"].strip()]
        before_lines = [item["text"] for item in current_lines if item["type"] in {"ctx", "del"} and item["text"].strip()]
        after_lines = [item["text"] for item in current_lines if item["type"] in {"ctx", "add"} and item["text"].strip()]
        line_numbers = [item["lineNumber"] for item in current_lines if item["lineNumber"] is not None]
        if not visible_lines or not line_numbers:
            return
        symbol, kind = _find_symbol_and_kind(file_path, visible_lines)
        block_index = len(blocks)
        blocks.append(
            {
                "blockId": f"{file_path}:{block_index}",
                "symbol": symbol,
                "kind": kind,
                "lineStart": min(line_numbers),
                "lineEnd": max(line_numbers),
                "snippet": "\n".join(visible_lines[:18]),
                "beforeSnippet": "\n".join(before_lines[:18]) or None,
                "afterSnippet": "\n".join(after_lines[:18]) or None,
                "header": current_header or None,
            }
        )

    for raw_line in patch.splitlines():
        match = HUNK_REGEX.match(raw_line)
        if match:
            flush_block()
            current_header = raw_line
            current_new = int(match.group(3))
            current_lines = []
            continue
        if raw_line.startswith("-") and not raw_line.startswith("---"):
            current_lines.append({"type": "del", "lineNumber": None, "text": raw_line[1:]})
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            current_lines.append({"type": "add", "lineNumber": current_new, "text": raw_line[1:]})
            current_new += 1
            continue
        if raw_line.startswith(" "):
            current_lines.append({"type": "ctx", "lineNumber": current_new, "text": raw_line[1:]})
            current_new += 1
            continue
    flush_block()
    return blocks[:limit]


def _is_definition_line(text: str) -> bool:
    return any(pattern.search(text) for pattern in CALL_SITE_DEFINITION_HINTS)


def build_related_call_sites(snapshot_files: list[dict[str, Any]], *, per_file_limit: int = 8) -> None:
    code_lines_by_file: dict[str, list[dict[str, Any]]] = {}
    for file in snapshot_files:
        code_lines_by_file[file["path"]] = [
            {"lineNumber": int(line["lineNumber"]), "text": str(line["text"])}
            for line in (file.get("surroundingCode") or [])
        ]

    for target in snapshot_files:
        symbols = [symbol for symbol in (target.get("changedSymbols") or []) if symbol]
        related: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int]] = set()
        for symbol in symbols:
            call_pattern = re.compile(rf"\b{re.escape(symbol)}\s*\(")
            for source in snapshot_files:
                for line in code_lines_by_file.get(source["path"], []):
                    if _is_definition_line(line["text"]):
                        continue
                    if not call_pattern.search(line["text"]):
                        continue
                    key = (symbol, source["path"], line["lineNumber"])
                    if key in seen:
                        continue
                    seen.add(key)
                    related.append(
                        {
                            "symbol": symbol,
                            "filePath": source["path"],
                            "lineStart": line["lineNumber"],
                            "lineEnd": line["lineNumber"],
                            "snippet": line["text"],
                            "relation": "changed-file-call-site",
                        }
                    )
                    if len(related) >= per_file_limit:
                        break
                if len(related) >= per_file_limit:
                    break
            if len(related) >= per_file_limit:
                break
        target["relatedCallSites"] = related
