from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .citation_resolver import CitationResolver
from .config import RagConfig, load_config
from .dense_index import build_dense_index, load_dense_index
from .generator import SuggestionGenerator
from .hunk_selector import select_hunks
from .hybrid_retriever import HybridRetriever
from .kb_chunker import chunk_documents
from .kb_inventory import build_inventory, write_inventory
from .kb_loader import collect_document_descriptors
from .kb_normalizer import normalize_descriptor
from .language_mapper import to_slug
from .ollama_client import OllamaClient, OllamaError
from .query_builder import build_query
from .ranking import build_ranked_suggestion, dedupe_and_rank, fingerprint_for_suggestion
from .rule_fallbacks import style_fallback_candidates
from .schemas import BackendSuggestion, BuildManifest, BuildNamespaceMeta, KnowledgeChunk, RagRequest, RagResponse
from .sparse_index import build_sparse_index, load_sparse_index
from .validator import SuggestionValidator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _chunks_dir(config: RagConfig) -> Path:
    return config.build_root / "chunks"


def _sparse_dir(config: RagConfig) -> Path:
    return config.build_root / "sparse"


def _dense_dir(config: RagConfig) -> Path:
    return config.build_root / "dense"


def _chunk_path(config: RagConfig, namespace: str) -> Path:
    return _chunks_dir(config) / f"{namespace}.chunks.jsonl"


def _sparse_path(config: RagConfig, namespace: str) -> Path:
    return _sparse_dir(config) / f"{namespace}.bm25.pkl"


def _dense_vector_path(config: RagConfig, namespace: str) -> Path:
    return _dense_dir(config) / f"{namespace}.vectors.npy"


def _dense_meta_path(config: RagConfig, namespace: str) -> Path:
    return _dense_dir(config) / f"{namespace}.meta.jsonl"


def _build_manifest_path(config: RagConfig) -> Path:
    return config.build_root / "build-manifest.json"


def _remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def _clear_namespace_artifacts(config: RagConfig, namespace: str) -> None:
    _remove_if_exists(_chunk_path(config, namespace))
    _remove_if_exists(_sparse_path(config, namespace))
    _remove_if_exists(_dense_vector_path(config, namespace))
    _remove_if_exists(_dense_meta_path(config, namespace))


def _load_existing_build_manifest(config: RagConfig) -> BuildManifest | None:
    path = _build_manifest_path(config)
    if not path.exists():
        return None
    try:
        return BuildManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def write_chunks(path: Path, chunks: list[KnowledgeChunk]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.model_dump(), ensure_ascii=True) + "\n")


def load_chunk_store(config: RagConfig) -> dict[str, KnowledgeChunk]:
    chunks_by_id: dict[str, KnowledgeChunk] = {}
    chunks_dir = _chunks_dir(config)
    if not chunks_dir.exists():
        return chunks_by_id
    for chunk_file in sorted(chunks_dir.glob("*.chunks.jsonl")):
        for line in chunk_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            chunk = KnowledgeChunk.model_validate(json.loads(line))
            chunks_by_id[chunk.chunkId] = chunk
    return chunks_by_id


class RagRuntime:
    def __init__(self, config: RagConfig, chunks_by_id: dict[str, KnowledgeChunk]) -> None:
        self.config = config
        self.chunks_by_id = chunks_by_id
        self.sparse_by_namespace = {}
        self.dense_by_namespace = {}
        for namespace in {chunk.namespace for chunk in chunks_by_id.values()}:
            sparse_path = _sparse_path(config, namespace)
            dense_path = _dense_vector_path(config, namespace)
            dense_meta = _dense_meta_path(config, namespace)
            if sparse_path.exists():
                self.sparse_by_namespace[namespace] = load_sparse_index(sparse_path)
            if dense_path.exists() and dense_meta.exists():
                self.dense_by_namespace[namespace] = load_dense_index(dense_path, dense_meta)
        self.client = OllamaClient(config)
        self.retriever = HybridRetriever(chunks_by_id, self.sparse_by_namespace, self.dense_by_namespace)
        self.generator = SuggestionGenerator(self.client)
        self.citation_resolver = CitationResolver(chunks_by_id)
        self.validator = SuggestionValidator()

    def has_namespace(self, namespace: str) -> bool:
        return namespace in self.sparse_by_namespace and namespace in self.dense_by_namespace


_RUNTIME: RagRuntime | None = None


def _load_runtime(config: RagConfig) -> RagRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        chunks_by_id = load_chunk_store(config)
        if not chunks_by_id:
            raise RuntimeError(
                "RAG build artifacts are missing. Run 'python rag-ml/scripts/build_indexes.py' first."
            )
        _RUNTIME = RagRuntime(config, chunks_by_id)
    return _RUNTIME


async def build_artifacts(config: RagConfig, namespaces: set[str] | None = None) -> BuildManifest:
    inventory = build_inventory(config)
    write_inventory(config)
    existing_manifest = _load_existing_build_manifest(config)
    merged_meta: dict[str, BuildNamespaceMeta] = {
        item.namespace: item for item in (existing_manifest.namespaces if existing_manifest else [])
    }

    descriptors = collect_document_descriptors(config, include_readmes=False)
    if namespaces:
        descriptors = [descriptor for descriptor in descriptors if descriptor.namespace in namespaces]

    grouped: dict[str, list] = defaultdict(list)
    for descriptor in descriptors:
        grouped[descriptor.namespace].append(descriptor)

    client = OllamaClient(config)
    await client.ensure_models_available([config.embed_model])
    for namespace_item in inventory:
        if namespaces and namespace_item.namespace not in namespaces:
            continue
        descriptors_for_namespace = grouped.get(namespace_item.namespace, [])
        documents = [normalize_descriptor(descriptor) for descriptor in descriptors_for_namespace]
        chunks = chunk_documents(documents)
        print(
            f"[build] namespace={namespace_item.namespace} documents={len(documents)} chunks={len(chunks)}",
            flush=True,
        )
        if chunks:
            chunk_path = _chunk_path(config, namespace_item.namespace)
            write_chunks(chunk_path, chunks)
            build_sparse_index(chunks, _sparse_path(config, namespace_item.namespace))
            await build_dense_index(
                chunks,
                _dense_vector_path(config, namespace_item.namespace),
                _dense_meta_path(config, namespace_item.namespace),
                client,
            )
        else:
            _clear_namespace_artifacts(config, namespace_item.namespace)
        merged_meta[namespace_item.namespace] = (
            BuildNamespaceMeta(
                namespace=namespace_item.namespace,
                documents=len(documents),
                chunks=len(chunks),
                ready=bool(chunks),
                primary=namespace_item.primary,
                experimental=namespace_item.experimental,
            )
        )

    manifest = BuildManifest(
        generatedAt=now_iso(),
        embeddingModel=config.embed_model,
        namespaces=sorted(merged_meta.values(), key=lambda item: item.namespace),
    )
    config.build_root.mkdir(parents=True, exist_ok=True)
    _build_manifest_path(config).write_text(json.dumps(manifest.model_dump(), indent=2, ensure_ascii=True), encoding="utf-8")

    global _RUNTIME
    _RUNTIME = None
    return manifest


async def runtime_status() -> dict[str, Any]:
    config = load_config()
    manifest = _load_existing_build_manifest(config)
    required_namespaces = [namespace for namespace in config.primary_languages if namespace in config.supported_languages]
    if not required_namespaces:
        required_namespaces = list(dict.fromkeys(config.supported_languages))
    status: dict[str, Any] = {
        "enabled": True,
        "ready": False,
        "buildRoot": str(config.build_root),
        "embeddingModel": config.embed_model,
        "generationModel": config.generation_model,
        "requiredNamespaces": required_namespaces,
        "builtNamespaces": [],
        "missingArtifacts": [],
        "message": None,
    }

    if manifest is None:
        status["message"] = (
            "RAG build artifacts are missing. Run `npm --prefix backend run rag:build` before using the backend."
        )
        return status

    meta_by_namespace = {item.namespace: item for item in manifest.namespaces}
    status["builtNamespaces"] = sorted(meta_by_namespace.keys())
    missing_artifacts: list[str] = []
    for namespace in required_namespaces:
        meta = meta_by_namespace.get(namespace)
        if meta is None or not meta.ready:
            missing_artifacts.append(namespace)
            continue
        required_paths = (
            _chunk_path(config, namespace),
            _sparse_path(config, namespace),
            _dense_vector_path(config, namespace),
            _dense_meta_path(config, namespace),
        )
        if any(not path.exists() for path in required_paths):
            missing_artifacts.append(namespace)
    status["missingArtifacts"] = missing_artifacts

    client = OllamaClient(config)
    try:
        await client.ensure_models_available([config.embed_model, config.generation_model])
    except OllamaError as error:
        status["message"] = str(error)
        return status

    if missing_artifacts:
        status["message"] = (
            "Missing build artifacts for namespaces: "
            + ", ".join(missing_artifacts)
            + ". Run `npm --prefix backend run rag:build`."
        )
        return status

    status["ready"] = True
    status["message"] = "RAG runtime ready"
    return status


async def analyze_request(raw_request: dict) -> dict:
    config = load_config()
    request = RagRequest.model_validate(raw_request)
    runtime = _load_runtime(config)
    await runtime.client.ensure_models_available([config.embed_model, config.generation_model])
    requested_scope = {scope for scope in request.scope if scope in {"security", "bugs", "style", "performance"}}
    if not config.enable_security and "security" in requested_scope:
        requested_scope.remove("security")
    if not config.enable_performance and "performance" in requested_scope:
        requested_scope.remove("performance")
    if not requested_scope:
        return RagResponse(suggestions=[], partialFailures=0).model_dump()

    ranked_items = []
    candidate_buffer_by_file: dict[str, int] = defaultdict(int)
    partial_failures = 0
    for file in request.files:
        language_slug = to_slug(file.language)
        if not language_slug or language_slug not in config.supported_languages:
            partial_failures += 1
            continue
        if not runtime.has_namespace(language_slug):
            partial_failures += 1
            continue
        if not file.patch.strip():
            continue

        file_failed = False
        tasks = select_hunks(file, config.max_hunks_per_file)
        for task in tasks:
            for category in request.scope:
                if category not in requested_scope:
                    continue
                if candidate_buffer_by_file[file.path] >= request.limits.maxPerFile * 2:
                    break
                namespaces = [language_slug]
                if category == "security" and config.enable_security and runtime.has_namespace("security-pack"):
                    namespaces.append("security-pack")
                query_text = build_query(task, category)
                try:
                    query_vector = np.asarray((await runtime.client.embed_texts([query_text]))[0], dtype=np.float32)
                    hits = runtime.retriever.search(namespaces, query_text, query_vector, top_k=config.default_topk)
                    if len(hits) < 2:
                        continue
                    envelope = await runtime.generator.generate(task, category, hits)
                    score_by_chunk = {hit.chunkId: hit.finalScore for hit in hits}
                    accepted_any = False
                    for candidate in envelope.suggestions:
                        candidate = candidate.model_copy(update={"filePath": task.filePath, "category": category})
                        validation = runtime.validator.validate(candidate, task, requested_scope)
                        if not validation.valid:
                            continue
                        citations = runtime.citation_resolver.resolve(candidate.evidenceChunkIds)
                        if not citations:
                            continue
                        retrieval_scores = [score_by_chunk.get(chunk_id, 0.0) for chunk_id in candidate.evidenceChunkIds]
                        retrieval_score = sum(retrieval_scores) / len(retrieval_scores) if retrieval_scores else 0.0
                        suggestion = BackendSuggestion(
                            filePath=task.filePath,
                            lineStart=validation.lineStart or task.firstChangedLine,
                            lineEnd=validation.lineEnd or validation.lineStart or task.firstChangedLine,
                            severity=candidate.severity,
                            category=category,
                            title=candidate.title.strip(),
                            body=candidate.body.strip(),
                            citations=citations,
                            confidence=candidate.confidence,
                            fingerprint="",
                        )
                        suggestion = suggestion.model_copy(update={"fingerprint": fingerprint_for_suggestion(suggestion)})
                        ranked_items.append(build_ranked_suggestion(suggestion, retrieval_score))
                        candidate_buffer_by_file[file.path] += 1
                        accepted_any = True
                    if not accepted_any and category == "style":
                        for candidate in style_fallback_candidates(task, hits):
                            validation = runtime.validator.validate(candidate, task, requested_scope)
                            if not validation.valid:
                                continue
                            citations = runtime.citation_resolver.resolve(candidate.evidenceChunkIds)
                            if not citations:
                                continue
                            retrieval_scores = [score_by_chunk.get(chunk_id, 0.0) for chunk_id in candidate.evidenceChunkIds]
                            retrieval_score = sum(retrieval_scores) / len(retrieval_scores) if retrieval_scores else 0.0
                            suggestion = BackendSuggestion(
                                filePath=task.filePath,
                                lineStart=validation.lineStart or task.firstChangedLine,
                                lineEnd=validation.lineEnd or validation.lineStart or task.firstChangedLine,
                                severity=candidate.severity,
                                category=category,
                                title=candidate.title.strip(),
                                body=candidate.body.strip(),
                                citations=citations,
                                confidence=candidate.confidence,
                                fingerprint="",
                            )
                            suggestion = suggestion.model_copy(update={"fingerprint": fingerprint_for_suggestion(suggestion)})
                            ranked_items.append(build_ranked_suggestion(suggestion, retrieval_score))
                            candidate_buffer_by_file[file.path] += 1
                except Exception:
                    file_failed = True
                    continue
        if file_failed:
            partial_failures += 1

    suggestions = dedupe_and_rank(ranked_items, request.limits.maxComments, request.limits.maxPerFile)
    response = RagResponse(suggestions=suggestions, partialFailures=partial_failures)
    return response.model_dump()
