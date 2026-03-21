import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ApiClient } from "../lib/api";
import { DEBUG_PR_PRESETS } from "../debug/presets";
import type {
  AnalysisJob,
  AnalysisJobEvent,
  CursorPage,
  FeedbackSummary,
  GenerationModelProfile,
  GithubPr,
  GithubRepo,
  GithubSession,
  PublishMode,
  RepoRunSummary,
  Suggestion,
  SuggestionScope,
  SyncResponse,
  WorkspaceStep,
} from "../types";

const DEFAULT_BACKEND =
  import.meta.env.VITE_BACKEND_BASE_URL ??
  (typeof window !== "undefined" ? window.location.origin : "http://localhost:4000");
const DEFAULT_SERVICE_TOKEN = import.meta.env.VITE_API_SERVICE_TOKEN ?? "";
const ENABLE_DEBUG_SUITE = import.meta.env.VITE_ENABLE_DEBUG_SUITE === "true";
const WORKSPACE_PREFERENCES_KEY = "swagreviewer_repo_workspace_v1";

export const WORKSPACE_STEPS: WorkspaceStep[] = [
  "pr",
  "job",
  "results",
  "publish",
  "feedback",
  "history",
];

export const STEP_LABELS: Record<WorkspaceStep, string> = {
  pr: "PR",
  job: "Job",
  results: "Результаты",
  publish: "Публикация",
  feedback: "Фидбек",
  history: "История",
};

export const ALL_SCOPES: SuggestionScope[] = ["security", "style", "bugs", "performance"];
export const ANALYSIS_SCOPES: SuggestionScope[] = ["bugs", "security", "performance"];

export const GENERATION_MODEL_OPTIONS: Array<{
  id: GenerationModelProfile;
  label: string;
  description: string;
}> = [
  { id: "yandexgpt-pro", label: "YandexGPT Pro", description: "Основной balanced режим для review." },
  { id: "yandexgpt-lite", label: "YandexGPT Lite", description: "Быстрый и более дешевый прогон." },
  { id: "qwen3-235b", label: "Qwen3 235B", description: "Тяжелые PR и длинный контекст." },
  { id: "gpt-oss-120b", label: "GPT OSS 120B", description: "Альтернативная сильная open model." },
];

export const SCOPE_LABELS: Record<SuggestionScope, string> = {
  security: "Безопасность",
  style: "Стиль",
  bugs: "Баги",
  performance: "Производительность",
};

export const JOB_STATUS_LABELS: Record<AnalysisJob["status"], string> = {
  queued: "в очереди",
  running: "выполняется",
  done: "завершена",
  failed: "ошибка",
  canceled: "отменена",
};

export const JOB_STAGE_LABELS: Record<NonNullable<AnalysisJob["progress"]["stage"]>, string> = {
  overview: "Обзор PR",
  static: "Статический анализ",
  planning: "Планирование hotspot",
  review: "Анализ файлов",
  synthesis: "Синтез результатов",
  ranking: "Финальный ранжирующий проход",
};

export const SEVERITY_LABELS: Record<Suggestion["severity"], string> = {
  info: "info",
  low: "низкий",
  medium: "средний",
  high: "высокий",
  critical: "критичный",
};

interface ActivityLog {
  id: string;
  at: string;
  text: string;
}

interface RecentReviewItem {
  reviewKey: string;
  repoId: string;
  prNumber: number;
  repoFullName: string;
  prTitle: string;
  status: "ready" | "running" | "results" | "published";
  lastOpenedAt: string;
}

interface PersistedWorkspacePreference {
  selectedPrNumber: number | null;
  activeStep: WorkspaceStep;
  prState: "open" | "closed" | "all";
}

interface RepoBrowserState {
  repoId: string;
  prState: "open" | "closed" | "all";
  prSearch: string;
  prs: GithubPr[];
  selectedPrNumber: number | null;
}

interface ReviewWorkspaceState {
  repoId: string;
  prNumber: number | null;

  syncData: SyncResponse | null;

  scope: Record<SuggestionScope, boolean>;
  generationModelProfile: GenerationModelProfile;
  maxComments: number;
  minSeverity: "none" | Suggestion["severity"];
  fileFilter: string;

  job: AnalysisJob | null;
  jobBooting: boolean;
  jobBootStartedAt: string | null;
  jobEvents: AnalysisJobEvent[];
  suggestions: Suggestion[];
  suggestionSearch: string;
  suggestionCategoryFilter: "all" | SuggestionScope;
  severityFilter: "all" | Suggestion["severity"];
  selectedSuggestionIds: string[];
  activeSuggestionId: string | null;

  publishMode: PublishMode;
  dryRun: boolean;
  publishResult: {
    publishRunId: string;
    publishedCount: number;
    idempotent: boolean;
    errors: string[];
  } | null;

  comments: Array<{
    id: string;
    filePath: string;
    lineStart: number;
    lineEnd: number;
    body: string;
    state: string;
    mode: string;
    providerCommentId: string | null;
    createdAt: string;
  }>;
  feedbackSummary: FeedbackSummary | null;
  feedbackUserId: string;
  feedbackReason: string;

  runs: RepoRunSummary[];
  runsCursor: string | null;
  historyIsMock: boolean;

  activeStep: WorkspaceStep;
  lastTouchedAt: string | null;
}

interface AppState {
  backendUrl: string;
  serviceToken: string;
  githubToken: string;
  gitlabToken: string;
  scmProvider: "github" | "gitlab";
  session: GithubSession | null;

  repos: GithubRepo[];
  repoCursor: string | null;
  selectedRepoId: string | null;

  repoBrowsers: Record<string, RepoBrowserState>;
  reviewWorkspaces: Record<string, ReviewWorkspaceState>;

  busy: boolean;
  error: string | null;
  activity: ActivityLog[];
  debugSuiteEnabled: boolean;

  debugSuite: {
    running: boolean;
    items: Array<{
      presetId: string;
      label: string;
      owner: string;
      repo: string;
      prNumber: number;
      repoId: string | null;
      jobId: string | null;
      status: "pending" | "running" | "done" | "failed";
      suggestions: number | null;
      error: string | null;
      startedAt: string | null;
      finishedAt: string | null;
    }>;
  };
}

interface AppStoreActions {
  setBackendUrl: (value: string) => void;
  setServiceToken: (value: string) => void;
  setGithubToken: (value: string) => void;
  setGitlabToken: (value: string) => void;
  setScmProvider: (value: "github" | "gitlab") => void;

  clearError: () => void;

  connectScm: () => Promise<boolean>;
  disconnectScm: () => Promise<void>;
  checkBackendHealth: () => Promise<{ ok: boolean; status: string }>;

  loadRepos: (reset?: boolean) => Promise<void>;
  selectRepo: (repoId: string) => void;
  runDebugSuite: () => Promise<void>;

  setPrState: (repoId: string, value: "open" | "closed" | "all") => void;
  setPrSearch: (repoId: string, value: string) => void;
  loadPullRequests: (repoId: string) => Promise<void>;
  selectPullRequest: (repoId: string, prNumber: number | null) => void;

  syncPullRequest: (repoId: string) => Promise<void>;
  analyzePullRequest: (repoId: string) => Promise<void>;

  setActiveStep: (repoId: string, step: WorkspaceStep) => void;
  setMaxComments: (repoId: string, value: number) => void;
  setMinSeverity: (repoId: string, value: "none" | Suggestion["severity"]) => void;
  setFileFilter: (repoId: string, value: string) => void;
  toggleScope: (repoId: string, scope: SuggestionScope) => void;
  setGenerationModelProfile: (repoId: string, value: GenerationModelProfile) => void;

  createAnalysisJob: (repoId: string) => Promise<void>;
  refreshJob: (repoId: string) => Promise<void>;
  cancelJob: (repoId: string) => Promise<void>;
  loadJobEvents: (repoId: string) => Promise<void>;

  setSuggestionSearch: (repoId: string, value: string) => void;
  setSuggestionCategoryFilter: (repoId: string, value: "all" | SuggestionScope) => void;
  setSeverityFilter: (repoId: string, value: "all" | Suggestion["severity"]) => void;
  toggleSuggestionSelection: (repoId: string, suggestionId: string) => void;
  setActiveSuggestion: (repoId: string, suggestionId: string | null) => void;
  selectAllSuggestions: (repoId: string) => void;
  clearSuggestionSelection: (repoId: string) => void;
  reloadSuggestions: (repoId: string) => Promise<void>;

  setPublishMode: (repoId: string, mode: PublishMode) => void;
  setDryRun: (repoId: string, dryRun: boolean) => void;
  publishSuggestions: (repoId: string) => Promise<void>;
  loadComments: (repoId: string) => Promise<void>;

  setFeedbackUserId: (repoId: string, userId: string) => void;
  setFeedbackReason: (repoId: string, reason: string) => void;
  voteComment: (repoId: string, commentId: string, vote: "up" | "down") => Promise<void>;
  loadFeedbackSummary: (repoId: string) => Promise<void>;

  loadRepoRuns: (repoId: string, reset?: boolean) => Promise<void>;
  reopenRun: (repoId: string, run: RepoRunSummary) => Promise<void>;
}

interface AppStoreValue extends AppState {
  actions: AppStoreActions;
  recentReviews: RecentReviewItem[];
  getWorkflow: (repoId: string | null | undefined) => ReviewWorkspaceState | null;
  getRepoBrowser: (repoId: string | null | undefined) => RepoBrowserState | null;
  getSelectedRepo: () => GithubRepo | null;
  getRepoStatus: (repoId: string) => { label: string; tone: "ok" | "warn" | "muted" };
  canOpenStep: (repoId: string, step: WorkspaceStep) => boolean;
}

const AppStoreContext = createContext<AppStoreValue | null>(null);

const initialState: AppState = {
  backendUrl: DEFAULT_BACKEND,
  serviceToken: DEFAULT_SERVICE_TOKEN,
  githubToken: "",
  gitlabToken: "",
  scmProvider: "github",
  session: null,
  repos: [],
  repoCursor: null,
  selectedRepoId: null,
  repoBrowsers: {},
  reviewWorkspaces: {},
  busy: false,
  error: null,
  activity: [],
  debugSuiteEnabled: ENABLE_DEBUG_SUITE,
  debugSuite: {
    running: false,
    items: DEBUG_PR_PRESETS.map((preset) => ({
      presetId: preset.id,
      label: preset.label,
      owner: preset.owner,
      repo: preset.repo,
      prNumber: preset.prNumber,
      repoId: null,
      jobId: null,
      status: "pending" as const,
      suggestions: null,
      error: null,
      startedAt: null,
      finishedAt: null,
    })),
  },
};

export function AppStoreProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AppState>(initialState);
  const stateRef = useRef(state);
  const busyCounterRef = useRef(0);
  const workspacePreferencesRef = useRef(loadWorkspacePreferences());

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    const payload: Record<string, PersistedWorkspacePreference> = {};
    for (const [repoId, browser] of Object.entries(state.repoBrowsers)) {
      const reviewKey = browser.selectedPrNumber !== null ? getReviewKey(repoId, browser.selectedPrNumber) : null;
      const review = reviewKey ? state.reviewWorkspaces[reviewKey] : null;
      payload[repoId] = {
        selectedPrNumber: browser.selectedPrNumber,
        activeStep: review?.activeStep ?? "pr",
        prState: browser.prState,
      };
    }
    workspacePreferencesRef.current = payload;
    persistWorkspacePreferences(payload);
  }, [state.repoBrowsers, state.reviewWorkspaces]);

  const resetWorkspacePreferences = useCallback(() => {
    workspacePreferencesRef.current = {};
    clearWorkspacePreferences();
  }, []);

  const apiFactory = useCallback(() => {
    const current = stateRef.current;
    return new ApiClient({
      baseUrl: current.backendUrl,
      serviceToken: current.serviceToken.trim().length > 0 ? current.serviceToken.trim() : undefined,
    });
  }, []);

  const pushActivity = useCallback((text: string) => {
    setState((prev) => ({
      ...prev,
      activity: [
        {
          id: crypto.randomUUID(),
          at: new Date().toLocaleTimeString("ru-RU"),
          text,
        },
        ...prev.activity,
      ].slice(0, 30),
    }));
  }, []);

  const setBusy = useCallback((next: boolean) => {
    setState((prev) => ({ ...prev, busy: next }));
  }, []);

  const sleep = useCallback((ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms)), []);

  const ensureRepoLoaded = useCallback(
    async (
      sessionId: string,
      provider: GithubSession["provider"],
      owner: string,
      name: string,
    ): Promise<GithubRepo> => {
      const normalize = (value: string) => value.trim().toLowerCase();
      const targetOwner = normalize(owner);
      const targetName = normalize(name);

      const existing = stateRef.current.repos.find(
        (repo) => normalize(repo.owner) === targetOwner && normalize(repo.name) === targetName,
      );
      if (existing) {
        return existing;
      }

      const api = apiFactory();
      const merged = new Map<string, GithubRepo>();
      for (const repo of stateRef.current.repos) {
        merged.set(repo.repoId, repo);
      }

      let cursor: string | null = null;
      let pageCount = 0;

      while (pageCount < 30) {
        const page: CursorPage<GithubRepo> = provider === "gitlab"
          ? await api.getGitlabRepos(sessionId, cursor)
          : await api.getGithubRepos(sessionId, cursor);
        pageCount += 1;

        for (const repo of page.items) {
          merged.set(repo.repoId, repo);
        }

        const values = [...merged.values()];
        setState((prev) => ({
          ...prev,
          repos: values,
          repoCursor: page.nextCursor,
          selectedRepoId: prev.selectedRepoId ?? values[0]?.repoId ?? null,
        }));

        const found = page.items.find(
          (repo) => normalize(repo.owner) === targetOwner && normalize(repo.name) === targetName,
        );
        if (found) {
          return found;
        }

        if (!page.nextCursor) {
          break;
        }

        cursor = page.nextCursor;
      }

      throw new Error(`Репозиторий ${owner}/${name} не найден или недоступен по текущему токену.`);
    },
    [apiFactory],
  );

  const runTask = useCallback(
    async <T,>(label: string, task: () => Promise<T>): Promise<T> => {
      busyCounterRef.current += 1;
      setBusy(true);
      setState((prev) => ({ ...prev, error: null }));
      try {
        const result = await task();
        pushActivity(label);
        return result;
      } catch (error) {
        const message = formatUiError(error, stateRef.current.backendUrl);
        setState((prev) => ({ ...prev, error: message }));
        pushActivity(`Ошибка: ${message}`);
        throw error;
      } finally {
        busyCounterRef.current = Math.max(0, busyCounterRef.current - 1);
        if (busyCounterRef.current === 0) {
          setBusy(false);
        }
      }
    },
    [pushActivity, setBusy],
  );

  const upsertRepoBrowser = useCallback((repoId: string, updater: (current: RepoBrowserState) => RepoBrowserState) => {
    setState((prev) => {
      const existing = prev.repoBrowsers[repoId] ?? createDefaultRepoBrowser(repoId, workspacePreferencesRef.current[repoId]);
      return {
        ...prev,
        repoBrowsers: {
          ...prev.repoBrowsers,
          [repoId]: updater(existing),
        },
      };
    });
  }, []);

  const upsertReviewWorkspace = useCallback(
    (reviewKey: string, updater: (current: ReviewWorkspaceState) => ReviewWorkspaceState) => {
      setState((prev) => {
        const existing = prev.reviewWorkspaces[reviewKey] ?? createDefaultReviewWorkspaceFromKey(reviewKey);
        return {
          ...prev,
          reviewWorkspaces: {
            ...prev.reviewWorkspaces,
            [reviewKey]: updater(existing),
          },
        };
      });
    },
    [],
  );

  const touchReviewWorkspace = useCallback((reviewKey: string) => {
    setState((prev) => {
      const now = new Date().toISOString();
      const existing = prev.reviewWorkspaces[reviewKey] ?? createDefaultReviewWorkspaceFromKey(reviewKey);
      return {
        ...prev,
        reviewWorkspaces: {
          ...prev.reviewWorkspaces,
          [reviewKey]: {
            ...existing,
            lastTouchedAt: now,
          },
        },
      };
    });
  }, []);

  const getCurrentReviewContext = useCallback((repoId: string) => {
    const browser = stateRef.current.repoBrowsers[repoId] ?? createDefaultRepoBrowser(repoId, workspacePreferencesRef.current[repoId]);
    const prNumber = browser.selectedPrNumber;
    if (prNumber === null) {
      return {
        browser,
        prNumber,
        reviewKey: null,
        review: createDefaultReviewWorkspace(repoId, null),
      };
    }

    const reviewKey = getReviewKey(repoId, prNumber);
    const review = stateRef.current.reviewWorkspaces[reviewKey] ?? createDefaultReviewWorkspace(repoId, prNumber);

    return {
      browser,
      prNumber,
      reviewKey,
      review,
    };
  }, []);

  const selectRepoInternal = useCallback(
    (repoId: string) => {
      setState((prev) => {
        const nextRepoBrowsers = prev.repoBrowsers[repoId]
          ? prev.repoBrowsers
          : {
              ...prev.repoBrowsers,
              [repoId]: createDefaultRepoBrowser(repoId, workspacePreferencesRef.current[repoId]),
            };

        return {
          ...prev,
          selectedRepoId: repoId,
          repoBrowsers: nextRepoBrowsers,
        };
      });
    },
    [],
  );

  const loadReposInternal = useCallback(
    async (sessionId: string, provider: GithubSession["provider"], reset: boolean) => {
      const current = stateRef.current;
      const api = apiFactory();
      const page = provider === "gitlab"
        ? await api.getGitlabRepos(sessionId, reset ? null : current.repoCursor)
        : await api.getGithubRepos(sessionId, reset ? null : current.repoCursor);

      setState((prev) => {
        const merged = reset ? page.items : [...prev.repos, ...page.items];
        const byId = new Map<string, GithubRepo>();
        for (const item of merged) {
          byId.set(item.repoId, item);
        }

        return {
          ...prev,
          repos: [...byId.values()],
          repoCursor: page.nextCursor,
          selectedRepoId: prev.selectedRepoId ?? page.items[0]?.repoId ?? null,
        };
      });
    },
    [apiFactory],
  );

  const loadSuggestionsInternal = useCallback(
    async (reviewKey: string, jobId: string) => {
      const api = apiFactory();
      let cursor: string | null = null;
      const items: Suggestion[] = [];

      do {
        const page = await api.getAnalysisResults(jobId, cursor);
        items.push(...page.items);
        cursor = page.nextCursor;
      } while (cursor);

      upsertReviewWorkspace(reviewKey, (workflow) => {
        const inlineIds = items.filter((item) => (item.deliveryMode ?? "inline") === "inline").map((item) => item.id);
        const selectedSuggestionIds = workflow.selectedSuggestionIds.length > 0
          ? workflow.selectedSuggestionIds.filter((id) => inlineIds.includes(id))
          : inlineIds;

        return {
          ...workflow,
          suggestions: items,
          lastTouchedAt: new Date().toISOString(),
          selectedSuggestionIds,
          activeSuggestionId: workflow.activeSuggestionId && items.some((item) => item.id === workflow.activeSuggestionId)
            ? workflow.activeSuggestionId
            : items[0]?.id ?? null,
          activeStep: items.length > 0 && workflow.activeStep === "job" ? "results" : workflow.activeStep,
        };
      });

      pushActivity(`Загружено рекомендаций: ${items.length}`);
    },
    [apiFactory, pushActivity, upsertReviewWorkspace],
  );

  const loadCommentsInternal = useCallback(
    async (reviewKey: string, prId: string) => {
      const api = apiFactory();
      let cursor: string | null = null;
      const all: ReviewWorkspaceState["comments"] = [];

      do {
        const page = await api.getPrComments(prId, cursor);
        all.push(...page.items);
        cursor = page.nextCursor;
      } while (cursor);

      upsertReviewWorkspace(reviewKey, (workflow) => ({
        ...workflow,
        lastTouchedAt: new Date().toISOString(),
        comments: all,
      }));
    },
    [apiFactory, upsertReviewWorkspace],
  );

  const loadFeedbackSummaryInternal = useCallback(
    async (reviewKey: string, prId: string) => {
      const api = apiFactory();
      const summary = await api.getFeedbackSummary(prId);
      upsertReviewWorkspace(reviewKey, (workflow) => ({
        ...workflow,
        lastTouchedAt: new Date().toISOString(),
        feedbackSummary: summary,
      }));
    },
    [apiFactory, upsertReviewWorkspace],
  );

  const loadJobEventsInternal = useCallback(
    async (reviewKey: string, jobId: string) => {
      const api = apiFactory();
      let cursor: string | null = null;
      const events: AnalysisJobEvent[] = [];

      try {
        do {
          const page = await api.getAnalysisJobEvents(jobId, cursor);
          events.push(...page.items);
          cursor = page.nextCursor;
        } while (cursor);

        upsertReviewWorkspace(reviewKey, (workflow) => ({
          ...workflow,
          lastTouchedAt: new Date().toISOString(),
          jobEvents: events,
        }));
      } catch (_error) {
        const job = stateRef.current.reviewWorkspaces[reviewKey]?.job;
        const mockEvents = createMockEvents(job);
        upsertReviewWorkspace(reviewKey, (workflow) => ({
          ...workflow,
          lastTouchedAt: new Date().toISOString(),
          jobEvents: mockEvents,
        }));
      }
    },
    [apiFactory, upsertReviewWorkspace],
  );

  const startAnalysisJobInternal = useCallback(
    async (
      reviewKey: string,
      syncData: SyncResponse,
      scope: SuggestionScope[],
      maxComments: number,
    ) => {
      const bootStartedAt = new Date().toISOString();
      const pendingJobId = `pending-${crypto.randomUUID()}`;

      upsertReviewWorkspace(reviewKey, (current) => ({
        ...current,
        syncData,
        activeStep: "job",
        jobBooting: true,
        jobBootStartedAt: bootStartedAt,
        lastTouchedAt: bootStartedAt,
        job: {
          id: pendingJobId,
          prId: syncData.prId,
          snapshotId: syncData.snapshotId,
          status: "queued",
          scope,
          generationModelProfile: current.generationModelProfile,
          maxComments,
          progress: {
            filesDone: 0,
            total: syncData.counts.files,
            stage: "overview",
            stageProgress: { done: 0, total: 1 },
          },
          summary: {
            totalSuggestions: 0,
            partialFailures: 0,
            filesSkipped: 0,
            warnings: [],
          },
          errorMessage: null,
          createdAt: bootStartedAt,
          updatedAt: bootStartedAt,
        },
        jobEvents: [
          {
            id: `local-${crypto.randomUUID()}`,
            jobId: pendingJobId,
            level: "info",
            message: "Запрос на создание job отправлен. Backend формирует снимок и запускает анализ.",
            filePath: null,
            stage: "overview",
            meta: {
              files: syncData.counts.files,
              scope,
            },
            createdAt: bootStartedAt,
          },
        ],
      }));

      try {
        await runTask("Задача анализа создана", async () => {
          const api = apiFactory();
          const current = stateRef.current.reviewWorkspaces[reviewKey] ?? createDefaultReviewWorkspaceFromKey(reviewKey);
          const created = await api.createAnalysisJob(syncData.prId, {
            snapshotId: syncData.snapshotId,
            scope,
            maxComments,
            modelProfile: current.generationModelProfile,
          });

          const fresh = await api.getAnalysisJob(created.jobId);
          upsertReviewWorkspace(reviewKey, (current) => ({
            ...current,
            generationModelProfile: fresh.generationModelProfile ?? current.generationModelProfile,
            job: fresh,
            jobBooting: false,
            jobBootStartedAt: null,
            activeStep: "job",
            lastTouchedAt: new Date().toISOString(),
          }));

          await loadJobEventsInternal(reviewKey, fresh.id);

          if (fresh.status === "done") {
            await loadSuggestionsInternal(reviewKey, fresh.id);
          }
        });
      } catch (error) {
        const message = formatUiError(error, stateRef.current.backendUrl);
        upsertReviewWorkspace(reviewKey, (current) => ({
          ...current,
          jobBooting: false,
          jobBootStartedAt: null,
          lastTouchedAt: new Date().toISOString(),
          job: current.job
            ? {
                ...current.job,
                status: "failed",
                errorMessage: message,
                updatedAt: new Date().toISOString(),
              }
            : null,
        }));
      }
    },
    [apiFactory, loadJobEventsInternal, loadSuggestionsInternal, runTask, upsertReviewWorkspace],
  );

  const actions: AppStoreActions = useMemo(
    () => ({
      setBackendUrl: (value) => {
        setState((prev) => ({ ...prev, backendUrl: value }));
      },

      setServiceToken: (value) => {
        setState((prev) => ({ ...prev, serviceToken: value }));
      },

      setGithubToken: (value) => {
        setState((prev) => ({ ...prev, githubToken: value }));
      },

      setGitlabToken: (value) => {
        setState((prev) => ({ ...prev, gitlabToken: value }));
      },

      setScmProvider: (value) => {
        setState((prev) => ({ ...prev, scmProvider: value }));
      },

      clearError: () => {
        setState((prev) => ({ ...prev, error: null }));
      },

      connectScm: async () => {
        const provider = stateRef.current.scmProvider;
        const token = (provider === "gitlab" ? stateRef.current.gitlabToken : stateRef.current.githubToken).trim();
        if (!token) {
          setState((prev) => ({ ...prev, error: provider === "gitlab" ? "Требуется GitLab токен" : "Требуется GitHub токен" }));
          return false;
        }

        await runTask(`${provider === "gitlab" ? "GitLab" : "GitHub"} сессия создана`, async () => {
          const api = apiFactory();
          const session = provider === "gitlab" ? await api.createGitlabSession(token) : await api.createGithubSession(token);
          resetWorkspacePreferences();

          setState((prev) => ({
            ...prev,
            session,
            repos: [],
            repoCursor: null,
            selectedRepoId: null,
            repoBrowsers: {},
            reviewWorkspaces: {},
          }));

          await loadReposInternal(session.sessionId, session.provider, true);
        });

        return true;
      },

      disconnectScm: async () => {
        const current = stateRef.current;
        if (!current.session) {
          return;
        }

        await runTask(`${current.session!.provider === "gitlab" ? "GitLab" : "GitHub"} сессия удалена`, async () => {
          const api = apiFactory();
          if (current.session!.provider === "gitlab") {
            await api.deleteGitlabSession(current.session!.sessionId);
          } else {
            await api.deleteGithubSession(current.session!.sessionId);
          }
          resetWorkspacePreferences();

          setState((prev) => ({
            ...prev,
            session: null,
            repos: [],
            repoCursor: null,
            selectedRepoId: null,
            repoBrowsers: {},
            reviewWorkspaces: {},
          }));
        });
      },

      checkBackendHealth: async () => {
        const { backendUrl } = stateRef.current;
        try {
          const response = await fetch(`${backendUrl}/healthz`);
          if (!response.ok) {
            return { ok: false, status: `${response.status}` };
          }
          return { ok: true, status: "ok" };
        } catch {
          return { ok: false, status: "unreachable" };
        }
      },

      loadRepos: async (reset = false) => {
        const session = stateRef.current.session;
        if (!session?.sessionId) {
          setState((prev) => ({ ...prev, error: "Нет активной SCM-сессии" }));
          return;
        }

        await runTask("Репозитории загружены", async () => {
          await loadReposInternal(session.sessionId, session.provider, reset);
        });
      },

      selectRepo: (repoId) => {
        selectRepoInternal(repoId);
      },

      runDebugSuite: async () => {
        if (!stateRef.current.debugSuiteEnabled) {
          return;
        }

        const sessionId = stateRef.current.session?.sessionId;
        if (!sessionId) {
          setState((prev) => ({ ...prev, error: "Нет активной SCM-сессии" }));
          return;
        }

        const presets = DEBUG_PR_PRESETS;
        const invalidPreset = presets.find(
          (preset) =>
            preset.owner.trim().length === 0 ||
            preset.repo.trim().length === 0 ||
            preset.repo.includes("REPLACE_ME") ||
            preset.prNumber <= 0,
        );
        if (invalidPreset) {
          setState((prev) => ({
            ...prev,
            error: "Debug presets не настроены. Открой frontend/src/debug/presets.ts и замени owner/repo/prNumber.",
          }));
          return;
        }

        busyCounterRef.current += 1;
        setBusy(true);
        setState((prev) => ({
          ...prev,
          error: null,
          debugSuite: {
            running: true,
            items: presets.map((preset) => ({
              presetId: preset.id,
              label: preset.label,
              owner: preset.owner,
              repo: preset.repo,
              prNumber: preset.prNumber,
              repoId: null,
              jobId: null,
              status: "pending" as const,
              suggestions: null,
              error: null,
              startedAt: null,
              finishedAt: null,
            })),
          },
        }));

        const updateItem = (presetId: string, patch: Partial<AppState["debugSuite"]["items"][number]>) => {
          setState((prev) => ({
            ...prev,
            debugSuite: {
              ...prev.debugSuite,
              items: prev.debugSuite.items.map((item) => (item.presetId === presetId ? { ...item, ...patch } : item)),
            },
          }));
        };

        const api = apiFactory();

        try {
          for (const preset of presets) {
            updateItem(preset.id, {
              status: "running",
              startedAt: new Date().toISOString(),
              finishedAt: null,
              error: null,
              suggestions: null,
              jobId: null,
              repoId: null,
            });
            pushActivity(`[debug] start ${preset.owner}/${preset.repo}#${preset.prNumber}`);

            try {
              const repo = await ensureRepoLoaded(sessionId, stateRef.current.session?.provider ?? "github", preset.owner, preset.repo);
              const reviewKey = getReviewKey(repo.repoId, preset.prNumber);
              selectRepoInternal(repo.repoId);
              upsertRepoBrowser(repo.repoId, (browser) => ({
                ...browser,
                selectedPrNumber: preset.prNumber,
              }));

              const session = stateRef.current.session;
              const sync = session?.provider === "gitlab"
                ? await api.syncGitlabMr(sessionId, String(repo.providerRepoId), preset.prNumber)
                : await api.syncGithubPr(sessionId, repo.owner, repo.name, preset.prNumber);

              upsertReviewWorkspace(reviewKey, (workflow) => ({
                ...workflow,
                prNumber: preset.prNumber,
                syncData: sync,
                activeStep: "job",
                job: null,
                jobBooting: false,
                jobBootStartedAt: null,
                jobEvents: [],
                suggestions: [],
                selectedSuggestionIds: [],
                activeSuggestionId: null,
                publishResult: null,
                comments: [],
                feedbackSummary: null,
                lastTouchedAt: new Date().toISOString(),
              }));

              const scope = (preset.scope?.length ? preset.scope : ["bugs", "security"]) as SuggestionScope[];
              const maxComments = preset.maxComments ?? 40;

              const created = await api.createAnalysisJob(sync.prId, {
                snapshotId: sync.snapshotId,
                scope,
                maxComments,
                modelProfile: "yandexgpt-pro",
              });

              updateItem(preset.id, { repoId: repo.repoId, jobId: created.jobId });

              const fresh = await api.getAnalysisJob(created.jobId);
              upsertReviewWorkspace(reviewKey, (workflow) => ({
                ...workflow,
                generationModelProfile: fresh.generationModelProfile ?? workflow.generationModelProfile,
                job: fresh,
                activeStep: "job",
                lastTouchedAt: new Date().toISOString(),
              }));

              const deadline = Date.now() + 15 * 60 * 1000;
              let current = fresh;

              while (Date.now() < deadline) {
                if (current.status === "done" || current.status === "failed" || current.status === "canceled") {
                  break;
                }

                await sleep(2000);
                current = await api.getAnalysisJob(created.jobId);
                upsertReviewWorkspace(reviewKey, (workflow) => ({
                  ...workflow,
                  generationModelProfile: current.generationModelProfile ?? workflow.generationModelProfile,
                  job: current,
                  lastTouchedAt: new Date().toISOString(),
                }));
              }

              if (current.status !== "done" && current.status !== "failed" && current.status !== "canceled") {
                throw new Error("Timeout ожидания завершения job (15m).");
              }

              await loadJobEventsInternal(reviewKey, current.id);
              if (current.status === "done") {
                await loadSuggestionsInternal(reviewKey, current.id);
              }

              updateItem(preset.id, {
                status: current.status === "done" ? "done" : "failed",
                suggestions: current.summary.totalSuggestions ?? 0,
                finishedAt: new Date().toISOString(),
              });

              pushActivity(
                `[debug] ${current.status} ${preset.owner}/${preset.repo}#${preset.prNumber} suggestions=${current.summary.totalSuggestions ?? 0}`,
              );
            } catch (error) {
              const message = formatUiError(error, stateRef.current.backendUrl);
              updateItem(preset.id, {
                status: "failed",
                error: message,
                finishedAt: new Date().toISOString(),
              });
              pushActivity(`[debug] failed ${preset.owner}/${preset.repo}#${preset.prNumber}: ${message}`);
            }
          }
        } finally {
          setState((prev) => ({
            ...prev,
            debugSuite: {
              ...prev.debugSuite,
              running: false,
            },
          }));

          busyCounterRef.current = Math.max(0, busyCounterRef.current - 1);
          if (busyCounterRef.current === 0) {
            setBusy(false);
          }
        }
      },

      setPrState: (repoId, value) => {
        upsertRepoBrowser(repoId, (browser) => ({ ...browser, prState: value }));
      },

      setPrSearch: (repoId, value) => {
        upsertRepoBrowser(repoId, (browser) => ({ ...browser, prSearch: value }));
      },

      loadPullRequests: async (repoId) => {
        const session = stateRef.current.session;
        const repo = stateRef.current.repos.find((item) => item.repoId === repoId);
        const browser = stateRef.current.repoBrowsers[repoId] ?? createDefaultRepoBrowser(repoId, workspacePreferencesRef.current[repoId]);

        if (!session || !repo) {
          setState((prev) => ({ ...prev, error: "Сначала подключите SCM и выберите репозиторий" }));
          return;
        }

        await runTask(`PR загружены (${repo.fullName})`, async () => {
          const api = apiFactory();
          const response = session.provider === "gitlab"
            ? await api.getGitlabMrs(session.sessionId, String(repo.providerRepoId), browser.prState)
            : await api.getGithubPrs(session.sessionId, repo.owner, repo.name, browser.prState);

          upsertRepoBrowser(repoId, (current) => ({
            ...current,
            prs: response.items,
            selectedPrNumber: current.selectedPrNumber && response.items.some((pr) => pr.number === current.selectedPrNumber)
              ? current.selectedPrNumber
              : response.items[0]?.number ?? null,
          }));
        });
      },

      selectPullRequest: (repoId, prNumber) => {
        upsertRepoBrowser(repoId, (browser) => ({ ...browser, selectedPrNumber: prNumber }));
        if (prNumber !== null) {
          const reviewKey = getReviewKey(repoId, prNumber);
          const existing = stateRef.current.reviewWorkspaces[reviewKey];
          const nextStep = deriveWorkspaceLandingStep(existing);
          upsertReviewWorkspace(reviewKey, (workflow) => ({
            ...workflow,
            repoId,
            prNumber,
            activeStep: nextStep,
            lastTouchedAt: workflow.syncData || workflow.job ? new Date().toISOString() : workflow.lastTouchedAt,
          }));
        }
      },

      syncPullRequest: async (repoId) => {
        const session = stateRef.current.session;
        const repo = stateRef.current.repos.find((item) => item.repoId === repoId);
        const { prNumber, reviewKey, review } = getCurrentReviewContext(repoId);

        if (!session || !repo || !prNumber || !reviewKey) {
          setState((prev) => ({ ...prev, error: "Сначала выберите репозиторий и PR" }));
          return;
        }

        await runTask(`PR синхронизирован (${repo.fullName}#${prNumber})`, async () => {
          const api = apiFactory();
          const sync = session.provider === "gitlab"
            ? await api.syncGitlabMr(session.sessionId, String(repo.providerRepoId), prNumber)
            : await api.syncGithubPr(session.sessionId, repo.owner, repo.name, prNumber);

          upsertReviewWorkspace(reviewKey, (current) => ({
            ...current,
            repoId,
            prNumber,
            syncData: sync,
            activeStep: "pr",
            job: null,
            jobBooting: false,
            jobBootStartedAt: null,
            jobEvents: [],
            suggestions: [],
            selectedSuggestionIds: [],
            activeSuggestionId: null,
            publishResult: null,
            comments: [],
            feedbackSummary: null,
            lastTouchedAt: new Date().toISOString(),
            maxComments: review.maxComments,
          }));
        });
      },

      analyzePullRequest: async (repoId) => {
        const session = stateRef.current.session;
        const repo = stateRef.current.repos.find((item) => item.repoId === repoId);
        const { prNumber, reviewKey, review } = getCurrentReviewContext(repoId);

        if (!session || !repo || !prNumber || !reviewKey) {
          setState((prev) => ({ ...prev, error: "Сначала выберите репозиторий и PR" }));
          return;
        }

        const scope = ANALYSIS_SCOPES.filter((item) => review.scope[item]);
        if (scope.length === 0) {
          setState((prev) => ({ ...prev, error: "Выберите хотя бы одну область анализа" }));
          return;
        }

        const sync = await runTask(`Подготовлен snapshot для ${repo.fullName}#${prNumber}`, async () => {
          const api = apiFactory();
          const response = session.provider === "gitlab"
            ? await api.syncGitlabMr(session.sessionId, String(repo.providerRepoId), prNumber)
            : await api.syncGithubPr(session.sessionId, repo.owner, repo.name, prNumber);

          upsertReviewWorkspace(reviewKey, (current) => ({
            ...current,
            repoId,
            prNumber,
            syncData: response,
            activeStep: "job",
            job: null,
            jobBooting: false,
            jobBootStartedAt: null,
            jobEvents: [],
            suggestions: [],
            selectedSuggestionIds: [],
            activeSuggestionId: null,
            publishResult: null,
            comments: [],
            feedbackSummary: null,
            lastTouchedAt: new Date().toISOString(),
          }));

          return response;
        });

        await startAnalysisJobInternal(reviewKey, sync, scope, review.maxComments);
      },

      setActiveStep: (repoId, step) => {
        const { review } = getCurrentReviewContext(repoId);
        const canOpen = canOpenStepWithWorkflow(review, step);
        if (!canOpen) {
          return;
        }

        if (review.prNumber === null) {
          return;
        }

        upsertReviewWorkspace(getReviewKey(repoId, review.prNumber), (workflow) => ({
          ...workflow,
          activeStep: step,
        }));
      },

      setMaxComments: (repoId, value) => {
        const next = Number.isFinite(value) ? Math.max(1, Math.min(500, Math.floor(value))) : 30;
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, maxComments: next }));
      },

      setMinSeverity: (repoId, value) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, minSeverity: value }));
      },

      setFileFilter: (repoId, value) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, fileFilter: value }));
      },

      toggleScope: (repoId, scope) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({
          ...workflow,
          scope: {
            ...workflow.scope,
            [scope]: !workflow.scope[scope],
          },
        }));
      },

      setGenerationModelProfile: (repoId, value) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({
          ...workflow,
          generationModelProfile: value,
        }));
      },

      createAnalysisJob: async (repoId) => {
        const { reviewKey, review } = getCurrentReviewContext(repoId);
        if (!reviewKey || !review.syncData) {
          setState((prev) => ({ ...prev, error: "Сначала выполните синхронизацию PR" }));
          return;
        }

        const scope = ANALYSIS_SCOPES.filter((item) => review.scope[item]);
        if (scope.length === 0) {
          setState((prev) => ({ ...prev, error: "Выберите хотя бы одну область анализа" }));
          return;
        }

        await startAnalysisJobInternal(reviewKey, review.syncData, scope, review.maxComments);
      },

      refreshJob: async (repoId) => {
        const { reviewKey, review } = getCurrentReviewContext(repoId);
        if (!reviewKey || !review.job || review.job.id.startsWith("pending-")) {
          return;
        }
        const job = review.job;

        await runTask("Состояние задачи обновлено", async () => {
          const api = apiFactory();
          const fresh = await api.getAnalysisJob(job.id);

          upsertReviewWorkspace(reviewKey, (current) => ({
            ...current,
            generationModelProfile: fresh.generationModelProfile ?? current.generationModelProfile,
            job: fresh,
            jobBooting: false,
            jobBootStartedAt: null,
            lastTouchedAt: new Date().toISOString(),
          }));
          await loadJobEventsInternal(reviewKey, fresh.id);

          if (fresh.status === "done") {
            await loadSuggestionsInternal(reviewKey, fresh.id);
          }
        });
      },

      cancelJob: async (repoId) => {
        const { reviewKey, review } = getCurrentReviewContext(repoId);
        if (!reviewKey || !review.job || review.job.id.startsWith("pending-")) {
          return;
        }
        const job = review.job;

        await runTask("Задача анализа отменена", async () => {
          const api = apiFactory();
          const canceled = await api.cancelAnalysisJob(job.id);
          upsertReviewWorkspace(reviewKey, (current) => ({
            ...current,
            job: canceled,
            jobBooting: false,
            jobBootStartedAt: null,
            lastTouchedAt: new Date().toISOString(),
          }));
          await loadJobEventsInternal(reviewKey, canceled.id);
        });
      },

      loadJobEvents: async (repoId) => {
        const { reviewKey, review } = getCurrentReviewContext(repoId);
        if (!reviewKey || !review.job || review.job.id.startsWith("pending-")) {
          return;
        }
        const job = review.job;

        await runTask("Лента событий обновлена", async () => {
          await loadJobEventsInternal(reviewKey, job.id);
        });
      },

      setSuggestionSearch: (repoId, value) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, suggestionSearch: value }));
      },

      setSuggestionCategoryFilter: (repoId, value) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, suggestionCategoryFilter: value }));
      },

      setSeverityFilter: (repoId, value) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, severityFilter: value }));
      },

      toggleSuggestionSelection: (repoId, suggestionId) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => {
          const selectedSuggestionIds = workflow.selectedSuggestionIds.includes(suggestionId)
            ? workflow.selectedSuggestionIds.filter((id) => id !== suggestionId)
            : [...workflow.selectedSuggestionIds, suggestionId];

          return {
            ...workflow,
            selectedSuggestionIds,
          };
        });
      },

      setActiveSuggestion: (repoId, suggestionId) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, activeSuggestionId: suggestionId }));
      },

      selectAllSuggestions: (repoId) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({
          ...workflow,
          selectedSuggestionIds: workflow.suggestions.map((item) => item.id),
        }));
      },

      clearSuggestionSelection: (repoId) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, selectedSuggestionIds: [] }));
      },

      reloadSuggestions: async (repoId) => {
        const { reviewKey, review } = getCurrentReviewContext(repoId);
        if (!reviewKey || !review.job) {
          return;
        }
        const job = review.job;

        await runTask("Рекомендации обновлены", async () => {
          await loadSuggestionsInternal(reviewKey, job.id);
        });
      },

      setPublishMode: (repoId, mode) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, publishMode: mode }));
      },

      setDryRun: (repoId, dryRun) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, dryRun }));
      },

      publishSuggestions: async (repoId) => {
        const { reviewKey, review } = getCurrentReviewContext(repoId);
        if (!reviewKey || !review.job) {
          setState((prev) => ({ ...prev, error: "Сначала запустите анализ" }));
          return;
        }
        const job = review.job;

        const prId = review.syncData?.prId ?? job.prId;

        await runTask(`Публикация запрошена (dryRun=${String(review.dryRun)})`, async () => {
          const api = apiFactory();
          const response = await api.publishSuggestions(prId, {
            jobId: job.id,
            mode: review.publishMode,
            dryRun: review.dryRun,
            sessionId: stateRef.current.session?.sessionId,
          });

          upsertReviewWorkspace(reviewKey, (current) => ({
            ...current,
            publishResult: {
              publishRunId: response.publishRunId,
              publishedCount: response.publishedCount,
              idempotent: response.idempotent,
              errors: response.errors,
            },
            comments: response.comments,
            lastTouchedAt: new Date().toISOString(),
            activeStep: current.dryRun ? "publish" : "feedback",
          }));

          if (!review.dryRun) {
            await loadCommentsInternal(reviewKey, prId);
            await loadFeedbackSummaryInternal(reviewKey, prId);
          }
        });
      },

      loadComments: async (repoId) => {
        const { reviewKey, review } = getCurrentReviewContext(repoId);
        const prId = review.syncData?.prId ?? review.job?.prId;
        if (!prId) {
          setState((prev) => ({ ...prev, error: "Нет связанного PR" }));
          return;
        }

        await runTask("Комментарии PR обновлены", async () => {
          if (reviewKey) {
            await loadCommentsInternal(reviewKey, prId);
          }
        });
      },

      setFeedbackUserId: (repoId, userId) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, feedbackUserId: userId }));
      },

      setFeedbackReason: (repoId, reason) => {
        const { prNumber } = getCurrentReviewContext(repoId);
        if (prNumber === null) {
          return;
        }
        upsertReviewWorkspace(getReviewKey(repoId, prNumber), (workflow) => ({ ...workflow, feedbackReason: reason }));
      },

      voteComment: async (repoId, commentId, vote) => {
        const { reviewKey, review } = getCurrentReviewContext(repoId);
        const userId = review.feedbackUserId?.trim();
        const prId = review.syncData?.prId ?? review.job?.prId;

        if (!reviewKey || !userId || !prId) {
          setState((prev) => ({ ...prev, error: "Нужен ID пользователя и связанный PR" }));
          return;
        }

        await runTask(`Голос отправлен (${vote === "up" ? "полезно" : "неполезно"})`, async () => {
          const api = apiFactory();
          await api.putFeedback(commentId, {
            userId,
            vote,
            reason: review.feedbackReason.trim() || undefined,
          });

          await loadFeedbackSummaryInternal(reviewKey, prId);
        });
      },

      loadFeedbackSummary: async (repoId) => {
        const { reviewKey, review } = getCurrentReviewContext(repoId);
        const prId = review.syncData?.prId ?? review.job?.prId;
        if (!prId) {
          setState((prev) => ({ ...prev, error: "Нет связанного PR" }));
          return;
        }

        await runTask("Сводка фидбека обновлена", async () => {
          if (reviewKey) {
            await loadFeedbackSummaryInternal(reviewKey, prId);
          }
        });
      },

      loadRepoRuns: async (repoId, reset = true) => {
        const { prNumber, reviewKey, review } = getCurrentReviewContext(repoId);
        const cursor = reset ? null : review.runsCursor ?? null;

        await runTask("История запусков обновлена", async () => {
          const api = apiFactory();

          try {
            const page = await api.getRepoRuns(repoId, cursor);
            if (!reviewKey && prNumber === null) {
              const fallbackPrNumber = page.items[0]?.prNumber ?? null;
              if (fallbackPrNumber !== null) {
                upsertRepoBrowser(repoId, (browser) => ({ ...browser, selectedPrNumber: fallbackPrNumber }));
              }
            }
            const targetPrNumber = prNumber ?? page.items[0]?.prNumber ?? null;
            if (targetPrNumber === null) {
              return;
            }
            upsertReviewWorkspace(getReviewKey(repoId, targetPrNumber), (workflow) => ({
              ...workflow,
              runs: reset ? page.items : [...workflow.runs, ...page.items],
              runsCursor: page.nextCursor,
              historyIsMock: false,
            }));
          } catch (_error) {
            const targetPrNumber = prNumber ?? review.prNumber;
            if (targetPrNumber === null) {
              return;
            }
            const fallbackRuns = createMockRunsFromWorkflow(stateRef.current.reviewWorkspaces[getReviewKey(repoId, targetPrNumber)]);
            upsertReviewWorkspace(getReviewKey(repoId, targetPrNumber), (workflow) => ({
              ...workflow,
              runs: fallbackRuns,
              runsCursor: null,
              historyIsMock: true,
            }));
          }
        });
      },

      reopenRun: async (repoId, run) => {
        await runTask(`Открыт запуск ${run.runId}`, async () => {
          const api = apiFactory();
          const job = await api.getAnalysisJob(run.jobId);
          const prMeta = await api.getPr(job.prId);
          const selectedPrNumber = prMeta.pr.number;
          const reviewKey = getReviewKey(repoId, selectedPrNumber);

          upsertRepoBrowser(repoId, (browser) => {
            const existingPr = browser.prs.find((pr) => pr.number === selectedPrNumber);
            const prs = existingPr
              ? browser.prs
              : [
                  ...browser.prs,
                  {
                    number: prMeta.pr.number,
                    title: prMeta.pr.title,
                    state: prMeta.pr.state === "merged" ? "closed" : prMeta.pr.state,
                    url: prMeta.pr.url,
                    authorLogin: prMeta.pr.authorLogin,
                    baseSha: prMeta.pr.baseSha,
                    headSha: prMeta.pr.headSha,
                    updatedAt: prMeta.pr.updatedAt,
                  },
                ];

            return {
              ...browser,
              prs,
              selectedPrNumber,
            };
          });

          upsertReviewWorkspace(reviewKey, (workflow) => ({
            ...workflow,
            repoId,
            prNumber: selectedPrNumber,
            generationModelProfile: job.generationModelProfile ?? workflow.generationModelProfile,
            syncData: {
              repoId,
              prId: prMeta.pr.id,
              snapshotId: job.snapshotId,
              counts: {
                files: prMeta.latestSnapshot?.filesCount ?? 0,
                additions: prMeta.latestSnapshot?.additions ?? 0,
                deletions: prMeta.latestSnapshot?.deletions ?? 0,
              },
              idempotent: true,
              source: "history",
            },
            job,
            activeStep: "results",
            lastTouchedAt: new Date().toISOString(),
          }));

          await loadJobEventsInternal(reviewKey, job.id);
          await loadSuggestionsInternal(reviewKey, job.id);
          await loadCommentsInternal(reviewKey, job.prId);
          await loadFeedbackSummaryInternal(reviewKey, job.prId);
        });
      },
    }),
    [
      apiFactory,
      loadCommentsInternal,
      loadFeedbackSummaryInternal,
      loadJobEventsInternal,
      loadReposInternal,
      loadSuggestionsInternal,
      ensureRepoLoaded,
      getCurrentReviewContext,
      resetWorkspacePreferences,
      runTask,
      sleep,
      selectRepoInternal,
      startAnalysisJobInternal,
      upsertRepoBrowser,
      upsertReviewWorkspace,
    ],
  );

  const value: AppStoreValue = useMemo(
    () => ({
      ...state,
      recentReviews: buildRecentReviews(state.reviewWorkspaces, state.repoBrowsers, state.repos),
      actions,
      getWorkflow: (repoId) => {
        if (!repoId) {
          return null;
        }
        const browser = state.repoBrowsers[repoId] ?? createDefaultRepoBrowser(repoId, workspacePreferencesRef.current[repoId]);
        if (browser.selectedPrNumber === null) {
          return createDefaultReviewWorkspace(repoId, null);
        }
        return state.reviewWorkspaces[getReviewKey(repoId, browser.selectedPrNumber)] ?? createDefaultReviewWorkspace(repoId, browser.selectedPrNumber);
      },
      getRepoBrowser: (repoId) => {
        if (!repoId) {
          return null;
        }
        return state.repoBrowsers[repoId] ?? createDefaultRepoBrowser(repoId, workspacePreferencesRef.current[repoId]);
      },
      getSelectedRepo: () => {
        const currentRepoId = state.selectedRepoId;
        if (!currentRepoId) {
          return null;
        }
        return state.repos.find((repo) => repo.repoId === currentRepoId) ?? null;
      },
      getRepoStatus: (repoId) => {
        const browser = state.repoBrowsers[repoId] ?? createDefaultRepoBrowser(repoId, workspacePreferencesRef.current[repoId]);
        const workflow = browser.selectedPrNumber !== null
          ? state.reviewWorkspaces[getReviewKey(repoId, browser.selectedPrNumber)]
          : undefined;
        return deriveRepoStatus(workflow);
      },
      canOpenStep: (repoId, step) => {
        const browser = state.repoBrowsers[repoId] ?? createDefaultRepoBrowser(repoId, workspacePreferencesRef.current[repoId]);
        const workflow = browser.selectedPrNumber !== null
          ? state.reviewWorkspaces[getReviewKey(repoId, browser.selectedPrNumber)]
          : undefined;
        return canOpenStepWithWorkflow(workflow, step);
      },
    }),
    [actions, state],
  );

  return <AppStoreContext.Provider value={value}>{children}</AppStoreContext.Provider>;
}

export function useAppStore() {
  const context = useContext(AppStoreContext);
  if (!context) {
    throw new Error("useAppStore must be used within AppStoreProvider");
  }
  return context;
}

function getReviewKey(repoId: string, prNumber: number): string {
  return `${repoId}:${prNumber}`;
}

function parseReviewKey(reviewKey: string): { repoId: string; prNumber: number | null } {
  const [repoId, rawPrNumber] = reviewKey.split(":");
  const prNumber = rawPrNumber ? Number(rawPrNumber) : Number.NaN;
  return {
    repoId: repoId ?? "",
    prNumber: Number.isFinite(prNumber) ? prNumber : null,
  };
}

function createDefaultRepoBrowser(repoId: string, persisted?: PersistedWorkspacePreference): RepoBrowserState {
  return {
    repoId,
    prState: persisted?.prState ?? "open",
    prSearch: "",
    prs: [],
    selectedPrNumber: persisted?.selectedPrNumber ?? null,
  };
}

function createDefaultReviewWorkspace(repoId: string, prNumber: number | null): ReviewWorkspaceState {
  return {
    repoId,
    prNumber,
    syncData: null,
    scope: {
      security: true,
      bugs: true,
      style: false,
      performance: false,
    },
    generationModelProfile: "yandexgpt-pro",
    maxComments: 30,
    minSeverity: "none",
    fileFilter: "",
    job: null,
    jobBooting: false,
    jobBootStartedAt: null,
    jobEvents: [],
    suggestions: [],
    suggestionSearch: "",
    suggestionCategoryFilter: "all",
    severityFilter: "all",
    selectedSuggestionIds: [],
    activeSuggestionId: null,
    publishMode: "review_comments",
    dryRun: true,
    publishResult: null,
    comments: [],
    feedbackSummary: null,
    feedbackUserId: "dev_local",
    feedbackReason: "полезно",
    runs: [],
    runsCursor: null,
    historyIsMock: false,
    activeStep: "pr",
    lastTouchedAt: null,
  };
}

function createDefaultReviewWorkspaceFromKey(reviewKey: string): ReviewWorkspaceState {
  const { repoId, prNumber } = parseReviewKey(reviewKey);
  return createDefaultReviewWorkspace(repoId, prNumber);
}

function deriveRepoStatus(workflow: ReviewWorkspaceState | undefined): { label: string; tone: "ok" | "warn" | "muted" } {
  if (!workflow) {
    return { label: "нет PR", tone: "muted" };
  }

  if (workflow.jobBooting) {
    return { label: "анализ стартует", tone: "warn" };
  }

  if (workflow.job && (workflow.job.status === "queued" || workflow.job.status === "running")) {
    return { label: "идет анализ", tone: "ok" };
  }

  if (workflow.syncData && !workflow.job) {
    return { label: "готов к анализу", tone: "ok" };
  }

  if (workflow.job?.status === "done") {
    return { label: "есть результаты", tone: "ok" };
  }

  return { label: "нет PR", tone: "muted" };
}

function canOpenStepWithWorkflow(workflow: ReviewWorkspaceState | undefined, step: WorkspaceStep): boolean {
  if (!workflow) {
    return step === "pr";
  }

  if (step === "pr") {
    return true;
  }

  if (step === "job") {
    return Boolean(workflow.syncData);
  }

  if (step === "results") {
    return Boolean(workflow.job && !workflow.jobBooting);
  }

  if (step === "publish") {
    return Boolean(
      workflow.job?.status === "done"
      && workflow.suggestions.some((item) => (item.deliveryMode ?? "inline") === "inline"),
    );
  }

  if (step === "feedback") {
    const publishedCount = workflow.publishResult?.publishedCount ?? 0;
    return workflow.comments.length > 0 || publishedCount > 0;
  }

  if (step === "history") {
    return true;
  }

  return false;
}

function buildRecentReviews(
  reviewWorkspaces: Record<string, ReviewWorkspaceState>,
  repoBrowsers: Record<string, RepoBrowserState>,
  repos: GithubRepo[],
): RecentReviewItem[] {
  return Object.entries(reviewWorkspaces)
    .filter(([, workflow]) => Boolean(workflow.syncData || workflow.job || workflow.publishResult))
    .sort((a, b) => {
      const aTouched = new Date(a[1].lastTouchedAt ?? a[1].job?.updatedAt ?? 0).getTime();
      const bTouched = new Date(b[1].lastTouchedAt ?? b[1].job?.updatedAt ?? 0).getTime();
      return bTouched - aTouched;
    })
    .slice(0, 8)
    .map(([reviewKey, workflow]) => {
      const repo = repos.find((item) => item.repoId === workflow.repoId);
      const browser = repoBrowsers[workflow.repoId];
      const prTitle = browser?.prs.find((item) => item.number === workflow.prNumber)?.title ?? `PR #${workflow.prNumber ?? "?"}`;

      return {
        reviewKey,
        repoId: workflow.repoId,
        prNumber: workflow.prNumber ?? 0,
        repoFullName: repo?.fullName ?? workflow.repoId,
        prTitle,
        status: deriveRecentReviewStatus(workflow),
        lastOpenedAt: workflow.lastTouchedAt ?? workflow.job?.updatedAt ?? new Date().toISOString(),
      };
    });
}

function deriveRecentReviewStatus(workflow: ReviewWorkspaceState): RecentReviewItem["status"] {
  if (workflow.publishResult && (workflow.publishResult.publishedCount > 0 || workflow.comments.length > 0)) {
    return "published";
  }
  if (workflow.jobBooting || workflow.job?.status === "queued" || workflow.job?.status === "running") {
    return "running";
  }
  if (workflow.job?.status === "done" || workflow.suggestions.length > 0) {
    return "results";
  }
  return "ready";
}

function deriveWorkspaceLandingStep(workflow: ReviewWorkspaceState | undefined): WorkspaceStep {
  if (!workflow) {
    return "pr";
  }

  if (workflow.jobBooting || workflow.job?.status === "queued" || workflow.job?.status === "running" || workflow.job?.status === "failed" || workflow.job?.status === "canceled") {
    return "job";
  }

  if (workflow.job?.status === "done" || workflow.suggestions.length > 0 || workflow.publishResult || workflow.comments.length > 0) {
    return "results";
  }

  return "pr";
}

function loadWorkspacePreferences(): Record<string, PersistedWorkspacePreference> {
  if (typeof window === "undefined") {
    return {};
  }

  try {
    const raw = window.localStorage.getItem(WORKSPACE_PREFERENCES_KEY);
    if (!raw) {
      return {};
    }

    const parsed = JSON.parse(raw) as Record<string, { selectedPrNumber?: unknown; activeStep?: unknown; prState?: unknown }>;
    if (!parsed || typeof parsed !== "object") {
      return {};
    }

    const normalized: Record<string, PersistedWorkspacePreference> = {};
    for (const [repoId, value] of Object.entries(parsed)) {
      normalized[repoId] = {
        selectedPrNumber: typeof value?.selectedPrNumber === "number" ? value.selectedPrNumber : null,
        activeStep: normalizeWorkspaceStep(value?.activeStep),
        prState: normalizePrState(value?.prState),
      };
    }

    return normalized;
  } catch {
    return {};
  }
}

function persistWorkspacePreferences(preferences: Record<string, PersistedWorkspacePreference>) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(WORKSPACE_PREFERENCES_KEY, JSON.stringify(preferences));
}

function clearWorkspacePreferences() {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(WORKSPACE_PREFERENCES_KEY);
}

function createMockEvents(job: AnalysisJob | null | undefined): AnalysisJobEvent[] {
  const now = new Date().toISOString();

  if (!job) {
    return [];
  }

  return [
    {
      id: `mock_evt_${job.id}_1`,
      jobId: job.id,
      level: "info",
      message: "Подключен mock stream событий (реальный endpoint недоступен).",
      filePath: null,
      meta: null,
      stage: "overview",
      createdAt: now,
    },
    {
      id: `mock_evt_${job.id}_2`,
      jobId: job.id,
      level: job.status === "failed" ? "error" : "info",
      message: `Текущий статус: ${JOB_STATUS_LABELS[job.status]}`,
      filePath: null,
      stage: job.progress.stage ?? "review",
      meta: {
        progress: `${job.progress.filesDone}/${job.progress.total}`,
      },
      createdAt: now,
    },
  ];
}

function createMockRunsFromWorkflow(workflow: ReviewWorkspaceState | undefined): RepoRunSummary[] {
  if (!workflow?.job) {
    return [];
  }

  return [
    {
      runId: workflow.job.id,
      jobId: workflow.job.id,
      repoId: workflow.repoId,
      repoFullName: workflow.repoId,
      prId: workflow.job.prId,
      prNumber: workflow.prNumber ?? 0,
      prTitle: `PR #${workflow.prNumber ?? "?"}`,
      status: workflow.job.status,
      totalSuggestions: workflow.suggestions.length,
      publishedComments: workflow.comments.length,
      feedbackScore: workflow.feedbackSummary?.overall.score ?? 0,
      createdAt: workflow.job.createdAt,
      updatedAt: workflow.job.updatedAt,
    },
  ];
}

function formatUiError(error: unknown, backendUrl: string): string {
  const message = error instanceof Error ? error.message : "Неизвестная ошибка";

  if (message === "Failed to fetch" || message === "Load failed" || message.includes("NetworkError")) {
    return `Не удалось подключиться к backend (${backendUrl}). Проверьте, что backend запущен и доступен.`;
  }

  if (message.includes("Unauthorized") || message.includes("Invalid or missing service token")) {
    return "Ошибка авторизации backend: проверьте API Service Token.";
  }

  return message;
}

function normalizeWorkspaceStep(value: unknown): WorkspaceStep {
  if (value === "job" || value === "results" || value === "publish" || value === "feedback" || value === "history") {
    return value;
  }
  return "pr";
}

function normalizePrState(value: unknown): "open" | "closed" | "all" {
  if (value === "open" || value === "closed" || value === "all") {
    return value;
  }
  return "open";
}
