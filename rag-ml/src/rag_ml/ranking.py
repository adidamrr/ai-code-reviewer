from __future__ import annotations

import hashlib
from collections import defaultdict

from .schemas import BackendSuggestion, RankedSuggestion
from .validator import normalize_title

SEVERITY_WEIGHTS = {
    "critical": 1.0,
    "high": 0.8,
    "medium": 0.6,
    "low": 0.4,
    "info": 0.2,
}
CATEGORY_PRIORITY = {
    "security": 1.0,
    "bugs": 0.85,
    "performance": 0.75,
    "style": 0.6,
}


def fingerprint_for_suggestion(suggestion: BackendSuggestion) -> str:
    payload = (
        f"{suggestion.filePath}:{suggestion.lineStart}:{suggestion.lineEnd}:"
        f"{normalize_title(suggestion.title)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_ranked_suggestion(suggestion: BackendSuggestion, retrieval_score: float) -> RankedSuggestion:
    severity_weight = SEVERITY_WEIGHTS.get(suggestion.severity, 0.2)
    category_priority = CATEGORY_PRIORITY.get(suggestion.category, 0.5)
    rank_score = (
        0.45 * suggestion.confidence
        + 0.25 * retrieval_score
        + 0.20 * severity_weight
        + 0.10 * category_priority
    )
    return RankedSuggestion(suggestion=suggestion, rankScore=rank_score, retrievalScore=retrieval_score)


def dedupe_and_rank(items: list[RankedSuggestion], max_comments: int, max_per_file: int) -> list[BackendSuggestion]:
    best_by_fingerprint: dict[str, RankedSuggestion] = {}
    for item in items:
        existing = best_by_fingerprint.get(item.suggestion.fingerprint)
        if existing is None or item.rankScore > existing.rankScore:
            best_by_fingerprint[item.suggestion.fingerprint] = item

    ranked = sorted(best_by_fingerprint.values(), key=lambda item: item.rankScore, reverse=True)
    per_file_count: dict[str, int] = defaultdict(int)
    selected: list[BackendSuggestion] = []
    for item in ranked:
        file_path = item.suggestion.filePath
        if per_file_count[file_path] >= max_per_file:
            continue
        selected.append(item.suggestion)
        per_file_count[file_path] += 1
        if len(selected) >= max_comments:
            break
    return selected
