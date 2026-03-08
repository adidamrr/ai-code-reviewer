from __future__ import annotations

import re

from .evidence_models import code_ref, doc_ref, rule_ref
from .schemas import ContextEvidenceCandidate, ContextPack, HunkTask, RetrievalHit, StaticSignal


def _truncate(value: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def build_context_pack(task: HunkTask, signals: list[StaticSignal], doc_hits: list[RetrievalHit]) -> ContextPack:
    code_candidates: list[ContextEvidenceCandidate] = []
    for index, line in enumerate(task.surroundingCode[:8]):
        code_candidates.append(
            ContextEvidenceCandidate(
                refId=code_ref(task.taskId, index),
                type="code",
                title=f"Кодовый контекст {task.filePath}:{line.lineNumber}",
                snippet=_truncate(line.text),
                filePath=task.filePath,
                lineStart=line.lineNumber,
                lineEnd=line.lineNumber,
                metadata={"taskId": task.taskId},
            )
        )
    if not code_candidates:
        code_candidates.append(
            ContextEvidenceCandidate(
                refId=code_ref(task.taskId, 0),
                type="code",
                title=f"Измененный hunk {task.filePath}",
                snippet=_truncate(task.hunkPatch, 360),
                filePath=task.filePath,
                lineStart=task.firstChangedLine,
                lineEnd=max(task.changedNewLines) if task.changedNewLines else task.firstChangedLine,
                metadata={"taskId": task.taskId},
            )
        )

    rule_candidates = [
        ContextEvidenceCandidate(
            refId=rule_ref(task.taskId, index),
            type="rule",
            title=f"Статический сигнал: {signal.type}",
            snippet=_truncate(signal.message),
            filePath=signal.filePath,
            lineStart=signal.lineStart,
            lineEnd=signal.lineEnd,
            metadata={"signalId": signal.signalId, "severity": signal.severity},
        )
        for index, signal in enumerate(signals)
    ]

    doc_candidates = [
        ContextEvidenceCandidate(
            refId=doc_ref(hit.chunkId),
            type="doc",
            title=hit.title,
            snippet=_truncate(hit.text, 300),
            sourceId=hit.sourceId,
            url=hit.url,
            metadata={"chunkId": hit.chunkId, "headingPath": hit.headingPath},
        )
        for hit in doc_hits
    ]

    return ContextPack(
        taskId=task.taskId,
        codeEvidenceCandidates=code_candidates,
        ruleEvidenceCandidates=rule_candidates,
        docEvidenceCandidates=doc_candidates,
        historyEvidenceCandidates=[],
    )
