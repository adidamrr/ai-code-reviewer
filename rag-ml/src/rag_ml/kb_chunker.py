from __future__ import annotations

from collections import defaultdict

from .schemas import KnowledgeChunk, NormalizedDocument


def chunk_params(namespace: str) -> tuple[int, int, int]:
    if namespace in {"cpp", "javascript"}:
        return (1300, 2000, 250)
    return (1600, 2200, 250)


def _find_window_end(text: str, start: int, preferred: int, hard_max: int) -> int:
    if len(text) - start <= hard_max:
        return len(text)
    search_end = min(len(text), start + hard_max)
    preferred_end = min(len(text), start + preferred)
    breakpoints = ["\n\n", "\n", ". ", "; "]
    for marker in breakpoints:
        position = text.rfind(marker, start + 200, search_end)
        if position >= preferred_end - 400:
            return position + len(marker)
    return search_end


def chunk_documents(documents: list[NormalizedDocument]) -> list[KnowledgeChunk]:
    counters: dict[tuple[str, str], int] = defaultdict(int)
    chunks: list[KnowledgeChunk] = []

    for document in documents:
        target_size, hard_max, overlap = chunk_params(document.namespace)
        for section in document.sections:
            section_text = document.text[section.charStart:section.charEnd].strip()
            if not section_text:
                continue

            local_start = 0
            while local_start < len(section_text):
                local_end = _find_window_end(section_text, local_start, target_size, hard_max)
                chunk_text = section_text[local_start:local_end].strip()
                if not chunk_text:
                    break

                counters[(document.namespace, document.sourceId)] += 1
                sequence = counters[(document.namespace, document.sourceId)]
                global_start = section.charStart + local_start
                global_end = section.charStart + local_end

                chunks.append(
                    KnowledgeChunk(
                        chunkId=f"{document.namespace}:{document.sourceId}:{sequence:06d}",
                        namespace=document.namespace,
                        language=document.language,
                        sourceId=document.sourceId,
                        sourceTitle=document.sourceTitle,
                        sourceUrl=document.sourceUrl,
                        docPath=document.docPath,
                        headingPath=section.headingPath,
                        text=chunk_text,
                        charStart=global_start,
                        charEnd=global_end,
                        tokenEstimate=max(1, len(chunk_text) // 4),
                    )
                )

                if local_end >= len(section_text):
                    break
                local_start = max(local_end - overlap, local_start + 1)

    return chunks
