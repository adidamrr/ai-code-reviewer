from __future__ import annotations

import re

from .evidence_models import unwrap_doc_ref
from .schemas import Citation, ContextPack, Evidence, KnowledgeChunk


def _truncate_preserving_lines(value: str, *, max_lines: int = 12, max_chars: int = 420) -> str:
    normalized_lines: list[str] = []
    for raw_line in value.splitlines():
        line = re.sub(r"[\t ]+", " ", raw_line).rstrip()
        if line:
            normalized_lines.append(line)

    if not normalized_lines:
        return ""

    clipped_lines = normalized_lines[:max_lines]
    snippet = "\n".join(clipped_lines)
    if len(snippet) <= max_chars and len(normalized_lines) <= max_lines:
        return snippet

    clipped = snippet[: max_chars - 3].rstrip()
    return f"{clipped}..."


class CitationResolver:
    def __init__(self, chunks_by_id: dict[str, KnowledgeChunk]) -> None:
        self.chunks_by_id = chunks_by_id

    def resolve(self, evidence_refs: list[str], context_pack: ContextPack) -> tuple[list[Evidence], list[Citation]]:
        candidate_by_ref = {
            candidate.refId: candidate
            for candidate in (
                context_pack.codeEvidenceCandidates
                + context_pack.ruleEvidenceCandidates
                + context_pack.docEvidenceCandidates
                + context_pack.historyEvidenceCandidates
            )
        }
        evidence: list[Evidence] = []
        citations: list[Citation] = []
        seen_doc_sources: set[str] = set()
        for evidence_ref in evidence_refs:
            doc_chunk_id = unwrap_doc_ref(evidence_ref)
            if doc_chunk_id:
                chunk = self.chunks_by_id.get(doc_chunk_id)
                if not chunk:
                    return [], []
                snippet = _truncate_preserving_lines(chunk.text)
                if len(snippet) < 40:
                    return [], []
                evidence.append(
                    Evidence(
                        evidenceId=evidence_ref,
                        type="doc",
                        title=chunk.sourceTitle,
                        snippet=snippet,
                        sourceId=chunk.sourceId,
                        url=chunk.sourceUrl,
                        metadata={
                            "chunkId": chunk.chunkId,
                            "headingPath": chunk.headingPath,
                            "docPath": chunk.docPath,
                        },
                    )
                )
                if chunk.sourceId not in seen_doc_sources:
                    citations.append(
                        Citation(
                            sourceId=chunk.sourceId,
                            title=chunk.sourceTitle,
                            url=chunk.sourceUrl,
                            snippet=snippet,
                        )
                    )
                    seen_doc_sources.add(chunk.sourceId)
                continue

            candidate = candidate_by_ref.get(evidence_ref)
            if not candidate:
                return [], []
            evidence.append(
                Evidence(
                    evidenceId=candidate.refId,
                    type=candidate.type,
                    title=candidate.title,
                    snippet=candidate.snippet,
                    filePath=candidate.filePath,
                    lineStart=candidate.lineStart,
                    lineEnd=candidate.lineEnd,
                    sourceId=candidate.sourceId,
                    url=candidate.url,
                    metadata=candidate.metadata,
                )
            )

        return evidence[:4], citations[:2]
