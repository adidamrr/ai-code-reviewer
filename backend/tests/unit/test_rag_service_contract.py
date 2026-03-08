from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
RAG_SRC = REPO_ROOT / "rag-ml" / "src"
if str(RAG_SRC) not in sys.path:
    sys.path.insert(0, str(RAG_SRC))

from rag_ml.config import RagConfig
from rag_ml.evidence_models import doc_ref
from rag_ml.schemas import (
    BuildManifest,
    BuildNamespaceMeta,
    CandidateFinding,
    ContextPack,
    ContextEvidenceCandidate,
    Evidence,
    FindingExplanation,
    FindingOutline,
    FindingOutlineEnvelope,
    RetrievalHit,
    ValidationResult,
)
from rag_ml.service import analyze_request, runtime_status
from rag_ml.verifier import FindingVerifier


class _FakeClient:
    async def ensure_models_available(self, models):
        return None

    async def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def chat_structured(self, messages, schema, **kwargs):
        if "PROverview" in str(schema):
            return {
                "prIntent": "Refactor auth flow",
                "riskLevel": "medium",
                "recommendedScopes": ["style", "bugs"],
                "hotspots": [{"filePath": "lib/example.dart", "reasons": ["heuristic-risk"], "risk": 0.8}],
                "notes": ["Touches auth flow"],
            }
        if "FindingOutlineEnvelope" in str(schema) or "\"findings\"" in str(schema):
            return {
                "findings": [
                    {
                        "filePath": "lib/example.dart",
                        "lineStart": 1,
                        "lineEnd": 1,
                        "severity": "low",
                        "category": "style",
                        "shortLabel": "use lowerCamelCase for constants",
                        "confidence": 0.82,
                        "evidenceRefs": [
                            "doc:dart:effective-dart:000001",
                            "code:lib/example.dart:0:0",
                        ],
                    }
                ]
            }
        return {"title": "Use lowerCamelCase for identifiers", "body": "This identifier naming does not follow Dart style guidance."}

    async def chat_text(self, messages, **kwargs):
        return "NO_FINDINGS"


class _FakeRetriever:
    def search(self, namespaces, query_text, query_vector, **kwargs):
        return [
            RetrievalHit(
                chunkId="dart:effective-dart:000001",
                namespace="dart",
                sourceId="effective-dart",
                title="Effective Dart",
                url="https://dart.dev/guides/language/effective-dart",
                headingPath=["Effective Dart", "Style"],
                text="Use lowerCamelCase for variables and function names.",
                finalScore=0.9,
                sparseRank=1,
                denseRank=1,
            ),
            RetrievalHit(
                chunkId="dart:dart-language-tour:000001",
                namespace="dart",
                sourceId="dart-language-tour",
                title="Dart language tour",
                url="https://dart.dev/guides/language/language-tour",
                headingPath=["Dart language tour"],
                text="Dart style guide favors consistent casing and naming.",
                finalScore=0.7,
                sparseRank=2,
                denseRank=2,
            ),
        ]


class _FakeGenerator:
    async def detect(self, task, categories, context_pack, **kwargs):
        category = categories[0]
        return FindingOutlineEnvelope(
            findings=[
                FindingOutline(
                    filePath=task.filePath,
                    lineStart=task.firstChangedLine,
                    lineEnd=task.firstChangedLine,
                    severity="low",
                    category=category,
                    shortLabel="use lowerCamelCase for constants",
                    confidence=0.82,
                    evidenceRefs=[doc_ref("dart:effective-dart:000001"), context_pack.codeEvidenceCandidates[0].refId],
                )
            ]
        )

    async def explain(self, task, outline, context_pack):
        return CandidateFinding(
            filePath=outline.filePath,
            lineStart=outline.lineStart,
            lineEnd=outline.lineEnd,
            severity=outline.severity,
            category=outline.category,
            title="Use lowerCamelCase for constants",
            body="This identifier naming does not follow Dart style guidance.",
            confidence=outline.confidence,
            evidenceRefs=outline.evidenceRefs,
        )


class _FakeCitationResolver:
    def resolve(self, evidence_refs, context_pack):
        return (
            [
                Evidence(
                    evidenceId=context_pack.codeEvidenceCandidates[0].refId,
                    type="code",
                    title="Changed hunk",
                    snippet="final My_var = 1;",
                    filePath="lib/example.dart",
                    lineStart=1,
                    lineEnd=1,
                ),
                Evidence(
                    evidenceId=doc_ref("dart:effective-dart:000001"),
                    type="doc",
                    title="Effective Dart",
                    snippet="Use lowerCamelCase for variables and function names.",
                    sourceId="effective-dart",
                    url="https://dart.dev/guides/language/effective-dart",
                ),
            ],
            [
                {
                    "sourceId": "effective-dart",
                    "title": "Effective Dart",
                    "url": "https://dart.dev/guides/language/effective-dart",
                    "snippet": "Use lowerCamelCase for variables and function names.",
                }
            ],
        )


class _FakeValidator:
    def validate(self, candidate, task, scope):
        return ValidationResult(valid=True, lineStart=task.firstChangedLine, lineEnd=task.firstChangedLine)


class _FakeRuntime:
    def __init__(self):
        self.client = _FakeClient()
        self.retriever = _FakeRetriever()
        self.generator = _FakeGenerator()
        self.citation_resolver = _FakeCitationResolver()
        self.validator = _FakeValidator()
        self.verifier = FindingVerifier()

    def has_namespace(self, namespace: str) -> bool:
        return namespace == "dart"


class RagServiceContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_request_returns_backend_contract(self) -> None:
        config = RagConfig(
            repo_root=REPO_ROOT,
            rag_root=REPO_ROOT / "rag-ml",
            kb_root=REPO_ROOT / "rag-ml" / "kb",
            build_root=REPO_ROOT / "rag-ml" / "build",
            ollama_base_url="http://127.0.0.1:11434",
            generation_model="qwen2.5-coder:7b",
            eval_generation_model="qwen2.5-coder:14b",
            embed_model="nomic-embed-text",
            supported_languages=("dart",),
            primary_languages=("dart",),
            experimental_languages=(),
            enable_security=False,
            enable_performance=True,
            default_topk=6,
            max_hunks_per_file=2,
            max_hotspot_tasks=8,
            embed_batch_size=64,
            generation_max_tokens=256,
            ollama_timeout_seconds=30.0,
            repair_model="gemma3:12b",
        )
        request = {
            "jobId": "job_1",
            "prId": "pr_1",
            "snapshotId": "snap_1",
            "title": "Refactor auth flow",
            "scope": ["style"],
            "files": [
                {
                    "path": "lib/example.dart",
                    "language": "Dart",
                    "patch": "@@ -1 +1 @@\n+final My_var = 1;",
                    "hunks": [],
                    "lineMap": [],
                    "surroundingCode": [{"lineNumber": 1, "text": "final My_var = 1;"}],
                }
            ],
            "limits": {"maxComments": 5, "maxPerFile": 3},
        }

        with patch("rag_ml.service.load_config", return_value=config), patch("rag_ml.service._load_runtime", return_value=_FakeRuntime()):
            result = await analyze_request(request)

        self.assertEqual(result["partialFailures"], 0)
        self.assertGreaterEqual(len(result["suggestions"]), 1)
        suggestion = result["suggestions"][0]
        self.assertEqual(suggestion["filePath"], "lib/example.dart")
        self.assertEqual(suggestion["category"], "style")
        self.assertTrue(any(item["sourceId"] == "effective-dart" for item in suggestion["citations"]))
        self.assertGreaterEqual(len(suggestion["evidence"]), 1)
        self.assertTrue(suggestion["fingerprint"])

    async def test_runtime_status_reports_missing_primary_artifacts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            build_root = Path(tmpdir)
            (build_root / "chunks").mkdir(parents=True, exist_ok=True)
            (build_root / "sparse").mkdir(parents=True, exist_ok=True)
            (build_root / "dense").mkdir(parents=True, exist_ok=True)
            (build_root / "build-manifest.json").write_text(
                BuildManifest(
                    generatedAt="2026-01-01T00:00:00Z",
                    embeddingModel="nomic-embed-text",
                    namespaces=[
                        BuildNamespaceMeta(namespace="dart", documents=1, chunks=2, ready=True, primary=True),
                    ],
                ).model_dump_json(indent=2),
                encoding="utf-8",
            )
            for relative in (
                "chunks/dart.chunks.jsonl",
                "sparse/dart.bm25.pkl",
                "dense/dart.vectors.npy",
                "dense/dart.meta.jsonl",
            ):
                (build_root / relative).write_text("ok", encoding="utf-8")

            config = RagConfig(
                repo_root=REPO_ROOT,
                rag_root=REPO_ROOT / "rag-ml",
                kb_root=REPO_ROOT / "rag-ml" / "kb",
                build_root=build_root,
                ollama_base_url="http://127.0.0.1:11434",
                generation_model="qwen2.5-coder:7b",
                eval_generation_model="qwen2.5-coder:14b",
                embed_model="nomic-embed-text",
                supported_languages=("dart", "python"),
                primary_languages=("dart", "python"),
                experimental_languages=(),
                enable_security=False,
                enable_performance=True,
                default_topk=6,
                max_hunks_per_file=2,
                max_hotspot_tasks=8,
                embed_batch_size=64,
                generation_max_tokens=256,
                ollama_timeout_seconds=30.0,
            )

            with patch("rag_ml.service.load_config", return_value=config), patch("rag_ml.service.OllamaClient", return_value=_FakeClient()):
                result = await runtime_status()

        self.assertFalse(result["ready"])
        self.assertIn("python", result["missingArtifacts"])
        self.assertIn("dart", result["builtNamespaces"])


if __name__ == "__main__":
    unittest.main()
