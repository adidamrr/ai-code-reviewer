from __future__ import annotations

import json
from collections import Counter

from .model_client import ModelClientError, ModelClientProtocol
from .schemas import OllamaMessage, PROverview, PROverviewHotspot, RagRequest


def _heuristic_overview(request: RagRequest) -> PROverview:
    file_counter = Counter()
    notes: list[str] = []
    recommended_scopes = [scope for scope in request.scope if scope in {"bugs", "performance", "security"}]
    for file in request.files:
        path = file.path.lower()
        if any(token in path for token in ("auth", "token", "session", "login")):
            file_counter[file.path] += 4
        if any(token in path for token in ("api", "network", "client", "http")):
            file_counter[file.path] += 3
        if any(token in path for token in ("widget", "view", "component", "screen")):
            file_counter[file.path] += 2
        file_counter[file.path] += max(1, len((file.hunks or [])))

    hotspots = [
        PROverviewHotspot(filePath=file_path, reasons=["heuristic-risk"], risk=min(0.95, 0.35 + score / 10.0))
        for file_path, score in file_counter.most_common(5)
    ]
    if any("auth" in hotspot.filePath.lower() or "token" in hotspot.filePath.lower() for hotspot in hotspots):
        notes.append("PR затрагивает auth/session/token flow.")
    if len(request.files) > 10:
        notes.append("PR затрагивает много файлов и требует hotspot-based review.")
    risk_level = "high" if len(request.files) > 12 else "medium" if len(request.files) > 4 else "low"
    return PROverview(
        prIntent=(request.title or "Pull request update").strip(),
        riskLevel=risk_level,
        recommendedScopes=recommended_scopes or ["bugs", "security"],
        hotspots=hotspots,
        notes=notes,
    )


async def build_pr_overview(
    client: ModelClientProtocol,
    request: RagRequest,
    *,
    model: str | None = None,
) -> PROverview:
    heuristic = _heuristic_overview(request)
    summary_payload = {
        "title": request.title or "Untitled PR",
        "description": request.description or "",
        "scope": request.scope,
        "files": [
            {
                "path": file.path,
                "language": file.language,
                "hunks": len(file.hunks or []),
                "imports": file.imports[:8],
                "changedSymbols": file.changedSymbols[:8],
            }
            for file in request.files[:20]
        ],
    }
    messages = [
        OllamaMessage(
            role="system",
            content=(
                "You summarize pull request intent for code review planning. "
                "Return only JSON that matches the provided schema. "
                "Prefer concise, actionable hotspots. "
                "If uncertain, keep heuristic defaults and avoid speculation."
            ),
        ),
        OllamaMessage(role="user", content=json.dumps(summary_payload, ensure_ascii=True)),
    ]
    try:
        payload = await client.chat_structured(
            messages,
            PROverview.model_json_schema(),
            model=model,
            temperature=0.0,
            num_ctx=2048,
        )
        overview = PROverview.model_validate(payload)
        if not overview.hotspots:
            return heuristic
        if not overview.recommendedScopes:
            overview = overview.model_copy(update={"recommendedScopes": heuristic.recommendedScopes})
        return overview
    except (ModelClientError, ValueError):
        return heuristic
