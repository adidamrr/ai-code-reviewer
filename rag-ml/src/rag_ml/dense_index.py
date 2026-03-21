from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .model_client import ModelClientProtocol
from .schemas import KnowledgeChunk


def normalize_vectors(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


class DenseIndex:
    def __init__(self, chunk_ids: list[str], vectors: np.ndarray) -> None:
        self.chunk_ids = chunk_ids
        self.vectors = normalize_vectors(vectors.astype(np.float32)) if len(vectors) else vectors.astype(np.float32)

    def search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[str, float, int]]:
        if self.vectors.size == 0 or not self.chunk_ids:
            return []
        query = np.asarray(query_vector, dtype=np.float32)
        if query.ndim == 1:
            query = query.reshape(1, -1)
        query = normalize_vectors(query)
        scores = np.matmul(self.vectors, query[0])
        ranked = np.argsort(scores)[::-1]
        results: list[tuple[str, float, int]] = []
        for rank, index in enumerate(ranked[:top_k], start=1):
            score = float(scores[index])
            if score <= 0:
                continue
            results.append((self.chunk_ids[int(index)], score, rank))
        return results


async def build_dense_index(chunks: list[KnowledgeChunk], output_vectors: Path, output_meta: Path, client: ModelClientProtocol) -> None:
    output_vectors.parent.mkdir(parents=True, exist_ok=True)
    output_meta.parent.mkdir(parents=True, exist_ok=True)
    batch_size = max(1, getattr(client, "embed_batch_size", 64))
    texts = [chunk.text for chunk in chunks]
    all_vectors: list[list[float]] = []
    namespace = chunks[0].namespace if chunks else "unknown"
    for offset in range(0, len(texts), batch_size):
        batch = texts[offset : offset + batch_size]
        all_vectors.extend(await client.embed_texts(batch))
        print(f"[dense] {namespace}: {min(offset + len(batch), len(texts))}/{len(texts)}", flush=True)

    matrix = np.asarray(all_vectors, dtype=np.float32)
    matrix = normalize_vectors(matrix)
    np.save(output_vectors, matrix)
    with output_meta.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps({"chunkId": chunk.chunkId}, ensure_ascii=True) + "\n")


def load_dense_index(vectors_path: Path, meta_path: Path) -> DenseIndex:
    vectors = np.load(vectors_path)
    chunk_ids = [json.loads(line)["chunkId"] for line in meta_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return DenseIndex(chunk_ids=chunk_ids, vectors=vectors)
