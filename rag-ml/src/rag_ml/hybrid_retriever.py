from __future__ import annotations

from collections import defaultdict

import numpy as np

from .dense_index import DenseIndex
from .schemas import KnowledgeChunk, RetrievalHit
from .sparse_index import SparseIndex

RRF_K = 60
NOISE_FRAGMENTS = (
    "skip to main content",
    "uses cookies from google",
    "overview docs blog community",
    "light_mode",
    "dark_mode",
    "night_sight_auto",
    "view source bug_repo",
)


def _is_low_quality_chunk(text: str) -> bool:
    lowered = text.lower()
    return any(fragment in lowered for fragment in NOISE_FRAGMENTS)


class HybridRetriever:
    def __init__(self, chunks_by_id: dict[str, KnowledgeChunk], sparse_by_namespace: dict[str, SparseIndex], dense_by_namespace: dict[str, DenseIndex]) -> None:
        self.chunks_by_id = chunks_by_id
        self.sparse_by_namespace = sparse_by_namespace
        self.dense_by_namespace = dense_by_namespace

    def search(
        self,
        namespaces: list[str],
        query_text: str,
        query_vector: np.ndarray | None,
        *,
        sparse_k: int = 12,
        dense_k: int = 12,
        top_k: int = 6,
    ) -> list[RetrievalHit]:
        score_by_chunk: dict[str, float] = defaultdict(float)
        sparse_rank_by_chunk: dict[str, int] = {}
        dense_rank_by_chunk: dict[str, int] = {}

        for namespace in namespaces:
            sparse_index = self.sparse_by_namespace.get(namespace)
            if sparse_index:
                for chunk_id, _score, rank in sparse_index.search(query_text, sparse_k):
                    score_by_chunk[chunk_id] += 1.0 / (RRF_K + rank)
                    sparse_rank_by_chunk.setdefault(chunk_id, rank)

            dense_index = self.dense_by_namespace.get(namespace)
            if dense_index and query_vector is not None:
                for chunk_id, _score, rank in dense_index.search(query_vector, dense_k):
                    score_by_chunk[chunk_id] += 1.0 / (RRF_K + rank)
                    dense_rank_by_chunk.setdefault(chunk_id, rank)

        ranked = sorted(score_by_chunk.items(), key=lambda item: item[1], reverse=True)
        hits: list[RetrievalHit] = []
        for chunk_id, score in ranked:
            chunk = self.chunks_by_id.get(chunk_id)
            if not chunk:
                continue
            if _is_low_quality_chunk(chunk.text):
                continue
            hits.append(
                RetrievalHit(
                    chunkId=chunk.chunkId,
                    namespace=chunk.namespace,
                    sourceId=chunk.sourceId,
                    title=chunk.sourceTitle,
                    url=chunk.sourceUrl,
                    headingPath=chunk.headingPath,
                    text=chunk.text,
                    finalScore=float(score),
                    sparseRank=sparse_rank_by_chunk.get(chunk_id),
                    denseRank=dense_rank_by_chunk.get(chunk_id),
                )
            )
            if len(hits) >= top_k:
                break
        return hits
