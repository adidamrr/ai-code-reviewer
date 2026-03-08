from __future__ import annotations

import re

from .schemas import CandidateFinding, ContextPack, HunkTask, ValidationResult
from .validator import SEVERITIES, THRESHOLDS

DART_TYPE_DECLARATION = re.compile(r"\b(class|enum|typedef|extension)\s+([A-Za-z_][A-Za-z0-9_]*)")
DART_IDENTIFIER_DECLARATION = re.compile(
    r"\b(?:final|var|late|int|double|String|bool|num|dynamic|VoidCallback)\s+([A-Za-z_][A-Za-z0-9_]*)"
)


class FindingVerifier:
    def verify(
        self,
        candidate: CandidateFinding,
        task: HunkTask,
        requested_scope: set[str],
        context_pack: ContextPack,
    ) -> ValidationResult:
        if candidate.category not in requested_scope:
            return ValidationResult(valid=False, reason="category_not_requested")
        if candidate.severity not in SEVERITIES:
            return ValidationResult(valid=False, reason="invalid_severity")
        if not candidate.evidenceRefs:
            return ValidationResult(valid=False, reason="missing_evidence")
        if not (0.0 <= candidate.confidence <= 1.0):
            return ValidationResult(valid=False, reason="invalid_confidence")
        threshold = THRESHOLDS.get(candidate.category, 0.7) - 0.05
        if candidate.confidence < threshold:
            return ValidationResult(valid=False, reason="below_threshold")

        if candidate.category == "style" and task.languageSlug == "dart":
            line = _line_text(task, candidate.lineStart)
            if "UpperCamelCase" in candidate.title:
                type_match = DART_TYPE_DECLARATION.search(line)
                if not type_match:
                    return ValidationResult(valid=False, reason="style_type_not_found")
                type_name = type_match.group(2)
                visible = type_name[1:] if type_name.startswith("_") else type_name
                if visible[:1].isupper() and "_" not in visible:
                    return ValidationResult(valid=False, reason="style_already_valid")
            if "lowerCamelCase" in candidate.title:
                id_match = DART_IDENTIFIER_DECLARATION.search(line)
                if not id_match:
                    return ValidationResult(valid=False, reason="style_identifier_not_found")
                identifier = id_match.group(1)
                if "_" not in identifier and not identifier[:1].isupper():
                    return ValidationResult(valid=False, reason="style_already_valid")

        valid_lines = set(task.changedNewLines)
        if candidate.lineStart in valid_lines and candidate.lineEnd in valid_lines and candidate.lineStart <= candidate.lineEnd:
            return ValidationResult(valid=True, lineStart=candidate.lineStart, lineEnd=candidate.lineEnd)
        if valid_lines:
            nearest = min(valid_lines, key=lambda value: abs(value - candidate.lineStart))
            if abs(nearest - candidate.lineStart) <= 3:
                return ValidationResult(valid=True, lineStart=nearest, lineEnd=nearest)
            return ValidationResult(valid=False, reason="line_out_of_diff")
        return ValidationResult(valid=True, lineStart=max(1, candidate.lineStart), lineEnd=max(candidate.lineStart, candidate.lineEnd))


def _line_text(task: HunkTask, line_no: int) -> str:
    if not task.changedNewLines:
        return task.hunkPatch
    try:
        index = task.changedNewLines.index(line_no)
    except ValueError:
        return task.hunkPatch
    if 0 <= index < len(task.addedLines):
        return task.addedLines[index]
    return task.hunkPatch
