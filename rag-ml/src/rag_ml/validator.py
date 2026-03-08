from __future__ import annotations

import re

from .schemas import CandidateFinding, HunkTask, ValidationResult

SEVERITIES = {"info", "low", "medium", "high", "critical"}
IDENTIFIER_REGEX = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
GENERIC_PHRASES = (
    "this section provides",
    "this section covers",
    "overview of the",
    "various topics related",
)
THRESHOLDS = {
    "style": 0.60,
    "bugs": 0.65,
    "performance": 0.68,
    "security": 0.72,
}
CATEGORY_KEYWORDS = {
    "style": {"camelcase", "lowercamelcase", "uppercamelcase", "identifier", "naming", "convention"},
    "bugs": {"null", "exception", "async", "state", "logic", "edge case", "handle"},
    "performance": {"performance", "loop", "blocking", "allocation", "copy", "complexity", "repeated"},
    "security": {"security", "validate", "sanitize", "injection", "auth", "secret", "unsafe"},
}


def _identifiers_from_task(task: HunkTask) -> set[str]:
    identifiers = set()
    for line in task.addedLines:
        for token in IDENTIFIER_REGEX.findall(line):
            if len(token) < 3:
                continue
            if token.lower() in {"final", "const", "var", "int", "double", "string", "return"}:
                continue
            identifiers.add(token.lower())
    return identifiers


def _is_specific_enough(candidate: CandidateFinding, task: HunkTask) -> bool:
    combined = f"{candidate.title} {candidate.body}".lower()
    if any(phrase in combined for phrase in GENERIC_PHRASES):
        return False
    identifiers = _identifiers_from_task(task)
    if any(identifier in combined for identifier in identifiers):
        return True
    keywords = CATEGORY_KEYWORDS.get(candidate.category, set())
    return any(keyword in combined for keyword in keywords)


class SuggestionValidator:
    def validate(self, candidate: CandidateFinding, task: HunkTask, requested_scope: set[str]) -> ValidationResult:
        if candidate.category not in requested_scope:
            return ValidationResult(valid=False, reason="category_not_requested")
        if candidate.severity not in SEVERITIES:
            return ValidationResult(valid=False, reason="invalid_severity")
        if not candidate.title.strip() or not candidate.body.strip():
            return ValidationResult(valid=False, reason="missing_text")
        if not candidate.evidenceRefs:
            return ValidationResult(valid=False, reason="missing_evidence")
        if not (0.0 <= candidate.confidence <= 1.0):
            return ValidationResult(valid=False, reason="invalid_confidence")
        threshold = THRESHOLDS.get(candidate.category, 0.7)
        if candidate.confidence < threshold:
            return ValidationResult(valid=False, reason="below_threshold")
        if not _is_specific_enough(candidate, task):
            return ValidationResult(valid=False, reason="generic_feedback")

        line_start = candidate.lineStart
        line_end = candidate.lineEnd
        if not task.changedNewLines:
            line_start = max(1, line_start)
            line_end = max(line_start, line_end)
            return ValidationResult(valid=True, lineStart=line_start, lineEnd=line_end)

        valid_lines = set(task.changedNewLines)
        if line_start in valid_lines and line_end in valid_lines and line_start <= line_end:
            return ValidationResult(valid=True, lineStart=line_start, lineEnd=line_end)

        nearest = min(task.changedNewLines, key=lambda value: abs(value - line_start))
        if abs(nearest - line_start) <= 3:
            return ValidationResult(valid=True, lineStart=nearest, lineEnd=nearest)
        return ValidationResult(valid=False, reason="line_out_of_diff")


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())
