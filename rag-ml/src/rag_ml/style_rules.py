from __future__ import annotations

import re

from .evidence_models import code_ref, doc_ref
from .schemas import CandidateFinding, HunkTask, RetrievalHit

DART_TYPE_DECLARATION = re.compile(r"\b(class|enum|typedef|extension)\s+([A-Za-z_][A-Za-z0-9_]*)")
DART_IDENTIFIER_DECLARATION = re.compile(
    r"\b(?:final|var|late|int|double|String|bool|num|dynamic|VoidCallback)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
PY_CLASS_DECLARATION = re.compile(r"^\+?\s*class\s+([A-Za-z_][A-Za-z0-9_]*)")
PY_FUNCTION_DECLARATION = re.compile(r"^\+?\s*def\s+([A-Za-z_][A-Za-z0-9_]*)")


def _line_for_match(task: HunkTask, index: int) -> int:
    if 0 <= index < len(task.changedNewLines):
        return task.changedNewLines[index]
    return task.firstChangedLine


def _pick_doc_refs(hits: list[RetrievalHit], keywords: tuple[str, ...]) -> list[str]:
    preferred = [
        doc_ref(hit.chunkId)
        for hit in hits
        if any(keyword.lower() in hit.text.lower() for keyword in keywords)
    ]
    if preferred:
        return preferred[:2]
    return [doc_ref(hit.chunkId) for hit in hits[:2]]


def _camel_case(value: str) -> str:
    if value.startswith("_"):
        value = value[1:]
    return value


def rule_based_style_candidates(task: HunkTask, hits: list[RetrievalHit]) -> list[CandidateFinding]:
    candidates: list[CandidateFinding] = []

    for index, line in enumerate(task.addedLines):
        line_no = _line_for_match(task, index)

        if task.languageSlug == "dart":
            type_match = DART_TYPE_DECLARATION.search(line)
            if type_match:
                type_name = type_match.group(2)
                visible_name = _camel_case(type_name)
                if visible_name and not visible_name[:1].isupper():
                    candidates.append(
                        CandidateFinding(
                            filePath=task.filePath,
                            lineStart=line_no,
                            lineEnd=line_no,
                            severity="low",
                            category="style",
                            title="Use UpperCamelCase for type names",
                            body=(
                                f"`{type_name}` should use UpperCamelCase. Dart style guidance recommends "
                                "UpperCamelCase for class, enum, typedef, and extension names."
                            ),
                            confidence=0.84,
                            evidenceRefs=[code_ref(task.taskId, 0), *_pick_doc_refs(hits, ("UpperCamelCase", "camel_case_types"))],
                        )
                    )

            identifier_match = DART_IDENTIFIER_DECLARATION.search(line)
            if identifier_match and not line.strip().startswith("const "):
                identifier = identifier_match.group(1)
                if "_" in identifier and not identifier.startswith("_"):
                    candidates.append(
                        CandidateFinding(
                            filePath=task.filePath,
                            lineStart=line_no,
                            lineEnd=line_no,
                            severity="low",
                            category="style",
                            title="Use lowerCamelCase for non-constant identifiers",
                            body=(
                                f"`{identifier}` should use lowerCamelCase. Dart style guidance recommends "
                                "lowerCamelCase for non-constant identifiers."
                            ),
                            confidence=0.82,
                            evidenceRefs=[code_ref(task.taskId, 0), *_pick_doc_refs(hits, ("lowerCamelCase", "non_constant_identifier_names"))],
                        )
                    )

        elif task.languageSlug == "python":
            class_match = PY_CLASS_DECLARATION.search(line)
            if class_match:
                class_name = class_match.group(1)
                if "_" in class_name.strip("_"):
                    candidates.append(
                        CandidateFinding(
                            filePath=task.filePath,
                            lineStart=line_no,
                            lineEnd=line_no,
                            severity="low",
                            category="style",
                            title="Use CapWords for class names",
                            body=(
                                f"`{class_name}` should follow Python class naming conventions and use CapWords."
                            ),
                            confidence=0.8,
                            evidenceRefs=[code_ref(task.taskId, 0)],
                        )
                    )
            func_match = PY_FUNCTION_DECLARATION.search(line)
            if func_match:
                func_name = func_match.group(1)
                if any(char.isupper() for char in func_name):
                    candidates.append(
                        CandidateFinding(
                            filePath=task.filePath,
                            lineStart=line_no,
                            lineEnd=line_no,
                            severity="low",
                            category="style",
                            title="Use snake_case for function names",
                            body=(
                                f"`{func_name}` should use snake_case to match Python function naming conventions."
                            ),
                            confidence=0.8,
                            evidenceRefs=[code_ref(task.taskId, 0)],
                        )
                    )

    deduped: list[CandidateFinding] = []
    seen: set[tuple[int, str]] = set()
    for candidate in candidates:
        key = (candidate.lineStart, candidate.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped[:2]
