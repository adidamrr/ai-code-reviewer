from __future__ import annotations

from typing import Any


def severity_weight(value: str) -> int:
    if value == "critical":
        return 5
    if value == "high":
        return 4
    if value == "medium":
        return 3
    if value == "low":
        return 2
    return 1


def rerank_suggestions(suggestions: list[dict[str, Any]], feedback_score_by_fingerprint: dict[str, int]) -> list[dict[str, Any]]:
    return sorted(
        suggestions,
        key=lambda item: (
            -(1 if item.get("deliveryMode", "inline") == "inline" else 0),
            -(feedback_score_by_fingerprint.get(item["fingerprint"], 0)),
            -severity_weight(item["severity"]),
            item["createdAt"],
        ),
    )
