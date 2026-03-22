import type {
  AnalysisJob,
  AnalysisJobEvent,
  AnalysisJobCreateResponse,
  CursorPage,
  FeedbackSummary,
  GenerationModelProfile,
  GithubPr,
  GithubRepo,
  GithubSession,
  PrDiffResponse,
  PrMetaResponse,
  PublishedComment,
  PublishMode,
  RepoRunSummary,
  Suggestion,
  SuggestionScope,
  SyncResponse,
} from "../types";

export interface ApiClientConfig {
  baseUrl: string;
  serviceToken?: string;
}

export class ApiClient {
  constructor(private readonly config: ApiClientConfig) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers ?? {});

    if (!headers.has("Content-Type") && init.body) {
      headers.set("Content-Type", "application/json");
    }

    if (this.config.serviceToken) {
      headers.set("Authorization", `Bearer ${this.config.serviceToken}`);
    }

    const response = await fetch(`${this.config.baseUrl}${path}`, {
      ...init,
      headers,
    });

    if (response.status === 204) {
      return undefined as T;
    }

    const text = await response.text();
    const data = text ? JSON.parse(text) : null;

    if (!response.ok) {
      const message = data?.error?.message ?? `Request failed: ${response.status}`;
      throw new Error(message);
    }

    return data as T;
  }

  createGithubSession(token: string) {
    return this.request<GithubSession>("/github/session", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  }

  createGitlabSession(token: string) {
    return this.request<GithubSession>("/gitlab/session", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  }

  deleteGithubSession(sessionId: string) {
    return this.request<void>(`/github/session/${sessionId}`, {
      method: "DELETE",
    });
  }

  deleteGitlabSession(sessionId: string) {
    return this.request<void>(`/gitlab/session/${sessionId}`, {
      method: "DELETE",
    });
  }

  getGithubRepos(sessionId: string, cursor?: string | null) {
    const search = new URLSearchParams();
    if (cursor) {
      search.set("cursor", cursor);
    }
    return this.request<CursorPage<GithubRepo>>(
      `/github/session/${sessionId}/repos${search.size ? `?${search.toString()}` : ""}`,
    );
  }

  getGitlabRepos(sessionId: string, cursor?: string | null) {
    const search = new URLSearchParams();
    if (cursor) {
      search.set("cursor", cursor);
    }
    return this.request<CursorPage<GithubRepo>>(
      `/gitlab/session/${sessionId}/repos${search.size ? `?${search.toString()}` : ""}`,
    );
  }

  getGithubPrs(sessionId: string, owner: string, repo: string, state: "open" | "closed" | "all" = "open") {
    return this.request<{ items: GithubPr[]; count: number }>(
      `/github/session/${sessionId}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/prs?state=${state}`,
    );
  }

  getGitlabMrs(sessionId: string, projectId: string, state: "open" | "closed" | "all" = "open") {
    return this.request<{ items: GithubPr[]; count: number }>(
      `/gitlab/session/${sessionId}/repos/${encodeURIComponent(projectId)}/mrs?state=${state}`,
    );
  }

  syncGithubPr(sessionId: string, owner: string, repo: string, prNumber: number) {
    return this.request<SyncResponse>(
      `/github/session/${sessionId}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/prs/${prNumber}/sync`,
      {
        method: "POST",
      },
    );
  }

  syncGitlabMr(sessionId: string, projectId: string, mrIid: number) {
    return this.request<SyncResponse>(
      `/gitlab/session/${sessionId}/repos/${encodeURIComponent(projectId)}/mrs/${mrIid}/sync`,
      {
        method: "POST",
      },
    );
  }

  createAnalysisJob(
    prId: string,
    body: { snapshotId: string; scope: SuggestionScope[]; maxComments: number; modelProfile: GenerationModelProfile },
  ) {
    return this.request<AnalysisJobCreateResponse>(`/prs/${prId}/analysis-jobs`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  getAnalysisJob(jobId: string) {
    return this.request<AnalysisJob>(`/analysis-jobs/${jobId}`);
  }

  getAnalysisResults(jobId: string, cursor?: string | null) {
    const search = new URLSearchParams();
    if (cursor) {
      search.set("cursor", cursor);
    }
    return this.request<CursorPage<Suggestion>>(
      `/analysis-jobs/${jobId}/results${search.size ? `?${search.toString()}` : ""}`,
    );
  }

  getAnalysisJobEvents(jobId: string, cursor?: string | null) {
    const search = new URLSearchParams();
    if (cursor) {
      search.set("cursor", cursor);
    }
    return this.request<CursorPage<AnalysisJobEvent>>(
      `/analysis-jobs/${jobId}/events${search.size ? `?${search.toString()}` : ""}`,
    );
  }

  cancelAnalysisJob(jobId: string) {
    return this.request<AnalysisJob>(`/analysis-jobs/${jobId}/cancel`, {
      method: "POST",
    });
  }

  publishSuggestions(prId: string, body: { jobId: string; mode: PublishMode; dryRun: boolean; sessionId?: string }) {
    return this.request<{
      publishRunId: string;
      publishedCount: number;
      errors: string[];
      comments: PublishedComment[];
      idempotent: boolean;
    }>(`/prs/${prId}/publish`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  getPrComments(prId: string, cursor?: string | null) {
    const search = new URLSearchParams();
    if (cursor) {
      search.set("cursor", cursor);
    }

    return this.request<CursorPage<PublishedComment>>(
      `/prs/${prId}/comments${search.size ? `?${search.toString()}` : ""}`,
    );
  }

  putFeedback(commentId: string, body: { userId: string; vote: "up" | "down"; reason?: string }) {
    return this.request(`/comments/${commentId}/feedback`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  }

  getFeedbackSummary(prId: string) {
    return this.request<FeedbackSummary>(`/prs/${prId}/feedback-summary`);
  }

  getPr(prId: string) {
    return this.request<PrMetaResponse>(`/prs/${prId}`);
  }

  getPrDiff(prId: string, filePath?: string) {
    const search = new URLSearchParams();
    if (filePath) {
      search.set("file", filePath);
    }

    return this.request<PrDiffResponse>(`/prs/${prId}/diff${search.size ? `?${search.toString()}` : ""}`);
  }

  getRepoRuns(repoId: string, cursor?: string | null) {
    const search = new URLSearchParams();
    if (cursor) {
      search.set("cursor", cursor);
    }
    return this.request<CursorPage<RepoRunSummary>>(
      `/repos/${repoId}/runs${search.size ? `?${search.toString()}` : ""}`,
    );
  }
}
