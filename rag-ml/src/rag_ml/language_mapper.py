from __future__ import annotations

DISPLAY_TO_SLUG = {
    "Python": "python",
    "Dart": "dart",
    "Swift": "swift",
    "C++": "cpp",
    "JavaScript": "javascript",
    "Javascript": "javascript",
}


def to_slug(language: str) -> str | None:
    normalized = (language or "").strip()
    if not normalized:
        return None
    if normalized.lower() in {"python", "dart", "swift", "cpp", "javascript"}:
        return normalized.lower()
    return DISPLAY_TO_SLUG.get(normalized)
