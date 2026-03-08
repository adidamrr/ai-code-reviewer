from __future__ import annotations

import re

from .schemas import Citation, KnowledgeChunk


class CitationResolver:
    def __init__(self, chunks_by_id: dict[str, KnowledgeChunk]) -> None:
        self.chunks_by_id = chunks_by_id

    def resolve(self, evidence_chunk_ids: list[str]) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[str] = set()
        for chunk_id in evidence_chunk_ids:
            chunk = self.chunks_by_id.get(chunk_id)
            if not chunk:
                return []
            if chunk.sourceId in seen:
                continue
            snippet = re.sub(r"\s+", " ", chunk.text).strip()[:320]
            if len(snippet) < 40:
                return []
            citations.append(
                Citation(
                    sourceId=chunk.sourceId,
                    title=chunk.sourceTitle,
                    url=chunk.sourceUrl,
                    snippet=snippet,
                )
            )
            seen.add(chunk.sourceId)
            if len(citations) >= 2:
                break
        return citations
