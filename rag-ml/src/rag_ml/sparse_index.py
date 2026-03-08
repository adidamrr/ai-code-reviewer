from __future__ import annotations

import json
import pickle
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from .schemas import KnowledgeChunk

TOKEN_REGEX = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[A-Za-z]+/[A-Za-z0-9_./-]+")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_REGEX.findall(text)]


class SparseIndex:
    def __init__(self, chunk_ids: list[str], tokenized_docs: list[list[str]]) -> None:
        self.chunk_ids = chunk_ids
        self.tokenized_docs = tokenized_docs
        self.bm25 = BM25Okapi(tokenized_docs) if tokenized_docs else None

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float, int]]:
        if not self.bm25:
            return []
        query_tokens = tokenize(query_text)
        if not query_tokens:
            return []
        scores = self.bm25.get_scores(query_tokens)
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        results: list[tuple[str, float, int]] = []
        for rank, (index, score) in enumerate(ranked[:top_k], start=1):
            if score <= 0:
                continue
            results.append((self.chunk_ids[index], float(score), rank))
        return results


def build_sparse_index(chunks: list[KnowledgeChunk], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_ids: list[str] = []
    tokenized_docs: list[list[str]] = []
    for chunk in chunks:
        indexed_text = "\n".join([chunk.sourceTitle, " / ".join(chunk.headingPath), chunk.text, chunk.docPath])
        tokens = tokenize(indexed_text)
        if not tokens:
            continue
        chunk_ids.append(chunk.chunkId)
        tokenized_docs.append(tokens)

    payload = {"chunkIds": chunk_ids, "tokenizedDocs": tokenized_docs}
    with output_path.open("wb") as handle:
        pickle.dump(payload, handle)


def load_sparse_index(path: Path) -> SparseIndex:
    payload = pickle.loads(path.read_bytes())
    return SparseIndex(chunk_ids=list(payload["chunkIds"]), tokenized_docs=list(payload["tokenizedDocs"]))
