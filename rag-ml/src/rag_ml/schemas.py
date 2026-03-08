from __future__ import annotations

from typing import Any, Literal

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


class RagCodeContextLine(Model):
    lineNumber: int
    text: str


class RagFile(Model):
    path: str
    language: str
    patch: str
    hunks: list[RagHunk] | None = None
    lineMap: list[RagLineMapEntry] | None = None
    imports: list[str] = Field(default_factory=list)
    changedSymbols: list[str] = Field(default_factory=list)
    surroundingCode: list[RagCodeContextLine] = Field(default_factory=list)


class RagLimits(Model):
    maxComments: int = 20
    maxPerFile: int = 3


class RagRequest(Model):
    jobId: str
    snapshotId: str
    prId: str | None = None
    title: str | None = None
    description: str | None = None
    baseSha: str | None = None
    headSha: str | None = None
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


class PROverviewHotspot(Model):
    filePath: str
    reasons: list[str]
    risk: float


class PROverview(Model):
    prIntent: str
    riskLevel: Literal["low", "medium", "high"]
    recommendedScopes: list[str] = Field(default_factory=list)
    hotspots: list[PROverviewHotspot] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class StaticSignal(Model):
    signalId: str
    filePath: str
    type: str
    severity: Literal["info", "low", "medium", "high", "critical"] = "info"
    message: str
    lineStart: int | None = None
    lineEnd: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StaticChecksResult(Model):
    signals: list[StaticSignal] = Field(default_factory=list)
    toolFindings: list[StaticSignal] = Field(default_factory=list)


class HotspotTask(Model):
    taskId: str
    filePath: str
    category: str
    priority: float
    selectedHunks: list[int] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ContextEvidenceCandidate(Model):
    refId: str
    type: Literal["code", "rule", "doc", "history"]
    title: str
    snippet: str
    filePath: str | None = None
    lineStart: int | None = None
    lineEnd: int | None = None
    sourceId: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextPack(Model):
    taskId: str
    codeEvidenceCandidates: list[ContextEvidenceCandidate] = Field(default_factory=list)
    ruleEvidenceCandidates: list[ContextEvidenceCandidate] = Field(default_factory=list)
    docEvidenceCandidates: list[ContextEvidenceCandidate] = Field(default_factory=list)
    historyEvidenceCandidates: list[ContextEvidenceCandidate] = Field(default_factory=list)


class CandidateFinding(Model):
    filePath: str
    lineStart: int
    lineEnd: int
    severity: str
    category: str
    title: str
    body: str
    confidence: float
    evidenceRefs: list[str] = Field(default_factory=list)


class CandidateFindingEnvelope(Model):
    suggestions: list[CandidateFinding] = Field(default_factory=list)


class Evidence(Model):
    evidenceId: str
    type: Literal["code", "rule", "doc", "history"]
    title: str
    snippet: str
    filePath: str | None = None
    lineStart: int | None = None
    lineEnd: int | None = None
    sourceId: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    deliveryMode: Literal["inline", "summary"] = "inline"
    evidence: list[Evidence] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float
    fingerprint: str
    meta: dict[str, Any] = Field(default_factory=dict)


class RagResponse(Model):
    suggestions: list[BackendSuggestion]
    partialFailures: int
    meta: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(Model):
    valid: bool
    reason: str | None = None
    lineStart: int | None = None
    lineEnd: int | None = None


class RankedSuggestion(Model):
    suggestion: BackendSuggestion
    rankScore: float
    retrievalScore: float
    evidenceStrength: float = 0.0
    plannerPriority: float = 0.0
    staticSupport: float = 0.0
    repoFeedbackScore: float = 0.0


class HunkTask(Model):
    taskId: str
    filePath: str
    language: str
    languageSlug: str
    patch: str
    hunkIndex: int
    hunkHeader: str
    hunkPatch: str
    addedLines: list[str]
    changedNewLines: list[int]
    firstChangedLine: int
    priority: float
    imports: list[str] = Field(default_factory=list)
    changedSymbols: list[str] = Field(default_factory=list)
    surroundingCode: list[RagCodeContextLine] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    staticSignalIds: list[str] = Field(default_factory=list)


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


class ProgressUpdate(Model):
    stage: Literal["overview", "static", "planning", "review", "synthesis", "ranking"]
    message: str
    filePath: str | None = None
    stageDone: int | None = None
    stageTotal: int | None = None
    filesDone: int | None = None
    filesTotal: int | None = None
    level: Literal["info", "warn", "error"] = "info"
    meta: dict[str, Any] = Field(default_factory=dict)


JSONDict = dict[str, Any]
