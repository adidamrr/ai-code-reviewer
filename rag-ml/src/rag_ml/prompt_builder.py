from __future__ import annotations

import json

from .schemas import HunkTask, OllamaMessage, RetrievalHit


SYSTEM_PROMPT = (
    "You are a grounded code review assistant. "
    "Use only the provided evidence chunks. "
    "If the evidence is insufficient, return an empty suggestions array. "
    "Do not invent URLs, sources, snippets, or evidence ids. "
    "Prefer fewer high-confidence findings over speculative feedback. "
    "Do not summarize documentation. "
    "Only produce concrete code review comments about the changed code."
)


def build_messages(task: HunkTask, category: str, hits: list[RetrievalHit], max_suggestions: int = 2) -> list[OllamaMessage]:
    evidence = [
        {
            "chunkId": hit.chunkId,
            "sourceId": hit.sourceId,
            "title": hit.title,
            "url": hit.url,
            "headingPath": hit.headingPath,
            "text": hit.text,
        }
        for hit in hits
    ]
    user_prompt = {
        "instructions": {
            "category": category,
            "maxSuggestions": max_suggestions,
            "rules": [
                "Return valid JSON matching the provided schema.",
                "Use only evidenceChunkIds that are present in the evidence list.",
                "If there is no supported finding, return {'suggestions': []}.",
                "Only comment on changed lines in the provided hunk.",
                "Do not write generic documentation summaries or overviews.",
                "Each suggestion must identify a specific issue in the changed code and reference the relevant identifier or construct when possible.",
                "If you cannot point to a concrete issue in the changed code, return {'suggestions': []}.",
            ],
        },
        "file": {
            "path": task.filePath,
            "language": task.language,
            "firstChangedLine": task.firstChangedLine,
            "changedLines": task.changedNewLines,
            "hunkHeader": task.hunkHeader,
            "hunkPatch": task.hunkPatch,
        },
        "evidence": evidence,
    }
    return [
        OllamaMessage(role="system", content=SYSTEM_PROMPT),
        OllamaMessage(role="user", content=json.dumps(user_prompt, ensure_ascii=True)),
    ]
