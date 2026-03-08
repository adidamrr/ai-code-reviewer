from __future__ import annotations

from .schemas import BackendSuggestion


def assign_delivery_mode(suggestion: BackendSuggestion) -> BackendSuggestion:
    evidence_types = {item.type for item in suggestion.evidence}
    has_precise_range = suggestion.lineStart > 0 and suggestion.lineEnd >= suggestion.lineStart
    if suggestion.confidence >= 0.70 and has_precise_range and evidence_types.intersection({"code", "rule", "doc"}):
        return suggestion.model_copy(update={"deliveryMode": "inline"})
    return suggestion.model_copy(update={"deliveryMode": "summary"})


def synthesize_suggestions(suggestions: list[BackendSuggestion]) -> list[BackendSuggestion]:
    return [assign_delivery_mode(suggestion) for suggestion in suggestions]
