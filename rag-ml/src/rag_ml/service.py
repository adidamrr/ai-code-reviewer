from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from inspect import isawaitable
from pathlib import Path
from typing import Any, Awaitable, Callable

import numpy as np

from .bug_rules import rule_based_bug_candidates
from .citation_resolver import CitationResolver
from .config import RagConfig, load_config
from .context_builder import build_context_pack
from .dense_index import build_dense_index, load_dense_index
from .hotspot_planner import plan_hotspot_tasks
from .pr_overview import build_pr_overview
from .generator import SuggestionGenerator
from .hybrid_retriever import HybridRetriever
from .kb_chunker import chunk_documents
from .kb_inventory import build_inventory, write_inventory
from .kb_loader import collect_document_descriptors
from .kb_normalizer import normalize_descriptor
from .ollama_client import OllamaClient, OllamaError
from .query_builder import build_query
from .ranking import build_ranked_suggestion, dedupe_and_rank, fingerprint_for_suggestion
from .schemas import (
    BackendSuggestion,
    BuildManifest,
    BuildNamespaceMeta,
    ContextPack,
    CandidateFinding,
    HunkTask,
    KnowledgeChunk,
    ProgressUpdate,
    RagRequest,
    RagResponse,
)
from .sparse_index import build_sparse_index, load_sparse_index
from .static_signals import collect_static_signals
from .style_rules import rule_based_style_candidates
from .synthesizer import synthesize_suggestions
from .validator import SuggestionValidator
from .verifier import FindingVerifier


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


def _merge_hits(hit_groups: list[list], *, top_k: int) -> list:
    best_by_chunk: dict[str, Any] = {}
    for hits in hit_groups:
        for hit in hits:
            current = best_by_chunk.get(hit.chunkId)
            if current is None or hit.finalScore > current.finalScore:
                best_by_chunk[hit.chunkId] = hit
    return sorted(best_by_chunk.values(), key=lambda item: item.finalScore, reverse=True)[:top_k]


async def _emit_progress(
    callback: Callable[[dict[str, Any]], Any] | None,
    update: ProgressUpdate,
) -> None:
    if callback is None:
        return
    result = callback(update.model_dump())
    if isawaitable(result):
        await result


def _effective_scope(config: RagConfig, request: RagRequest) -> set[str]:
    requested_scope = {scope for scope in request.scope if scope in {"security", "bugs", "style", "performance"}}
    if not config.enable_security and "security" in requested_scope:
        requested_scope.remove("security")
    if not config.enable_performance and "performance" in requested_scope:
        requested_scope.remove("performance")
    return requested_scope


def _static_signals_for_task(static_checks, task: HunkTask) -> list:
    return [
        signal
        for signal in [*static_checks.signals, *static_checks.toolFindings]
        if signal.filePath == task.filePath
    ]


def _doc_retrieval_score(score_by_chunk: dict[str, float], evidence_refs: list[str]) -> float:
    retrieval_scores = [
        score_by_chunk.get(ref.split(":", 1)[1], 0.0)
        for ref in evidence_refs
        if ref.startswith("doc:")
    ]
    if not retrieval_scores:
        return 0.0
    return sum(retrieval_scores) / len(retrieval_scores)


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
        self.verifier = FindingVerifier()

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
        "repairModel": config.repair_model,
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
        required_models = [config.embed_model, config.generation_model]
        if config.repair_model and config.repair_model not in required_models:
            required_models.append(config.repair_model)
        await client.ensure_models_available(required_models)
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


async def analyze_request(
    raw_request: dict,
    progress_callback: Callable[[dict[str, Any]], Any] | None = None,
) -> dict:
    config = load_config()
    request = RagRequest.model_validate(raw_request)
    runtime = _load_runtime(config)
    required_models = [config.embed_model, config.generation_model]
    if config.repair_model and config.repair_model not in required_models:
        required_models.append(config.repair_model)
    await runtime.client.ensure_models_available(required_models)
    requested_scope = _effective_scope(config, request)
    if not requested_scope:
        return RagResponse(suggestions=[], partialFailures=0, meta={}).model_dump()

    await _emit_progress(
        progress_callback,
        ProgressUpdate(
            stage="overview",
            message="Стартовал этап обзора pull request.",
            stageDone=0,
            stageTotal=1,
            filesDone=0,
            filesTotal=len(request.files),
        ),
    )
    overview = await build_pr_overview(runtime.client, request)
    await _emit_progress(
        progress_callback,
        ProgressUpdate(
            stage="overview",
            message="Обзор pull request завершен.",
            stageDone=1,
            stageTotal=1,
            filesDone=0,
            filesTotal=len(request.files),
            meta={
                "riskLevel": overview.riskLevel,
                "hotspots": [item.model_dump() for item in overview.hotspots],
                "recommendedScopes": overview.recommendedScopes,
            },
        ),
    )

    await _emit_progress(
        progress_callback,
        ProgressUpdate(
            stage="static",
            message="Запущен статический этап анализа.",
            stageDone=0,
            stageTotal=1,
            filesDone=0,
            filesTotal=len(request.files),
        ),
    )
    static_checks = collect_static_signals(request.files)
    await _emit_progress(
        progress_callback,
        ProgressUpdate(
            stage="static",
            message="Статический этап анализа завершен.",
            stageDone=1,
            stageTotal=1,
            filesDone=0,
            filesTotal=len(request.files),
            meta={"signals": [item.model_dump() for item in static_checks.signals]},
        ),
    )

    await _emit_progress(
        progress_callback,
        ProgressUpdate(
            stage="planning",
            message="Планирование hotspot-задач начато.",
            stageDone=0,
            stageTotal=1,
            filesDone=0,
            filesTotal=len(request.files),
        ),
    )
    planned_tasks = plan_hotspot_tasks(
        request,
        overview,
        static_checks,
        max_hunks_per_file=config.max_hunks_per_file,
        max_hotspot_tasks=config.max_hotspot_tasks,
    )
    await _emit_progress(
        progress_callback,
        ProgressUpdate(
            stage="planning",
            message="Hotspot-план построен.",
            stageDone=1,
            stageTotal=1,
            filesDone=0,
            filesTotal=len(request.files),
            meta={
                "taskCount": len(planned_tasks),
                "tasks": [
                    {
                        "taskId": task.taskId,
                        "filePath": task.filePath,
                        "categories": task.categories,
                        "priority": task.priority,
                        "reasons": task.reasons,
                    }
                    for task in planned_tasks
                ],
            },
        ),
    )

    ranked_items = []
    task_debug: list[dict[str, Any]] = []
    candidate_buffer_by_file: dict[str, int] = defaultdict(int)
    partial_failures = 0
    files_done = 0
    total_files = len({task.filePath for task in planned_tasks}) or len(request.files)
    task_count_by_file: dict[str, int] = defaultdict(int)
    completed_task_count_by_file: dict[str, int] = defaultdict(int)
    completed_files: set[str] = set()
    for task in planned_tasks:
        task_count_by_file[task.filePath] += 1

    def mark_task_complete(file_path: str) -> int:
        nonlocal files_done
        completed_task_count_by_file[file_path] += 1
        if (
            file_path not in completed_files
            and completed_task_count_by_file[file_path] >= task_count_by_file.get(file_path, 1)
        ):
            completed_files.add(file_path)
            files_done += 1
        return files_done

    def append_ranked_candidate(
        candidate: CandidateFinding,
        *,
        task: HunkTask,
        context_pack: ContextPack,
        score_by_chunk: dict[str, float],
        signals: list[Any],
        stage_origin: str,
    ) -> bool:
        verification = runtime.verifier.verify(candidate, task, requested_scope, context_pack)
        if not verification.valid:
            return False
        candidate = candidate.model_copy(
            update={
                "lineStart": verification.lineStart or candidate.lineStart,
                "lineEnd": verification.lineEnd or candidate.lineEnd,
            }
        )
        final_validation = runtime.validator.validate(candidate, task, requested_scope)
        if not final_validation.valid:
            return False
        evidence, citations = runtime.citation_resolver.resolve(candidate.evidenceRefs, context_pack)
        if not evidence:
            return False
        retrieval_score = _doc_retrieval_score(score_by_chunk, candidate.evidenceRefs)
        suggestion = BackendSuggestion(
            filePath=task.filePath,
            lineStart=final_validation.lineStart or task.firstChangedLine,
            lineEnd=final_validation.lineEnd or final_validation.lineStart or task.firstChangedLine,
            severity=candidate.severity,
            category=candidate.category,
            title=candidate.title.strip(),
            body=candidate.body.strip(),
            evidence=evidence,
            citations=citations,
            confidence=candidate.confidence,
            fingerprint="",
            meta={
                "stageOrigin": stage_origin,
                "taskId": task.taskId,
                "fileClass": task.fileClass,
                "language": task.languageSlug,
                "fileRole": task.fileClass,
                "promptContextVersion": "rag-v2",
            },
        )
        suggestion = suggestion.model_copy(update={"fingerprint": fingerprint_for_suggestion(suggestion)})
        ranked_items.append(
            build_ranked_suggestion(
                suggestion,
                retrieval_score=retrieval_score,
                planner_priority=task.priority,
                static_support=min(1.0, len(signals) / 3.0),
                repo_feedback_score=0.0,
            )
        )
        candidate_buffer_by_file[task.filePath] += 1
        return True

    for task_index, task in enumerate(planned_tasks, start=1):
        if candidate_buffer_by_file[task.filePath] >= request.limits.maxPerFile * 2:
            continue
        await _emit_progress(
            progress_callback,
            ProgressUpdate(
                stage="review",
                message="Начат анализ hotspot-задачи.",
                filePath=task.filePath,
                stageDone=task_index - 1,
                stageTotal=len(planned_tasks),
                filesDone=files_done,
                filesTotal=total_files,
                meta={"taskId": task.taskId, "categories": task.categories},
            ),
        )
        try:
            debug = {
                "taskId": task.taskId,
                "filePath": task.filePath,
                "fileClass": task.fileClass,
                "categories": task.categories,
                "detected": 0,
                "accepted": 0,
                "ruleCandidates": 0,
                "modelOutlines": 0,
                "rejected": defaultdict(int),
            }
            if task.languageSlug not in config.supported_languages or not runtime.has_namespace(task.languageSlug):
                partial_failures += 1
                debug["rejected"]["unsupported_namespace"] += 1
                task_debug.append({**debug, "rejected": dict(debug["rejected"])})
                mark_task_complete(task.filePath)
                continue
            active_categories = [category for category in task.categories if category in requested_scope]
            if not active_categories:
                debug["rejected"]["category_not_requested"] += 1
                task_debug.append({**debug, "rejected": dict(debug["rejected"])})
                mark_task_complete(task.filePath)
                continue

            hits_by_category: dict[str, list[Any]] = {}
            for category in active_categories:
                namespaces = [task.languageSlug]
                if category == "security" and config.enable_security and runtime.has_namespace("security-pack"):
                    namespaces.append("security-pack")
                query_text = build_query(task, category)
                query_vector = np.asarray((await runtime.client.embed_texts([query_text]))[0], dtype=np.float32)
                hits = runtime.retriever.search(namespaces, query_text, query_vector, top_k=config.default_topk)
                if hits:
                    hits_by_category[category] = hits

            merged_hits = _merge_hits(list(hits_by_category.values()), top_k=config.default_topk) if hits_by_category else []
            signals = _static_signals_for_task(static_checks, task)
            context_pack: ContextPack = build_context_pack(task, signals, merged_hits)
            score_by_chunk = {hit.chunkId: hit.finalScore for hit in merged_hits}
            accepted_any = False
            deterministic_candidates: list[CandidateFinding] = []
            if "style" in active_categories:
                style_hits = hits_by_category.get("style", [])
                deterministic_candidates.extend(rule_based_style_candidates(task, style_hits))
            if any(category in active_categories for category in ("bugs", "security")):
                deterministic_candidates.extend(rule_based_bug_candidates(task, signals))
            debug["ruleCandidates"] = len(deterministic_candidates)

            for candidate in deterministic_candidates:
                debug["detected"] += 1
                if append_ranked_candidate(
                    candidate,
                    task=task,
                    context_pack=context_pack,
                    score_by_chunk=score_by_chunk,
                    signals=signals,
                    stage_origin="rules",
                ):
                    debug["accepted"] += 1
                    accepted_any = True
                else:
                    debug["rejected"]["rule_candidate_rejected"] += 1

            if candidate_buffer_by_file[task.filePath] < request.limits.maxPerFile * 2:
                max_suggestions = max(1, min(2, request.limits.maxPerFile * 2 - candidate_buffer_by_file[task.filePath]))
                try:
                    outlines = await runtime.generator.detect(
                        task,
                        active_categories,
                        context_pack,
                        max_findings=max_suggestions,
                    )
                except Exception as error:
                    debug["rejected"]["invalid_json"] += 1
                    outlines = None
                    if not accepted_any:
                        raise error

                if outlines is not None:
                    debug["modelOutlines"] = len(outlines.findings)
                    for outline in outlines.findings:
                        debug["detected"] += 1
                        provisional = CandidateFinding(
                            filePath=task.filePath,
                            lineStart=outline.lineStart,
                            lineEnd=outline.lineEnd,
                            severity=outline.severity,
                            category=outline.category,
                            title=outline.shortLabel.strip(),
                            body=outline.shortLabel.strip(),
                            confidence=outline.confidence,
                            evidenceRefs=outline.evidenceRefs,
                        )
                        verification = runtime.verifier.verify(provisional, task, requested_scope, context_pack)
                        if not verification.valid:
                            debug["rejected"][verification.reason or "verification_failed"] += 1
                            continue
                        explained = await runtime.generator.explain(task, outline, context_pack)
                        if append_ranked_candidate(
                            explained,
                            task=task,
                            context_pack=context_pack,
                            score_by_chunk=score_by_chunk,
                            signals=signals,
                            stage_origin="model",
                        ):
                            debug["accepted"] += 1
                            accepted_any = True
                        else:
                            debug["rejected"]["final_validation_failed"] += 1

            mark_task_complete(task.filePath)
            task_debug.append({**debug, "rejected": dict(debug["rejected"])})
            reject_summary = ", ".join(
                f"{key}={value}" for key, value in sorted(dict(debug["rejected"]).items()) if value
            ) or "none"
            await _emit_progress(
                progress_callback,
                ProgressUpdate(
                    stage="review",
                    message=(
                        "Hotspot-задача обработана. "
                        f"detected={debug['detected']} accepted={debug['accepted']} rejected={reject_summary}"
                    ),
                    filePath=task.filePath,
                    stageDone=task_index,
                    stageTotal=len(planned_tasks),
                    filesDone=files_done,
                    filesTotal=total_files,
                    meta={
                        "taskId": task.taskId,
                        "accepted": accepted_any,
                        "fileClass": task.fileClass,
                        "detected": debug["detected"],
                        "acceptedCount": debug["accepted"],
                        "rejectedReasons": dict(debug["rejected"]),
                    },
                ),
            )
        except Exception as error:
            partial_failures += 1
            mark_task_complete(task.filePath)
            await _emit_progress(
                progress_callback,
                ProgressUpdate(
                    stage="review",
                    level="error",
                    message=f"Ошибка анализа hotspot-задачи: {error}",
                    filePath=task.filePath,
                    stageDone=task_index,
                    stageTotal=len(planned_tasks),
                    filesDone=files_done,
                    filesTotal=total_files,
                    meta={"taskId": task.taskId},
                ),
            )

    await _emit_progress(
        progress_callback,
        ProgressUpdate(
            stage="synthesis",
            message="Синтез и ранжирование результатов.",
            stageDone=0,
            stageTotal=1,
            filesDone=files_done,
            filesTotal=total_files,
        ),
    )
    synthesized = synthesize_suggestions([item.suggestion for item in ranked_items])
    suggestion_by_fingerprint = {suggestion.fingerprint: suggestion for suggestion in synthesized}
    reranked_items = [
        item.model_copy(update={"suggestion": suggestion_by_fingerprint.get(item.suggestion.fingerprint, item.suggestion)})
        for item in ranked_items
    ]
    suggestions = dedupe_and_rank(reranked_items, request.limits.maxComments, request.limits.maxPerFile)
    await _emit_progress(
        progress_callback,
        ProgressUpdate(
            stage="ranking",
            message="Результаты готовы.",
            stageDone=1,
            stageTotal=1,
            filesDone=files_done,
            filesTotal=total_files,
            meta={"suggestions": len(suggestions), "partialFailures": partial_failures},
        ),
    )
    response = RagResponse(
        suggestions=suggestions,
        partialFailures=partial_failures,
        meta={
            "overview": overview.model_dump(),
            "taskCount": len(planned_tasks),
            "staticSignals": len(static_checks.signals),
            "taskDebug": task_debug,
        },
    )
    return response.model_dump()
