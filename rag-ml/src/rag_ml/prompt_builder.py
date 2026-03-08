from __future__ import annotations

import json

from .schemas import ContextPack, FindingOutline, OllamaMessage, HunkTask

DETECTOR_SYSTEM_PROMPT = (
    "You are a grounded code review detector. "
    "Your job is to return compact structured findings only. "
    "Do not explain at length. Do not summarize documentation. "
    "Use only provided evidence reference ids. "
    "If there is no grounded issue, return an empty findings array."
)

DETECTOR_LINE_SYSTEM_PROMPT = (
    "You are a grounded code review detector. "
    "Return findings using one line per finding in the exact format "
    "FINDING|<category>|<severity>|<lineStart>|<lineEnd>|<shortLabel>|<evidenceRef1,evidenceRef2>. "
    "If there are no grounded issues, return exactly NO_FINDINGS. "
    "Do not output JSON. Do not add any prose."
)

JSON_REPAIR_SYSTEM_PROMPT = (
    "You are a strict syntax repair assistant for code review findings. "
    "You receive malformed detector output. "
    "Return valid JSON matching the provided schema. "
    "Preserve the original meaning. "
    "Only fix linear syntax issues such as commas, quotes, code fences, or truncation if recoverable. "
    "If the content cannot be safely repaired, return {\"findings\": []}."
)

EXPLAINER_SYSTEM_PROMPT = (
    "You are a concise code review explainer. "
    "You receive one accepted finding and must produce a short human-readable title and body. "
    "Do not invent evidence or claims beyond the provided finding and context."
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
        "docs": [candidate.model_dump() for candidate in context_pack.docEvidenceCandidates[:4]],
        "history": [candidate.model_dump() for candidate in context_pack.historyEvidenceCandidates[:4]],
    }


def build_detection_messages(
    task: HunkTask,
    categories: list[str],
    context_pack: ContextPack,
    *,
    max_findings: int = 2,
) -> list[OllamaMessage]:
    user_prompt = {
        "instructions": {
            "allowedCategories": categories,
            "maxFindings": max_findings,
            "rules": [
                "Return valid JSON matching the provided schema.",
                "Use only evidenceRefs from the provided evidence candidates.",
                "Prefer specific local issues over general comments.",
                "Do not emit documentation summaries.",
                "If uncertain, return {'findings': []}.",
            ],
        },
        "task": {
            "taskId": task.taskId,
            "filePath": task.filePath,
            "fileClass": task.fileClass,
            "language": task.languageSlug,
            "categories": categories,
            "reasons": task.reasons,
            "firstChangedLine": task.firstChangedLine,
            "changedLines": task.changedNewLines,
            "changedSymbols": task.changedSymbols[:10],
            "imports": task.imports[:10],
            "hunkHeader": task.hunkHeader,
            "hunkPatch": _truncate_text(task.hunkPatch, 1400),
            "addedLines": task.addedLines[:18],
        },
        "context": _serialize_context(context_pack),
    }
    return [
        OllamaMessage(role="system", content=DETECTOR_SYSTEM_PROMPT),
        OllamaMessage(role="user", content=json.dumps(user_prompt, ensure_ascii=True)),
    ]


def build_detection_line_messages(
    task: HunkTask,
    categories: list[str],
    context_pack: ContextPack,
    *,
    max_findings: int = 2,
) -> list[OllamaMessage]:
    user_prompt = {
        "instructions": {
            "allowedCategories": categories,
            "maxFindings": max_findings,
            "rules": [
                "Return one FINDING line per issue or NO_FINDINGS.",
                "Use only evidenceRefs from the provided evidence candidates.",
                "Use severity only from: info, low, medium, high, critical.",
                "Keep shortLabel compact and specific.",
                "If uncertain, return NO_FINDINGS.",
            ],
        },
        "task": {
            "taskId": task.taskId,
            "filePath": task.filePath,
            "fileClass": task.fileClass,
            "language": task.languageSlug,
            "categories": categories,
            "reasons": task.reasons,
            "firstChangedLine": task.firstChangedLine,
            "changedLines": task.changedNewLines,
            "changedSymbols": task.changedSymbols[:10],
            "imports": task.imports[:10],
            "hunkHeader": task.hunkHeader,
            "hunkPatch": _truncate_text(task.hunkPatch, 1400),
            "addedLines": task.addedLines[:18],
        },
        "context": _serialize_context(context_pack),
    }
    return [
        OllamaMessage(role="system", content=DETECTOR_LINE_SYSTEM_PROMPT),
        OllamaMessage(role="user", content=json.dumps(user_prompt, ensure_ascii=True)),
    ]


def build_json_repair_messages(
    task: HunkTask,
    categories: list[str],
    context_pack: ContextPack,
    invalid_content: str,
    *,
    max_findings: int = 2,
) -> list[OllamaMessage]:
    user_prompt = {
        "instructions": {
            "allowedCategories": categories,
            "maxFindings": max_findings,
            "rules": [
                "Return valid JSON matching the provided schema.",
                "Repair only syntax and formatting issues when safe.",
                "Do not invent new findings that are not already present in the malformed output.",
                "If the output cannot be repaired safely, return {'findings': []}.",
            ],
        },
        "task": {
            "taskId": task.taskId,
            "filePath": task.filePath,
            "language": task.languageSlug,
        },
        "context": _serialize_context(context_pack),
        "malformedDetectorOutput": _truncate_text(invalid_content, 2400),
    }
    return [
        OllamaMessage(role="system", content=JSON_REPAIR_SYSTEM_PROMPT),
        OllamaMessage(role="user", content=json.dumps(user_prompt, ensure_ascii=True)),
    ]


def build_explainer_messages(
    task: HunkTask,
    outline: FindingOutline,
    context_pack: ContextPack,
) -> list[OllamaMessage]:
    user_prompt = {
        "rules": [
            "Return valid JSON matching the provided schema.",
            "Keep the title short and actionable.",
            "Keep the body to one short paragraph.",
            "Do not mention documentation unless it is required by the finding.",
            "Do not invent new evidence or change the category.",
        ],
        "task": {
            "taskId": task.taskId,
            "filePath": task.filePath,
            "language": task.languageSlug,
            "hunkPatch": _truncate_text(task.hunkPatch, 1200),
        },
        "finding": outline.model_dump(),
        "context": _serialize_context(context_pack),
    }
    return [
        OllamaMessage(role="system", content=EXPLAINER_SYSTEM_PROMPT),
        OllamaMessage(role="user", content=json.dumps(user_prompt, ensure_ascii=True)),
    ]
