from __future__ import annotations

import re

from .language_mapper import to_slug
from .schemas import HunkTask, RagFile

HUNK_HEADER = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@\s*(.*)$")
SECURITY_HINTS = {
    "auth",
    "token",
    "secret",
    "password",
    "key",
    "sql",
    "query",
    "http",
    "api",
    "login",
}


def _split_patch_into_hunks(patch: str) -> list[tuple[str, str]]:
    lines = patch.splitlines()
    hunks: list[tuple[str, list[str]]] = []
    current_header = ""
    current_lines: list[str] = []
    for line in lines:
        match = HUNK_HEADER.match(line)
        if match:
            if current_lines:
                hunks.append((current_header, current_lines))
            current_header = line
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        hunks.append((current_header, current_lines))
    return [(header, "\n".join(chunk_lines)) for header, chunk_lines in hunks if chunk_lines]


def _extract_added_lines(hunk_patch: str) -> tuple[list[str], list[int]]:
    added_lines: list[str] = []
    changed_new_lines: list[int] = []
    current_new = 1
    for line in hunk_patch.splitlines():
        match = HUNK_HEADER.match(line)
        if match:
            current_new = int(match.group(3))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])
            changed_new_lines.append(current_new)
            current_new += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            current_new += 1
    return added_lines, changed_new_lines


def _score_hunk(file_path: str, header: str, added_lines: list[str]) -> float:
    joined = " ".join(added_lines).lower()
    tokens = set(re.findall(r"[a-z_][a-z0-9_]*", joined))
    path_tokens = set(re.findall(r"[a-z_][a-z0-9_]*", file_path.lower()))
    score = float(len(added_lines))
    score += 3.0 * len(tokens.intersection(SECURITY_HINTS))
    score += 2.0 * len(path_tokens.intersection(SECURITY_HINTS))
    if "async" in joined or "await" in joined:
        score += 2.0
    if "for (" in joined or "while (" in joined or "for " in joined:
        score += 1.5
    if header:
        score += 0.5
    return score


def select_hunks(file: RagFile, max_hunks: int) -> list[HunkTask]:
    language_slug = to_slug(file.language)
    if not language_slug or not file.patch.strip():
        return []

    raw_hunks = _split_patch_into_hunks(file.patch)
    if not raw_hunks:
        raw_hunks = [("", file.patch)]

    tasks: list[HunkTask] = []
    for hunk_index, (header, hunk_patch) in enumerate(raw_hunks):
        added_lines, changed_new_lines = _extract_added_lines(hunk_patch)
        if not added_lines:
            continue
        first_changed_line = changed_new_lines[0] if changed_new_lines else 1
        tasks.append(
            HunkTask(
                taskId=f"{file.path}:{hunk_index}",
                filePath=file.path,
                language=file.language,
                languageSlug=language_slug,
                patch=file.patch,
                hunkIndex=hunk_index,
                hunkHeader=header,
                hunkPatch=hunk_patch,
                addedLines=added_lines,
                changedNewLines=changed_new_lines,
                firstChangedLine=first_changed_line,
                priority=_score_hunk(file.path, header, added_lines),
                imports=file.imports,
                changedSymbols=file.changedSymbols,
                surroundingCode=file.surroundingCode,
            )
        )

    tasks.sort(key=lambda item: item.priority, reverse=True)
    return tasks[:max_hunks]
