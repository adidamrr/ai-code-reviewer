from __future__ import annotations

from typing import Any

DEFAULT_CITATIONS: dict[str, dict[str, str]] = {
    "security": {
        "sourceId": "owasp-top-10",
        "title": "OWASP Top 10",
        "url": "https://owasp.org/www-project-top-ten/",
        "snippet": "Validate all untrusted input and use context-aware output encoding.",
    },
    "style": {
        "sourceId": "clean-code",
        "title": "Clean Code Principles",
        "url": "https://martinfowler.com/bliki/CodeSmell.html",
        "snippet": "Prefer clear naming and small focused functions.",
    },
    "bugs": {
        "sourceId": "github-engineering",
        "title": "GitHub Engineering Practices",
        "url": "https://github.blog/engineering/",
        "snippet": "Cover edge cases and fail fast with actionable errors.",
    },
    "performance": {
        "sourceId": "web-dev-performance",
        "title": "Web Performance Fundamentals",
        "url": "https://web.dev/fast/",
        "snippet": "Avoid unnecessary work in hot paths and use bounded loops.",
    },
}


def choose_severity(category: str) -> str:
    if category == "security":
        return "high"
    if category == "performance":
        return "medium"
    if category == "style":
        return "low"
    return "medium"


async def analyze_with_rag(request: dict[str, Any]) -> dict[str, Any]:
    suggestions: list[dict[str, Any]] = []
    scope = request.get("scope") or ["bugs"]
    files = request.get("files") or []
    limits = request.get("limits") or {}
    max_comments = int(limits.get("maxComments") or 50)

    for index, file in enumerate(files):
        if len(suggestions) >= max_comments:
            break

        patch = str(file.get("patch") or "").strip()
        if not patch:
            continue

        line_map = file.get("lineMap") or []
        first_added_line = 1
        for entry in line_map:
            if entry.get("type") == "add":
                first_added_line = entry.get("newLine") or 1
                break

        category = scope[index % len(scope)]
        suggestions.append(
            {
                "filePath": file.get("path"),
                "lineStart": first_added_line,
                "lineEnd": first_added_line,
                "severity": choose_severity(category),
                "category": category,
                "title": f"Potential {category} issue in {file.get('path')}",
                "body": f"Check this change for {category} risks and ensure it follows team standards.",
                "citations": [DEFAULT_CITATIONS[category]],
                "confidence": 0.72,
            }
        )

    return {
        "suggestions": suggestions,
        "partialFailures": 0,
    }
