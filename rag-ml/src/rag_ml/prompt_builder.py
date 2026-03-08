from __future__ import annotations

import json

from .schemas import ContextPack, HunkTask, OllamaMessage


SYSTEM_PROMPT = (
    "You are a grounded code review assistant. "
    "You are working inside a staged code review pipeline. "
    "Use only the provided evidence references. "
    "Return JSON only. "
    "If you cannot justify a finding with evidenceRefs, return an empty suggestions array. "
    "Comments must be about the changed code, not documentation summaries. "
    "Prefer fewer, specific findings over broad commentary."
)


def _truncate_text(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _serialize_context(context_pack: ContextPack) -> dict:
    return {
        "code": [candidate.model_dump() for candidate in context_pack.codeEvidenceCandidates[:8]],
        "rules": [candidate.model_dump() for candidate in context_pack.ruleEvidenceCandidates[:8]],
        "docs": [candidate.model_dump() for candidate in context_pack.docEvidenceCandidates[:6]],
        "history": [candidate.model_dump() for candidate in context_pack.historyEvidenceCandidates[:4]],
    }


def build_messages(
    task: HunkTask,
    categories: list[str],
    context_pack: ContextPack,
    *,
    max_suggestions: int = 2,
) -> list[OllamaMessage]:
    user_prompt = {
        "instructions": {
            "allowedCategories": categories,
            "maxSuggestions": max_suggestions,
            "rules": [
                "Return valid JSON matching the provided schema.",
                "Each suggestion.evidenceRefs item must match one of the provided evidence refIds.",
                "If there is no grounded finding, return {'suggestions': []}.",
                "Only comment on changed code or directly affected behavior.",
                "Use code or rule evidence when documentation evidence is not necessary.",
                "Avoid generic suggestions and documentation summaries.",
                "Do not invent sources, URLs, snippets, or evidence ids.",
            ],
        },
        "task": {
            "taskId": task.taskId,
            "filePath": task.filePath,
            "language": task.languageSlug,
            "categories": categories,
            "reasons": task.reasons,
            "firstChangedLine": task.firstChangedLine,
            "changedLines": task.changedNewLines,
            "changedSymbols": task.changedSymbols[:10],
            "imports": task.imports[:10],
            "hunkHeader": task.hunkHeader,
            "hunkPatch": _truncate_text(task.hunkPatch, 1800),
            "addedLines": task.addedLines[:20],
        },
        "context": _serialize_context(context_pack),
    }
    return [
        OllamaMessage(role="system", content=SYSTEM_PROMPT),
        OllamaMessage(role="user", content=json.dumps(user_prompt, ensure_ascii=True)),
    ]
