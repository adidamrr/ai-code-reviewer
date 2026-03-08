from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
RAG_SRC = REPO_ROOT / "rag-ml" / "src"
if str(RAG_SRC) not in sys.path:
    sys.path.insert(0, str(RAG_SRC))

from rag_ml.citation_resolver import CitationResolver
from rag_ml.kb_chunker import chunk_documents
from rag_ml.kb_normalizer import normalize_descriptor
from rag_ml.language_mapper import to_slug
from rag_ml.query_builder import build_query
from rag_ml.rule_fallbacks import style_fallback_candidates
from rag_ml.schemas import CandidateSuggestion, DocumentDescriptor, HunkTask, KnowledgeChunk, NormalizedDocument, RetrievalHit, SectionSpan
from rag_ml.validator import SuggestionValidator


class RagRuntimeTests(unittest.TestCase):
    def test_language_mapper_maps_supported_display_names(self) -> None:
        self.assertEqual(to_slug("Python"), "python")
        self.assertEqual(to_slug("Dart"), "dart")
        self.assertEqual(to_slug("Swift"), "swift")
        self.assertEqual(to_slug("C++"), "cpp")
        self.assertEqual(to_slug("JavaScript"), "javascript")

    def test_chunker_preserves_metadata_and_size(self) -> None:
        document = NormalizedDocument(
            documentId="dart:effective-dart:sample",
            namespace="dart",
            language="dart",
            sourceId="effective-dart",
            sourceTitle="Effective Dart",
            sourceUrl="https://dart.dev/guides/language/effective-dart",
            docPath="/tmp/effective-dart.txt",
            text=("Style section\n\n" + ("lowerCamelCase is recommended. " * 200)),
            sections=[SectionSpan(headingPath=["Effective Dart", "Style"], charStart=0, charEnd=len("Style section\n\n" + ("lowerCamelCase is recommended. " * 200)))],
        )
        chunks = chunk_documents([document])
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].sourceId, "effective-dart")
        self.assertEqual(chunks[0].sourceUrl, "https://dart.dev/guides/language/effective-dart")
        self.assertLessEqual(max(len(chunk.text) for chunk in chunks), 2200)
        self.assertLess(len(chunks), 10)

    def test_citation_resolver_uses_real_chunk_text(self) -> None:
        chunk = KnowledgeChunk(
            chunkId="dart:effective-dart:000001",
            namespace="dart",
            language="dart",
            sourceId="effective-dart",
            sourceTitle="Effective Dart",
            sourceUrl="https://dart.dev/guides/language/effective-dart",
            docPath="/tmp/effective-dart.txt",
            headingPath=["Effective Dart", "Style"],
            text="Use lowerCamelCase for variables and function names to preserve consistency across Dart codebases.",
            charStart=0,
            charEnd=96,
            tokenEstimate=24,
        )
        citations = CitationResolver({chunk.chunkId: chunk}).resolve([chunk.chunkId])
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].sourceId, "effective-dart")
        self.assertIn("lowerCamelCase", citations[0].snippet)

    def test_validator_rejects_missing_evidence(self) -> None:
        candidate = CandidateSuggestion(
            filePath="lib/example.dart",
            lineStart=10,
            lineEnd=10,
            severity="low",
            category="style",
            title="Use lowerCamelCase",
            body="Rename the symbol to lowerCamelCase for consistency.",
            confidence=0.8,
            evidenceChunkIds=[],
        )
        from rag_ml.schemas import HunkTask

        task = HunkTask(
            filePath="lib/example.dart",
            language="Dart",
            languageSlug="dart",
            patch="@@ -1 +1 @@\n+final My_var = 1;",
            hunkHeader="",
            hunkPatch="@@ -1 +1 @@\n+final My_var = 1;",
            addedLines=["final My_var = 1;"],
            changedNewLines=[1],
            firstChangedLine=1,
            priority=1.0,
        )
        result = SuggestionValidator().validate(candidate, task, {"style"})
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "missing_evidence")

    def test_txt_normalizer_prefers_rst_headings_over_plain_paragraph_lines(self) -> None:
        sample = "\n".join(
            [
                "9. Classes",
                "**********",
                "",
                "Classes provide a means of bundling data and functionality together.",
                "Creating a new class creates a new type of object.",
                "",
                "9.1. A Word About Names and Objects",
                "===================================",
                "",
                "Objects can contain arbitrary amounts and kinds of data.",
                "",
            ]
        )
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "classes.txt"
            path.write_text(sample, encoding="utf-8")
            document = normalize_descriptor(
                DocumentDescriptor(
                    namespace="python",
                    language="python",
                    displayName="Python",
                    sourceId="python-docs",
                    sourceTitle="Python Tutorial",
                    sourceUrl="https://docs.python.org/3/tutorial/",
                    docPath=str(path),
                    isReadme=False,
                )
            )

        self.assertEqual(len(document.sections), 2)
        self.assertEqual(document.sections[0].headingPath, ["Python Tutorial", "9. Classes"])
        self.assertEqual(document.sections[1].headingPath, ["Python Tutorial", "9.1. A Word About Names and Objects"])

    def test_query_builder_adds_style_hints_for_bad_identifier_names(self) -> None:
        task = HunkTask(
            filePath="lib/example.dart",
            language="Dart",
            languageSlug="dart",
            patch="@@ -1 +1 @@\n+final My_value = 1;",
            hunkHeader="@@ -1 +1 @@",
            hunkPatch="@@ -1 +1 @@\n+final My_value = 1;",
            addedLines=["final My_value = 1;"],
            changedNewLines=[1],
            firstChangedLine=1,
            priority=1.0,
        )

        query = build_query(task, "style")
        self.assertIn("lowerCamelCase", query)
        self.assertIn("UpperCamelCase", query)

    def test_query_builder_adds_type_naming_hint_for_bad_class_name(self) -> None:
        task = HunkTask(
            filePath="lib/example.dart",
            language="Dart",
            languageSlug="dart",
            patch="@@ -0,0 +1 @@\n+class my_button {}",
            hunkHeader="@@ -0,0 +1 @@",
            hunkPatch="@@ -0,0 +1 @@\n+class my_button {}",
            addedLines=["class my_button {}"],
            changedNewLines=[1],
            firstChangedLine=1,
            priority=1.0,
        )

        query = build_query(task, "style")
        self.assertIn("UpperCamelCase", query)

    def test_validator_rejects_generic_documentation_summary(self) -> None:
        candidate = CandidateSuggestion(
            filePath="lib/example.dart",
            lineStart=1,
            lineEnd=1,
            severity="info",
            category="style",
            title="Dart language tour overview",
            body="This section provides an overview of the Dart programming language and its features.",
            confidence=1.0,
            evidenceChunkIds=["dart:effective-dart:000001"],
        )
        task = HunkTask(
            filePath="lib/example.dart",
            language="Dart",
            languageSlug="dart",
            patch="@@ -1 +1 @@\n+final My_value = 1;",
            hunkHeader="@@ -1 +1 @@",
            hunkPatch="@@ -1 +1 @@\n+final My_value = 1;",
            addedLines=["final My_value = 1;"],
            changedNewLines=[1],
            firstChangedLine=1,
            priority=1.0,
        )

        result = SuggestionValidator().validate(candidate, task, {"style"})
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "generic_feedback")

    def test_style_fallback_candidates_generate_grounded_dart_naming_comment(self) -> None:
        task = HunkTask(
            filePath="lib/example.dart",
            language="Dart",
            languageSlug="dart",
            patch="@@ -1 +1 @@\n+final My_value = 1;",
            hunkHeader="@@ -1 +1 @@",
            hunkPatch="@@ -1 +1 @@\n+final My_value = 1;",
            addedLines=["final My_value = 1;"],
            changedNewLines=[1],
            firstChangedLine=1,
            priority=1.0,
        )
        hits = [
            RetrievalHit(
                chunkId="dart:effective-dart:000005",
                namespace="dart",
                sourceId="effective-dart",
                title="Effective Dart",
                url="https://dart.dev/guides/language/effective-dart",
                headingPath=["Effective Dart"],
                text="DO name other identifiers using lowerCamelCase.",
                finalScore=0.9,
                sparseRank=1,
                denseRank=1,
            )
        ]

        candidates = style_fallback_candidates(task, hits)
        self.assertEqual(len(candidates), 1)
        self.assertIn("lowerCamelCase", candidates[0].body)
        self.assertEqual(candidates[0].evidenceChunkIds, ["dart:effective-dart:000005"])


if __name__ == "__main__":
    unittest.main()
