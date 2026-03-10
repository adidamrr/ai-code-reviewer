from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from .schemas import BackendSuggestion, Evidence, RankedSuggestion
from .validator import normalize_title

SEVERITY_WEIGHTS = {
    "critical": 1.0,
    "high": 0.8,
    "medium": 0.6,
    "low": 0.4,
    "info": 0.2,
}


def fingerprint_for_suggestion(suggestion: BackendSuggestion) -> str:
    payload = (
        f"{suggestion.filePath}:{suggestion.lineStart}:{suggestion.lineEnd}:"
        f"{normalize_title(suggestion.title)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evidence_strength(evidence: list[Evidence]) -> float:
    types = {item.type for item in evidence}
    if "code" in types and "rule" in types:
        return 1.0
    if "code" in types and "doc" in types:
        return 0.9
    if "code" in types:
        return 0.8
    if "rule" in types:
        return 0.7
    if "doc" in types:
        return 0.55
    return 0.3


def evidence_signature(evidence: list[Evidence]) -> str:
    types = sorted({item.type for item in evidence})
    if not types:
        return "none"
    return "+".join(types)


def build_ranked_suggestion(
    suggestion: BackendSuggestion,
    *,
    retrieval_score: float,
    planner_priority: float,
    static_support: float,
    repo_feedback_score: float,
) -> RankedSuggestion:
    severity_weight = SEVERITY_WEIGHTS.get(suggestion.severity, 0.2)
    ev_strength = evidence_strength(suggestion.evidence)
    ev_signature = evidence_signature(suggestion.evidence)
    suggestion_meta: dict[str, Any] = dict(suggestion.meta)
    suggestion_meta["rankFeatures"] = {
        "confidence": suggestion.confidence,
        "rankScore": 0.0,
        "retrievalScore": retrieval_score,
        "plannerPriority": planner_priority,
        "staticSupport": static_support,
        "repoFeedbackScore": repo_feedback_score,
        "evidenceStrength": ev_strength,
        "evidenceSignature": ev_signature,
        "titleTemplate": f"{suggestion.category}:{normalize_title(suggestion.title)}",
        "deliveryMode": suggestion.deliveryMode,
        "category": suggestion.category,
        "severity": suggestion.severity,
    }
    rank_score = (
        0.30 * suggestion.confidence
        + 0.25 * ev_strength
        + 0.20 * planner_priority
        + 0.15 * static_support
        + 0.10 * max(-1.0, min(1.0, repo_feedback_score / 5.0))
        + 0.05 * retrieval_score
        + 0.05 * severity_weight
    )
    suggestion_meta["rankFeatures"]["rankScore"] = rank_score
    return RankedSuggestion(
        suggestion=suggestion.model_copy(update={"meta": suggestion_meta}),
        rankScore=rank_score,
        retrievalScore=retrieval_score,
        evidenceStrength=ev_strength,
        plannerPriority=planner_priority,
        staticSupport=static_support,
        repoFeedbackScore=repo_feedback_score,
    )


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
        if item.suggestion.deliveryMode == "inline" and per_file_count[file_path] >= max_per_file:
            continue
        selected.append(item.suggestion)
        if item.suggestion.deliveryMode == "inline":
            per_file_count[file_path] += 1
        if len(selected) >= max_comments:
            break
    return selected
