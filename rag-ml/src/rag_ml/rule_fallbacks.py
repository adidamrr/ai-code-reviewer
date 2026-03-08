from __future__ import annotations

import re

from .evidence_models import doc_ref
from .schemas import CandidateFinding, HunkTask, RetrievalHit

TYPE_DECLARATION = re.compile(r"\b(class|enum|typedef|extension)\s+([A-Za-z_][A-Za-z0-9_]*)")
NON_CONSTANT_IDENTIFIER = re.compile(
    r"\b(?:final|var|late|int|double|String|bool|num|dynamic)\s+([A-Za-z_][A-Za-z0-9_]*)"
)


def _line_for_match(task: HunkTask, index: int) -> int:
    if 0 <= index < len(task.changedNewLines):
        return task.changedNewLines[index]
    return task.firstChangedLine


def _pick_evidence_ids(hits: list[RetrievalHit], keywords: tuple[str, ...]) -> list[str]:
    preferred = [
        doc_ref(hit.chunkId)
        for hit in hits
        if any(keyword.lower() in hit.text.lower() for keyword in keywords)
    ]
    if preferred:
        return preferred[:2]
    return [doc_ref(hit.chunkId) for hit in hits[:2]]


def style_fallback_candidates(task: HunkTask, hits: list[RetrievalHit]) -> list[CandidateFinding]:
    if task.languageSlug != "dart":
        return []

    candidates: list[CandidateFinding] = []
    for index, line in enumerate(task.addedLines):
        type_match = TYPE_DECLARATION.search(line)
        if type_match:
            type_name = type_match.group(2)
            if type_name and not type_name[:1].isupper():
                candidates.append(
                    CandidateFinding(
                        filePath=task.filePath,
                        lineStart=_line_for_match(task, index),
                        lineEnd=_line_for_match(task, index),
                        severity="low",
                        category="style",
                        title="Use UpperCamelCase for type names",
                        body=(
                            f"`{type_name}` should use UpperCamelCase. Dart style guidance recommends "
                            "UpperCamelCase for class, enum, typedef, and extension names."
                        ),
                        confidence=0.78,
                        evidenceRefs=_pick_evidence_ids(hits, ("UpperCamelCase", "camel_case_types")),
                    )
                )

        identifier_match = NON_CONSTANT_IDENTIFIER.search(line)
        if identifier_match and not line.strip().startswith("const "):
            identifier = identifier_match.group(1)
            if "_" in identifier or (identifier[:1].isupper() and not TYPE_DECLARATION.search(line)):
                candidates.append(
                    CandidateFinding(
                        filePath=task.filePath,
                        lineStart=_line_for_match(task, index),
                        lineEnd=_line_for_match(task, index),
                        severity="low",
                        category="style",
                        title="Use lowerCamelCase for non-constant identifiers",
                        body=(
                            f"`{identifier}` should use lowerCamelCase. Dart style guidance recommends "
                            "lowerCamelCase for non-constant identifiers."
                        ),
                        confidence=0.76,
                        evidenceRefs=_pick_evidence_ids(
                            hits,
                            ("lowerCamelCase", "non_constant_identifier_names", "constant_identifier_names"),
                        ),
                    )
                )

    deduped: list[CandidateFinding] = []
    seen: set[tuple[int, str]] = set()
    for candidate in candidates:
        key = (candidate.lineStart, candidate.title)
        if key in seen:
            continue
        deduped.append(candidate)
        seen.add(key)
    return deduped[:2]
