from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
RAG_SRC = REPO_ROOT / "rag-ml" / "src"
if str(RAG_SRC) not in sys.path:
    sys.path.insert(0, str(RAG_SRC))

from rag_ml.config import RagConfig
from rag_ml.evidence_models import code_ref
from rag_ml.hotspot_planner import plan_hotspot_tasks
from rag_ml.schemas import (
    BackendSuggestion,
    CandidateFinding,
    CandidateFindingEnvelope,
    Evidence,
    PROverview,
    PROverviewHotspot,
    RagRequest,
    RagFile,
    RetrievalHit,
    StaticChecksResult,
    ValidationResult,
)
from rag_ml.service import analyze_request
from rag_ml.static_signals import collect_static_signals
from rag_ml.synthesizer import synthesize_suggestions
from rag_ml.validator import SuggestionValidator


class _FakeClient:
    async def ensure_models_available(self, models):
        return None

    async def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def chat_structured(self, messages, schema, **kwargs):
        return {
            "prIntent": "Refactor auth flow",
            "riskLevel": "medium",
            "recommendedScopes": ["style", "bugs"],
            "hotspots": [{"filePath": "lib/example.dart", "reasons": ["async flow changed"], "risk": 0.8}],
            "notes": ["Touches async flow"],
        }


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
            )
        ]


class _FakeGenerator:
    async def generate(self, task, categories, context_pack, **kwargs):
        return CandidateFindingEnvelope(suggestions=[])


class _FakeCitationResolver:
    def resolve(self, evidence_refs, context_pack):
        return (
            [
                Evidence(
                    evidenceId=context_pack.codeEvidenceCandidates[0].refId,
                    type="code",
                    title="Changed hunk",
                    snippet=context_pack.codeEvidenceCandidates[0].snippet,
                    filePath=context_pack.codeEvidenceCandidates[0].filePath,
                    lineStart=context_pack.codeEvidenceCandidates[0].lineStart,
                    lineEnd=context_pack.codeEvidenceCandidates[0].lineEnd,
                )
            ],
            [],
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

    def has_namespace(self, namespace: str) -> bool:
        return namespace == "dart"


class RagPipelineV2Tests(unittest.IsolatedAsyncioTestCase):
    def test_validator_accepts_code_only_evidence(self) -> None:
        task = plan_hotspot_tasks(
            RagRequest(
                jobId="job_1",
                snapshotId="snap_1",
                prId="pr_1",
                title="Improve async flow",
                scope=["bugs"],
                files=[
                    RagFile(
                        path="lib/example.dart",
                        language="Dart",
                        patch="@@ -1 +1 @@\n+final responseData = await client.fetch();",
                        surroundingCode=[{"lineNumber": 1, "text": "final responseData = await client.fetch();"}],
                    )
                ],
                limits={"maxComments": 5, "maxPerFile": 3},
            ),
            PROverview(
                prIntent="Improve async flow",
                riskLevel="medium",
                recommendedScopes=["bugs"],
                hotspots=[PROverviewHotspot(filePath="lib/example.dart", reasons=["async flow changed"], risk=0.8)],
                notes=[],
            ),
            StaticChecksResult(signals=[], toolFindings=[]),
            max_hunks_per_file=1,
            max_hotspot_tasks=4,
        )[0]

        candidate_result = SuggestionValidator().validate(
            candidate=CandidateFinding(
                filePath=task.filePath,
                category="bugs",
                severity="medium",
                title="Missing async result guard",
                body="responseData is used directly after the async call without an explicit guard.",
                confidence=0.8,
                evidenceRefs=[code_ref(task.taskId, 0)],
                lineStart=task.firstChangedLine,
                lineEnd=task.firstChangedLine,
            ),
            task=task,
            requested_scope={"bugs"},
        )
        self.assertTrue(candidate_result.valid)

    def test_synthesizer_marks_low_confidence_items_as_summary(self) -> None:
        inline_candidate = BackendSuggestion(
            filePath="lib/example.dart",
            lineStart=10,
            lineEnd=10,
            severity="medium",
            category="bugs",
            title="Missing guard",
            body="The async result is dereferenced without a guard.",
            confidence=0.81,
            fingerprint="inline",
            evidence=[
                Evidence(
                    evidenceId="code:1",
                    type="code",
                    title="Changed hunk",
                    snippet="final token = response.data.token;",
                    filePath="lib/example.dart",
                    lineStart=10,
                    lineEnd=10,
                )
            ],
        )
        summary_candidate = inline_candidate.model_copy(
            update={"confidence": 0.62, "fingerprint": "summary"}
        )

        result = synthesize_suggestions([inline_candidate, summary_candidate])
        by_id = {item.fingerprint: item for item in result}
        self.assertEqual(by_id["inline"].deliveryMode, "inline")
        self.assertEqual(by_id["summary"].deliveryMode, "summary")

    def test_hotspot_planner_respects_file_and_global_limits(self) -> None:
        request = RagRequest(
            jobId="job_1",
            snapshotId="snap_1",
            prId="pr_1",
            title="Large refactor",
            scope=["style", "bugs"],
            files=[
                RagFile(
                    path="lib/a.dart",
                    language="Dart",
                    patch="@@ -1 +1 @@\n+final bad_name = 1;\n@@ -10 +10 @@\n+await client.fetch();\n@@ -20 +20 @@\n+final other_value = 2;",
                ),
                RagFile(
                    path="lib/b.dart",
                    language="Dart",
                    patch="@@ -1 +1 @@\n+final another_bad_name = 1;",
                ),
            ],
            limits={"maxComments": 10, "maxPerFile": 3},
        )
        overview = PROverview(
            prIntent="Large refactor",
            riskLevel="medium",
            recommendedScopes=["style", "bugs"],
            hotspots=[PROverviewHotspot(filePath="lib/a.dart", reasons=["heuristic-risk"], risk=0.9)],
            notes=[],
        )
        static_checks = collect_static_signals(request.files)

        planned = plan_hotspot_tasks(
            request,
            overview,
            static_checks,
            max_hunks_per_file=2,
            max_hotspot_tasks=2,
        )

        self.assertLessEqual(len(planned), 2)
        self.assertLessEqual(len([item for item in planned if item.filePath == "lib/a.dart"]), 2)

    async def test_analyze_request_progress_counts_unique_files(self) -> None:
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
                    "patch": "@@ -1 +1 @@\n+final Bad_name = 1;\n@@ -10 +10 @@\n+final Other_name = 2;",
                    "hunks": [],
                    "lineMap": [],
                    "surroundingCode": [{"lineNumber": 1, "text": "final Bad_name = 1;"}],
                }
            ],
            "limits": {"maxComments": 5, "maxPerFile": 3},
        }
        progress_updates: list[dict[str, object]] = []

        async def on_progress(update):
            progress_updates.append(update)

        with patch("rag_ml.service.load_config", return_value=config), patch("rag_ml.service._load_runtime", return_value=_FakeRuntime()):
            await analyze_request(request, on_progress)

        review_updates = [item for item in progress_updates if item["stage"] == "review"]
        self.assertTrue(review_updates)
        self.assertLessEqual(max(int(item.get("filesDone", 0)) for item in review_updates), 1)


if __name__ == "__main__":
    unittest.main()
