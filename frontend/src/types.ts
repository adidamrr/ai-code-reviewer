export type SuggestionScope = "security" | "style" | "bugs" | "performance";
export type PublishMode = "review_comments" | "issue_comments";
export type WorkspaceStep = "pr" | "params" | "job" | "results" | "publish" | "feedback" | "history";

export interface GithubSession {
  sessionId: string;
  githubLogin: string;
  expiresAt: string;
}

export interface GithubRepo {
  repoId: string;
  providerRepoId: number;
  owner: string;
  name: string;
  fullName: string;
  defaultBranch: string;
  private: boolean;
}

export interface GithubPr {
  number: number;
  title: string;
  state: "open" | "closed";
  url: string;
  authorLogin: string;
  baseSha: string;
  headSha: string;
  updatedAt: string;
}

export interface SyncResponse {
  repoId: string;
  prId: string;
  snapshotId: string;
  counts: {
    files: number;
    additions: number;
    deletions: number;
  };
  idempotent: boolean;
  source: string;
}

export interface AnalysisJobCreateResponse {
  jobId: string;
  status: string;
  progress: {
    filesDone: number;
    total: number;
    stage?: "overview" | "static" | "planning" | "review" | "synthesis" | "ranking";
    stageProgress?: {
      done: number;
      total: number;
    };
  };
}

export interface AnalysisJob {
  id: string;
  prId: string;
  snapshotId: string;
  status: "queued" | "running" | "done" | "failed" | "canceled";
  scope: SuggestionScope[];
  maxComments: number;
  progress: {
    filesDone: number;
    total: number;
    stage?: "overview" | "static" | "planning" | "review" | "synthesis" | "ranking";
    stageProgress?: {
      done: number;
      total: number;
    };
  };
  summary: {
    totalSuggestions: number;
    partialFailures: number;
    filesSkipped: number;
    warnings: string[];
  };
  errorMessage: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface AnalysisJobEvent {
  id: string;
  jobId: string;
  level: "info" | "warn" | "error";
  message: string;
  filePath: string | null;
  stage?: "overview" | "static" | "planning" | "review" | "synthesis" | "ranking" | null;
  meta: Record<string, unknown> | null;
  createdAt: string;
}

export interface Citation {
  sourceId: string;
  title: string;
  url: string;
  snippet: string;
}

export interface Evidence {
  evidenceId: string;
  type: "code" | "rule" | "doc" | "history";
  title: string;
  snippet: string;
  filePath?: string | null;
  lineStart?: number | null;
  lineEnd?: number | null;
  sourceId?: string | null;
  url?: string | null;
  metadata?: Record<string, unknown>;
}

export interface Suggestion {
  id: string;
  fingerprint: string;
  filePath: string;
  lineStart: number;
  lineEnd: number;
  severity: "info" | "low" | "medium" | "high" | "critical";
  category: SuggestionScope;
  title: string;
  body: string;
  deliveryMode?: "inline" | "summary";
  evidence?: Evidence[];
  citations: Citation[];
  confidence: number;
  meta?: Record<string, unknown>;
}

export interface PublishedComment {
  id: string;
  prId: string;
  jobId: string;
  suggestionId: string;
  providerCommentId: string | null;
  mode: PublishMode;
  state: "pending" | "posted" | "failed";
  filePath: string;
  lineStart: number;
  lineEnd: number;
  body: string;
  createdAt: string;
}

export interface FeedbackSummary {
  prId: string;
  overall: {
    up: number;
    down: number;
    score: number;
  };
  byFile: Array<{
    filePath: string;
    up: number;
    down: number;
    score: number;
    comments: number;
  }>;
  byCategory: Array<{
    category: SuggestionScope;
    up: number;
    down: number;
    score: number;
  }>;
  bySeverity: Array<{
    severity: string;
    up: number;
    down: number;
    score: number;
  }>;
}

export interface PullRequestMeta {
  id: string;
  repoId: string;
  number: number;
  title: string;
  state: "open" | "closed" | "merged";
  authorLogin: string;
  url: string;
  baseSha: string;
  headSha: string;
  latestSnapshotId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface SnapshotMeta {
  id: string;
  prId: string;
  commitSha: string;
  baseSha: string;
  headSha: string;
  filesCount: number;
  additions: number;
  deletions: number;
  createdAt: string;
}

export interface PrMetaResponse {
  pr: PullRequestMeta;
  latestSnapshot: SnapshotMeta | null;
}

export interface SnapshotDiffFile {
  id: string;
  snapshotId: string;
  path: string;
  status: "added" | "modified" | "removed" | "renamed";
  language: string;
  additions: number;
  deletions: number;
  patch: string;
  isTooLarge: boolean;
  createdAt: string;
}

export interface PrDiffResponse {
  items: SnapshotDiffFile[];
  count: number;
}

export interface RepoRunSummary {
  runId: string;
  jobId: string;
  repoId: string;
  repoFullName: string;
  prId: string;
  prNumber: number;
  prTitle: string;
  status: AnalysisJob["status"];
  totalSuggestions: number;
  publishedComments: number;
  feedbackScore: number;
  createdAt: string;
  updatedAt: string;
}

export interface CursorPage<T> {
  items: T[];
  nextCursor: string | null;
  limit: number;
}

export interface ApiError {
  error?: {
    code?: string;
    message?: string;
  };
}
