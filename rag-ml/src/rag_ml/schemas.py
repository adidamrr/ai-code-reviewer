from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RootLanguageEntry(Model):
    slug: str
    displayName: str
    path: str


class RootKbManifest(Model):
    version: int
    updatedAt: str
    languages: list[RootLanguageEntry]


class SourceManifest(Model):
    sourceId: str
    title: str
    url: str
    format: str | None = None
    license: str | None = None


class NamespaceManifest(Model):
    language: str | None = None
    namespace: str | None = None
    displayName: str
    defaultVersion: str | None = None
    docRoots: list[str] = Field(default_factory=lambda: ["docs"])
    sources: list[SourceManifest] = Field(default_factory=list)
    notes: str | None = None


class DocumentDescriptor(Model):
    namespace: str
    language: str | None = None
    displayName: str
    sourceId: str
    sourceTitle: str
    sourceUrl: str
    docPath: str
    isReadme: bool = False


class InventorySource(Model):
    sourceId: str
    title: str
    url: str
    documents: int
    chunkableDocuments: int


class NamespaceInventory(Model):
    namespace: str
    displayName: str
    language: str | None = None
    documents: int
    chunkableDocuments: int
    ready: bool
    primary: bool = False
    experimental: bool = False
    sources: list[InventorySource] = Field(default_factory=list)


class SectionSpan(Model):
    headingPath: list[str]
    charStart: int
    charEnd: int


class NormalizedDocument(Model):
    documentId: str
    namespace: str
    language: str | None = None
    sourceId: str
    sourceTitle: str
    sourceUrl: str
    docPath: str
    text: str
    sections: list[SectionSpan]


class KnowledgeChunk(Model):
    chunkId: str
    namespace: str
    language: str | None = None
    sourceId: str
    sourceTitle: str
    sourceUrl: str
    docPath: str
    headingPath: list[str]
    text: str
    charStart: int
    charEnd: int
    tokenEstimate: int


class BuildNamespaceMeta(Model):
    namespace: str
    documents: int
    chunks: int
    ready: bool
    primary: bool = False
    experimental: bool = False


class BuildManifest(Model):
    generatedAt: str
    embeddingModel: str
    namespaces: list[BuildNamespaceMeta]


class RagLineMapEntry(Model):
    patchLine: int
    oldLine: int | None = None
    newLine: int | None = None
    type: str


class RagHunk(Model):
    oldStart: int
    oldLines: int
    newStart: int
    newLines: int
    header: str | None = None


class RagFile(Model):
    path: str
    language: str
    patch: str
    hunks: list[RagHunk] | None = None
    lineMap: list[RagLineMapEntry] | None = None


class RagLimits(Model):
    maxComments: int = 20
    maxPerFile: int = 3


class RagRequest(Model):
    jobId: str
    snapshotId: str
    scope: list[str]
    files: list[RagFile]
    limits: RagLimits


class RetrievalHit(Model):
    chunkId: str
    namespace: str
    sourceId: str
    title: str
    url: str
    headingPath: list[str]
    text: str
    finalScore: float
    sparseRank: int | None = None
    denseRank: int | None = None


class CandidateSuggestion(Model):
    filePath: str
    lineStart: int
    lineEnd: int
    severity: str
    category: str
    title: str
    body: str
    confidence: float
    evidenceChunkIds: list[str]


class CandidateSuggestionEnvelope(Model):
    suggestions: list[CandidateSuggestion] = Field(default_factory=list)


class Citation(Model):
    sourceId: str
    title: str
    url: str
    snippet: str


class BackendSuggestion(Model):
    filePath: str
    lineStart: int
    lineEnd: int
    severity: str
    category: str
    title: str
    body: str
    citations: list[Citation]
    confidence: float
    fingerprint: str


class RagResponse(Model):
    suggestions: list[BackendSuggestion]
    partialFailures: int


class ValidationResult(Model):
    valid: bool
    reason: str | None = None
    lineStart: int | None = None
    lineEnd: int | None = None


class RankedSuggestion(Model):
    suggestion: BackendSuggestion
    rankScore: float
    retrievalScore: float


class HunkTask(Model):
    filePath: str
    language: str
    languageSlug: str
    patch: str
    hunkHeader: str
    hunkPatch: str
    addedLines: list[str]
    changedNewLines: list[int]
    firstChangedLine: int
    priority: float


class RetrievalQuery(Model):
    namespaces: list[str]
    queryText: str
    topK: int


class OllamaMessage(Model):
    role: str
    content: str


class BuildNamespaceArtifacts(Model):
    namespace: str
    chunkCount: int
    chunkPath: str
    sparsePath: str
    densePath: str
    denseMetaPath: str


JSONDict = dict[str, Any]
