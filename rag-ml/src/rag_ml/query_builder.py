from __future__ import annotations

import re

from .schemas import HunkTask

IDENTIFIER_REGEX = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STRING_LITERAL = re.compile(r"(['\"]).*?\1")
SNAKE_OR_MIXED_IDENTIFIER = re.compile(r"\b[A-Za-z]+_[A-Za-z0-9_]+\b")
UPPER_START_IDENTIFIER = re.compile(r"\b[A-Z][A-Za-z0-9_]*\b")
TYPE_DECLARATION = re.compile(r"\b(?:class|enum|typedef|extension)\s+([A-Za-z_][A-Za-z0-9_]*)")

CATEGORY_FOCUS = {
    "style": "naming consistency conventions readability lint rules",
    "bugs": "error handling nullability async state exceptions edge cases",
    "performance": "repeated work loops allocations blocking copies hot path",
    "security": "validation secrets injection auth unsafe apis deserialization",
}


def _normalize_line(line: str) -> str:
    line = STRING_LITERAL.sub("<str>", line)
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def _extract_symbols(lines: list[str], file_path: str) -> list[str]:
    symbols = set(IDENTIFIER_REGEX.findall(file_path))
    for line in lines:
        symbols.update(IDENTIFIER_REGEX.findall(line))
    return sorted(symbols)[:30]


def _style_focus_hints(lines: list[str]) -> str:
    joined = "\n".join(lines)
    hints: list[str] = []
    if SNAKE_OR_MIXED_IDENTIFIER.search(joined):
        hints.append("lowerCamelCase non-constant identifier names")
    if UPPER_START_IDENTIFIER.search(joined):
        hints.append("variables should not use UpperCamelCase")
    declared_type_names = TYPE_DECLARATION.findall(joined)
    if any(name and not name[:1].isupper() for name in declared_type_names):
        hints.append("types should use UpperCamelCase")
    return " ".join(hints)


def build_query(task: HunkTask, category: str) -> str:
    normalized_lines = [_normalize_line(line) for line in task.addedLines]
    compact_code = "\n".join(line for line in normalized_lines if line)
    symbols = ", ".join(_extract_symbols(normalized_lines, task.filePath))
    focus = CATEGORY_FOCUS[category]
    if category == "style":
        extra_focus = _style_focus_hints(normalized_lines)
        if extra_focus:
            focus = f"{focus} {extra_focus}"
    return (
        f"language={task.languageSlug}\n"
        f"category={category}\n"
        f"file={task.filePath}\n"
        f"symbols={symbols}\n"
        f"code={compact_code}\n"
        f"focus={focus}"
    )
