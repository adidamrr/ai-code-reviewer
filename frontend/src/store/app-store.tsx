import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ApiClient } from "../lib/api";
import { DEBUG_PR_PRESETS } from "../debug/presets";
import type {
  AnalysisJob,
  AnalysisJobEvent,
  CursorPage,
  FeedbackSummary,
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

const RECENT_REPOS_KEY = "swagreviewer_recent_repos_v1";
const WORKSPACE_PREFERENCES_KEY = "swagreviewer_repo_workspace_v1";

export const WORKSPACE_STEPS: WorkspaceStep[] = [
  "pr",
  "params",
  "job",
  "results",
  "publish",
  "feedback",
  "history",
];

export const STEP_LABELS: Record<WorkspaceStep, string> = {
  pr: "PR",
  params: "Параметры",
  job: "Job",
  results: "Результаты",
  publish: "Публикация",
  feedback: "Фидбек",
  history: "История",
};

export const ALL_SCOPES: SuggestionScope[] = ["security", "style", "bugs", "performance"];

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

interface RecentRepoItem {
  repoId: string;
  fullName: string;
  owner: string;
  name: string;
  lastOpenedAt: string;
}

interface PersistedWorkspacePreference {
  selectedPrNumber: number | null;
  activeStep: WorkspaceStep;
  prState: "open" | "closed" | "all";
}

interface RepoWorkspaceState {
  repoId: string;
  prState: "open" | "closed" | "all";
  prSearch: string;
  prs: GithubPr[];
  selectedPrNumber: number | null;

  syncData: SyncResponse | null;

  scope: Record<SuggestionScope, boolean>;
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
}

interface AppState {
  backendUrl: string;
  serviceToken: string;
  githubToken: string;
  session: GithubSession | null;

  repos: GithubRepo[];
  repoCursor: string | null;
  selectedRepoId: string | null;

  recentRepos: RecentRepoItem[];
  workflows: Record<string, RepoWorkspaceState>;

  busy: boolean;
  error: string | null;
  activity: ActivityLog[];

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

  clearError: () => void;

  connectGithub: () => Promise<boolean>;
  disconnectGithub: () => Promise<void>;
  checkBackendHealth: () => Promise<{ ok: boolean; status: string }>;

  loadRepos: (reset?: boolean) => Promise<void>;
  selectRepo: (repoId: string) => void;
  runDebugSuite: () => Promise<void>;

  setPrState: (repoId: string, value: "open" | "closed" | "all") => void;
  setPrSearch: (repoId: string, value: string) => void;
  loadPullRequests: (repoId: string) => Promise<void>;
  selectPullRequest: (repoId: string, prNumber: number | null) => void;

  syncPullRequest: (repoId: string) => Promise<void>;

  setActiveStep: (repoId: string, step: WorkspaceStep) => void;
  setMaxComments: (repoId: string, value: number) => void;
  setMinSeverity: (repoId: string, value: "none" | Suggestion["severity"]) => void;
  setFileFilter: (repoId: string, value: string) => void;
  toggleScope: (repoId: string, scope: SuggestionScope) => void;

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
  getWorkflow: (repoId: string | null | undefined) => RepoWorkspaceState | null;
  getSelectedRepo: () => GithubRepo | null;
  getRepoStatus: (repoId: string) => { label: string; tone: "ok" | "warn" | "muted" };
  canOpenStep: (repoId: string, step: WorkspaceStep) => boolean;
}

const AppStoreContext = createContext<AppStoreValue | null>(null);

const initialState: AppState = {
  backendUrl: DEFAULT_BACKEND,
  serviceToken: DEFAULT_SERVICE_TOKEN,
  githubToken: "",
  session: null,
  repos: [],
  repoCursor: null,
  selectedRepoId: null,
  recentRepos: loadRecentRepos(),
  workflows: {},
  busy: false,
  error: null,
  activity: [],
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
    persistRecentRepos(state.recentRepos);
  }, [state.recentRepos]);

  useEffect(() => {
    const payload: Record<string, PersistedWorkspacePreference> = {};
    for (const [repoId, workflow] of Object.entries(state.workflows)) {
      payload[repoId] = {
        selectedPrNumber: workflow.selectedPrNumber,
        activeStep: workflow.activeStep,
        prState: workflow.prState,
      };
    }
    workspacePreferencesRef.current = payload;
    persistWorkspacePreferences(payload);
  }, [state.workflows]);

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
    async (sessionId: string, owner: string, name: string): Promise<GithubRepo> => {
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
        const page: CursorPage<GithubRepo> = await api.getGithubRepos(sessionId, cursor);
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

  const upsertWorkflow = useCallback((repoId: string, updater: (current: RepoWorkspaceState) => RepoWorkspaceState) => {
    setState((prev) => {
      const existing = prev.workflows[repoId] ?? createDefaultWorkflow(repoId, workspacePreferencesRef.current[repoId]);
      return {
        ...prev,
        workflows: {
          ...prev.workflows,
          [repoId]: updater(existing),
        },
      };
    });
  }, []);

  const touchRecentRepo = useCallback((repo: GithubRepo) => {
    setState((prev) => {
      const now = new Date().toISOString();
      const deduped = prev.recentRepos.filter((item) => item.repoId !== repo.repoId);
      const next: RecentRepoItem[] = [
        {
          repoId: repo.repoId,
          fullName: repo.fullName,
          owner: repo.owner,
          name: repo.name,
          lastOpenedAt: now,
        },
        ...deduped,
      ].slice(0, 8);

      return {
        ...prev,
        recentRepos: next,
      };
    });
  }, []);

  const selectRepoInternal = useCallback(
    (repoId: string, repo?: GithubRepo | null) => {
      setState((prev) => {
        const nextWorkflows = prev.workflows[repoId]
          ? prev.workflows
          : {
              ...prev.workflows,
              [repoId]: createDefaultWorkflow(repoId, workspacePreferencesRef.current[repoId]),
            };

        return {
          ...prev,
          selectedRepoId: repoId,
          workflows: nextWorkflows,
        };
      });

      if (repo) {
        touchRecentRepo(repo);
      }
    },
    [touchRecentRepo],
  );

  const loadReposInternal = useCallback(
    async (sessionId: string, reset: boolean) => {
      const current = stateRef.current;
      const api = apiFactory();
      const page = await api.getGithubRepos(sessionId, reset ? null : current.repoCursor);

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
    async (repoId: string, jobId: string) => {
      const api = apiFactory();
      let cursor: string | null = null;
      const items: Suggestion[] = [];

      do {
        const page = await api.getAnalysisResults(jobId, cursor);
        items.push(...page.items);
        cursor = page.nextCursor;
      } while (cursor);

      upsertWorkflow(repoId, (workflow) => {
        const inlineIds = items.filter((item) => (item.deliveryMode ?? "inline") === "inline").map((item) => item.id);
        const selectedSuggestionIds = workflow.selectedSuggestionIds.length > 0
          ? workflow.selectedSuggestionIds.filter((id) => inlineIds.includes(id))
          : inlineIds;

        return {
          ...workflow,
          suggestions: items,
          selectedSuggestionIds,
          activeSuggestionId: workflow.activeSuggestionId && items.some((item) => item.id === workflow.activeSuggestionId)
            ? workflow.activeSuggestionId
            : items[0]?.id ?? null,
          activeStep: items.length > 0 && workflow.activeStep === "job" ? "results" : workflow.activeStep,
        };
      });

      pushActivity(`Загружено рекомендаций: ${items.length}`);
    },
    [apiFactory, pushActivity, upsertWorkflow],
  );

  const loadCommentsInternal = useCallback(
    async (repoId: string, prId: string) => {
      const api = apiFactory();
      let cursor: string | null = null;
      const all: RepoWorkspaceState["comments"] = [];

      do {
        const page = await api.getPrComments(prId, cursor);
        all.push(...page.items);
        cursor = page.nextCursor;
      } while (cursor);

      upsertWorkflow(repoId, (workflow) => ({
        ...workflow,
        comments: all,
      }));
    },
    [apiFactory, upsertWorkflow],
  );

  const loadFeedbackSummaryInternal = useCallback(
    async (repoId: string, prId: string) => {
      const api = apiFactory();
      const summary = await api.getFeedbackSummary(prId);
      upsertWorkflow(repoId, (workflow) => ({
        ...workflow,
        feedbackSummary: summary,
      }));
    },
    [apiFactory, upsertWorkflow],
  );

  const loadJobEventsInternal = useCallback(
    async (repoId: string, jobId: string) => {
      const api = apiFactory();
      let cursor: string | null = null;
      const events: AnalysisJobEvent[] = [];

      try {
        do {
          const page = await api.getAnalysisJobEvents(jobId, cursor);
          events.push(...page.items);
          cursor = page.nextCursor;
        } while (cursor);

        upsertWorkflow(repoId, (workflow) => ({ ...workflow, jobEvents: events }));
      } catch (_error) {
        const job = stateRef.current.workflows[repoId]?.job;
        const mockEvents = createMockEvents(job);
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, jobEvents: mockEvents }));
      }
    },
    [apiFactory, upsertWorkflow],
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

      clearError: () => {
        setState((prev) => ({ ...prev, error: null }));
      },

      connectGithub: async () => {
        const token = stateRef.current.githubToken.trim();
        if (!token) {
          setState((prev) => ({ ...prev, error: "Требуется GitHub токен" }));
          return false;
        }

        await runTask("GitHub сессия создана", async () => {
          const api = apiFactory();
          const session = await api.createGithubSession(token);

          setState((prev) => ({
            ...prev,
            session,
            repos: [],
            repoCursor: null,
          }));

          await loadReposInternal(session.sessionId, true);
        });

        return true;
      },

      disconnectGithub: async () => {
        const current = stateRef.current;
        if (!current.session) {
          return;
        }

        await runTask("GitHub сессия удалена", async () => {
          const api = apiFactory();
          await api.deleteGithubSession(current.session!.sessionId);

          setState((prev) => ({
            ...prev,
            session: null,
            repos: [],
            repoCursor: null,
            selectedRepoId: null,
            workflows: {},
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
        const sessionId = stateRef.current.session?.sessionId;
        if (!sessionId) {
          setState((prev) => ({ ...prev, error: "Нет активной GitHub сессии" }));
          return;
        }

        await runTask("Репозитории загружены", async () => {
          await loadReposInternal(sessionId, reset);
        });
      },

      selectRepo: (repoId) => {
        const repo = stateRef.current.repos.find((item) => item.repoId === repoId);
        selectRepoInternal(repoId, repo);
      },

      runDebugSuite: async () => {
        const sessionId = stateRef.current.session?.sessionId;
        if (!sessionId) {
          setState((prev) => ({ ...prev, error: "Нет активной GitHub сессии" }));
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
              const repo = await ensureRepoLoaded(sessionId, preset.owner, preset.repo);
              selectRepoInternal(repo.repoId, repo);

              upsertWorkflow(repo.repoId, (workflow) => ({
                ...workflow,
                selectedPrNumber: preset.prNumber,
              }));

              const sync = await api.syncGithubPr(sessionId, repo.owner, repo.name, preset.prNumber);

              upsertWorkflow(repo.repoId, (workflow) => ({
                ...workflow,
                syncData: sync,
                selectedPrNumber: preset.prNumber,
                activeStep: "params",
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
              }));

              const scope = (preset.scope?.length ? preset.scope : ["security", "bugs", "style"]) as SuggestionScope[];
              const maxComments = preset.maxComments ?? 40;

              const created = await api.createAnalysisJob(sync.prId, {
                snapshotId: sync.snapshotId,
                scope,
                maxComments,
              });

              updateItem(preset.id, { repoId: repo.repoId, jobId: created.jobId });

              const fresh = await api.getAnalysisJob(created.jobId);
              upsertWorkflow(repo.repoId, (workflow) => ({
                ...workflow,
                job: fresh,
                activeStep: "job",
              }));

              const deadline = Date.now() + 15 * 60 * 1000;
              let current = fresh;

              while (Date.now() < deadline) {
                if (current.status === "done" || current.status === "failed" || current.status === "canceled") {
                  break;
                }

                await sleep(2000);
                current = await api.getAnalysisJob(created.jobId);
                upsertWorkflow(repo.repoId, (workflow) => ({ ...workflow, job: current }));
              }

              if (current.status !== "done" && current.status !== "failed" && current.status !== "canceled") {
                throw new Error("Timeout ожидания завершения job (15m).");
              }

              await loadJobEventsInternal(repo.repoId, current.id);
              if (current.status === "done") {
                await loadSuggestionsInternal(repo.repoId, current.id);
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
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, prState: value }));
      },

      setPrSearch: (repoId, value) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, prSearch: value }));
      },

      loadPullRequests: async (repoId) => {
        const session = stateRef.current.session;
        const repo = stateRef.current.repos.find((item) => item.repoId === repoId);
        const workflow = stateRef.current.workflows[repoId] ?? createDefaultWorkflow(repoId, workspacePreferencesRef.current[repoId]);

        if (!session || !repo) {
          setState((prev) => ({ ...prev, error: "Сначала подключите GitHub и выберите репозиторий" }));
          return;
        }

        await runTask(`PR загружены (${repo.fullName})`, async () => {
          const api = apiFactory();
          const response = await api.getGithubPrs(session.sessionId, repo.owner, repo.name, workflow.prState);

          upsertWorkflow(repoId, (current) => ({
            ...current,
            prs: response.items,
            selectedPrNumber: current.selectedPrNumber && response.items.some((pr) => pr.number === current.selectedPrNumber)
              ? current.selectedPrNumber
              : response.items[0]?.number ?? null,
            activeStep: "pr",
          }));
        });
      },

      selectPullRequest: (repoId, prNumber) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, selectedPrNumber: prNumber }));
      },

      syncPullRequest: async (repoId) => {
        const session = stateRef.current.session;
        const repo = stateRef.current.repos.find((item) => item.repoId === repoId);
        const workflow = stateRef.current.workflows[repoId];

        if (!session || !repo || !workflow?.selectedPrNumber) {
          setState((prev) => ({ ...prev, error: "Сначала выберите репозиторий и PR" }));
          return;
        }

        await runTask(`PR синхронизирован (${repo.fullName}#${workflow.selectedPrNumber})`, async () => {
          const api = apiFactory();
          const sync = await api.syncGithubPr(session.sessionId, repo.owner, repo.name, workflow.selectedPrNumber!);

          upsertWorkflow(repoId, (current) => ({
            ...current,
            syncData: sync,
            activeStep: "params",
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
            runs: current.runs,
            runsCursor: current.runsCursor,
            historyIsMock: current.historyIsMock,
          }));
        });
      },

      setActiveStep: (repoId, step) => {
        const canOpen = canOpenStepWithWorkflow(stateRef.current.workflows[repoId], step);
        if (!canOpen) {
          return;
        }

        upsertWorkflow(repoId, (workflow) => ({ ...workflow, activeStep: step }));
      },

      setMaxComments: (repoId, value) => {
        const next = Number.isFinite(value) ? Math.max(1, Math.min(500, Math.floor(value))) : 30;
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, maxComments: next }));
      },

      setMinSeverity: (repoId, value) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, minSeverity: value }));
      },

      setFileFilter: (repoId, value) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, fileFilter: value }));
      },

      toggleScope: (repoId, scope) => {
        upsertWorkflow(repoId, (workflow) => ({
          ...workflow,
          scope: {
            ...workflow.scope,
            [scope]: !workflow.scope[scope],
          },
        }));
      },

      createAnalysisJob: async (repoId) => {
        const workflow = stateRef.current.workflows[repoId];
        if (!workflow?.syncData) {
          setState((prev) => ({ ...prev, error: "Сначала выполните синхронизацию PR" }));
          return;
        }

        const scope = ALL_SCOPES.filter((item) => workflow.scope[item]);
        if (scope.length === 0) {
          setState((prev) => ({ ...prev, error: "Выберите хотя бы одну область анализа" }));
          return;
        }

        const bootStartedAt = new Date().toISOString();
        const pendingJobId = `pending-${crypto.randomUUID()}`;

        upsertWorkflow(repoId, (current) => ({
          ...current,
          activeStep: "job",
          jobBooting: true,
          jobBootStartedAt: bootStartedAt,
          job: {
            id: pendingJobId,
            prId: current.syncData!.prId,
            snapshotId: current.syncData!.snapshotId,
            status: "queued",
            scope,
            maxComments: current.maxComments,
            progress: {
              filesDone: 0,
              total: current.syncData?.counts.files ?? 0,
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
              message: "Запрос на создание job отправлен. Для больших PR backend может отвечать несколько минут.",
              filePath: null,
              stage: "overview",
              meta: {
                files: current.syncData?.counts.files ?? 0,
                scope,
              },
              createdAt: bootStartedAt,
            },
          ],
        }));

        try {
          await runTask("Задача анализа создана", async () => {
            const api = apiFactory();
            const created = await api.createAnalysisJob(workflow.syncData!.prId, {
              snapshotId: workflow.syncData!.snapshotId,
              scope,
              maxComments: workflow.maxComments,
            });

            const fresh = await api.getAnalysisJob(created.jobId);
            upsertWorkflow(repoId, (current) => ({
              ...current,
              job: fresh,
              jobBooting: false,
              jobBootStartedAt: null,
              activeStep: "job",
            }));

            await loadJobEventsInternal(repoId, fresh.id);

            if (fresh.status === "done") {
              await loadSuggestionsInternal(repoId, fresh.id);
            }
          });
        } catch (error) {
          const message = formatUiError(error, stateRef.current.backendUrl);
          upsertWorkflow(repoId, (current) => ({
            ...current,
            jobBooting: false,
            jobBootStartedAt: null,
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

      refreshJob: async (repoId) => {
        const workflow = stateRef.current.workflows[repoId];
        if (!workflow?.job || workflow.job.id.startsWith("pending-")) {
          return;
        }

        await runTask("Состояние задачи обновлено", async () => {
          const api = apiFactory();
          const fresh = await api.getAnalysisJob(workflow.job!.id);

          upsertWorkflow(repoId, (current) => ({
            ...current,
            job: fresh,
            jobBooting: false,
            jobBootStartedAt: null,
          }));
          await loadJobEventsInternal(repoId, fresh.id);

          if (fresh.status === "done") {
            await loadSuggestionsInternal(repoId, fresh.id);
          }
        });
      },

      cancelJob: async (repoId) => {
        const workflow = stateRef.current.workflows[repoId];
        if (!workflow?.job || workflow.job.id.startsWith("pending-")) {
          return;
        }

        await runTask("Задача анализа отменена", async () => {
          const api = apiFactory();
          const canceled = await api.cancelAnalysisJob(workflow.job!.id);
          upsertWorkflow(repoId, (current) => ({
            ...current,
            job: canceled,
            jobBooting: false,
            jobBootStartedAt: null,
          }));
          await loadJobEventsInternal(repoId, canceled.id);
        });
      },

      loadJobEvents: async (repoId) => {
        const workflow = stateRef.current.workflows[repoId];
        if (!workflow?.job || workflow.job.id.startsWith("pending-")) {
          return;
        }

        await runTask("Лента событий обновлена", async () => {
          await loadJobEventsInternal(repoId, workflow.job!.id);
        });
      },

      setSuggestionSearch: (repoId, value) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, suggestionSearch: value }));
      },

      setSuggestionCategoryFilter: (repoId, value) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, suggestionCategoryFilter: value }));
      },

      setSeverityFilter: (repoId, value) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, severityFilter: value }));
      },

      toggleSuggestionSelection: (repoId, suggestionId) => {
        upsertWorkflow(repoId, (workflow) => {
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
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, activeSuggestionId: suggestionId }));
      },

      selectAllSuggestions: (repoId) => {
        upsertWorkflow(repoId, (workflow) => ({
          ...workflow,
          selectedSuggestionIds: workflow.suggestions.map((item) => item.id),
        }));
      },

      clearSuggestionSelection: (repoId) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, selectedSuggestionIds: [] }));
      },

      reloadSuggestions: async (repoId) => {
        const workflow = stateRef.current.workflows[repoId];
        if (!workflow?.job) {
          return;
        }

        await runTask("Рекомендации обновлены", async () => {
          await loadSuggestionsInternal(repoId, workflow.job!.id);
        });
      },

      setPublishMode: (repoId, mode) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, publishMode: mode }));
      },

      setDryRun: (repoId, dryRun) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, dryRun }));
      },

      publishSuggestions: async (repoId) => {
        const workflow = stateRef.current.workflows[repoId];
        if (!workflow?.job) {
          setState((prev) => ({ ...prev, error: "Сначала запустите анализ" }));
          return;
        }

        const prId = workflow.syncData?.prId ?? workflow.job.prId;

        await runTask(`Публикация запрошена (dryRun=${String(workflow.dryRun)})`, async () => {
          const api = apiFactory();
          const response = await api.publishSuggestions(prId, {
            jobId: workflow.job!.id,
            mode: workflow.publishMode,
            dryRun: workflow.dryRun,
          });

          upsertWorkflow(repoId, (current) => ({
            ...current,
            publishResult: {
              publishRunId: response.publishRunId,
              publishedCount: response.publishedCount,
              idempotent: response.idempotent,
              errors: response.errors,
            },
            comments: response.comments,
            activeStep: current.dryRun ? "publish" : "feedback",
          }));

          if (!workflow.dryRun) {
            await loadCommentsInternal(repoId, prId);
            await loadFeedbackSummaryInternal(repoId, prId);
          }
        });
      },

      loadComments: async (repoId) => {
        const workflow = stateRef.current.workflows[repoId];
        const prId = workflow?.syncData?.prId ?? workflow?.job?.prId;
        if (!prId) {
          setState((prev) => ({ ...prev, error: "Нет связанного PR" }));
          return;
        }

        await runTask("Комментарии PR обновлены", async () => {
          await loadCommentsInternal(repoId, prId);
        });
      },

      setFeedbackUserId: (repoId, userId) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, feedbackUserId: userId }));
      },

      setFeedbackReason: (repoId, reason) => {
        upsertWorkflow(repoId, (workflow) => ({ ...workflow, feedbackReason: reason }));
      },

      voteComment: async (repoId, commentId, vote) => {
        const workflow = stateRef.current.workflows[repoId];
        const userId = workflow?.feedbackUserId?.trim();
        const prId = workflow?.syncData?.prId ?? workflow?.job?.prId;

        if (!workflow || !userId || !prId) {
          setState((prev) => ({ ...prev, error: "Нужен ID пользователя и связанный PR" }));
          return;
        }

        await runTask(`Голос отправлен (${vote === "up" ? "полезно" : "неполезно"})`, async () => {
          const api = apiFactory();
          await api.putFeedback(commentId, {
            userId,
            vote,
            reason: workflow.feedbackReason.trim() || undefined,
          });

          await loadFeedbackSummaryInternal(repoId, prId);
        });
      },

      loadFeedbackSummary: async (repoId) => {
        const workflow = stateRef.current.workflows[repoId];
        const prId = workflow?.syncData?.prId ?? workflow?.job?.prId;
        if (!prId) {
          setState((prev) => ({ ...prev, error: "Нет связанного PR" }));
          return;
        }

        await runTask("Сводка фидбека обновлена", async () => {
          await loadFeedbackSummaryInternal(repoId, prId);
        });
      },

      loadRepoRuns: async (repoId, reset = true) => {
        const cursor = reset ? null : stateRef.current.workflows[repoId]?.runsCursor ?? null;

        await runTask("История запусков обновлена", async () => {
          const api = apiFactory();

          try {
            const page = await api.getRepoRuns(repoId, cursor);
            upsertWorkflow(repoId, (workflow) => ({
              ...workflow,
              runs: reset ? page.items : [...workflow.runs, ...page.items],
              runsCursor: page.nextCursor,
              historyIsMock: false,
            }));
          } catch (_error) {
            const fallbackRuns = createMockRunsFromWorkflow(stateRef.current.workflows[repoId]);
            upsertWorkflow(repoId, (workflow) => ({
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

          upsertWorkflow(repoId, (workflow) => {
            const selectedPrNumber = prMeta.pr.number;
            const existingPr = workflow.prs.find((pr) => pr.number === selectedPrNumber);

            const prs = existingPr
              ? workflow.prs
              : [
                  ...workflow.prs,
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
              ...workflow,
              prs,
              selectedPrNumber,
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
            };
          });

          await loadJobEventsInternal(repoId, job.id);
          await loadSuggestionsInternal(repoId, job.id);
          await loadCommentsInternal(repoId, job.prId);
          await loadFeedbackSummaryInternal(repoId, job.prId);
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
      runTask,
      sleep,
      touchRecentRepo,
      selectRepoInternal,
      upsertWorkflow,
    ],
  );

  const value: AppStoreValue = useMemo(
    () => ({
      ...state,
      actions,
      getWorkflow: (repoId) => {
        if (!repoId) {
          return null;
        }
        return state.workflows[repoId] ?? createDefaultWorkflow(repoId, workspacePreferencesRef.current[repoId]);
      },
      getSelectedRepo: () => {
        const currentRepoId = state.selectedRepoId;
        if (!currentRepoId) {
          return null;
        }
        return state.repos.find((repo) => repo.repoId === currentRepoId) ?? null;
      },
      getRepoStatus: (repoId) => {
        const workflow = state.workflows[repoId];
        return deriveRepoStatus(workflow);
      },
      canOpenStep: (repoId, step) => canOpenStepWithWorkflow(state.workflows[repoId], step),
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

function createDefaultWorkflow(repoId: string, persisted?: PersistedWorkspacePreference): RepoWorkspaceState {
  return {
    repoId,
    prState: persisted?.prState ?? "open",
    prSearch: "",
    prs: [],
    selectedPrNumber: persisted?.selectedPrNumber ?? null,
    syncData: null,
    scope: {
      security: true,
      style: true,
      bugs: true,
      performance: false,
    },
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
    activeStep: persisted?.activeStep ?? "pr",
  };
}

function deriveRepoStatus(workflow: RepoWorkspaceState | undefined): { label: string; tone: "ok" | "warn" | "muted" } {
  if (!workflow) {
    return { label: "нет PR", tone: "muted" };
  }

  if (workflow.jobBooting) {
    return { label: "анализ стартует", tone: "warn" };
  }

  if (workflow.job && (workflow.job.status === "queued" || workflow.job.status === "running")) {
    return { label: "есть job", tone: "ok" };
  }

  if (workflow.selectedPrNumber && !workflow.syncData) {
    return { label: "нужен sync", tone: "warn" };
  }

  if (workflow.syncData && !workflow.job) {
    return { label: "готов к анализу", tone: "ok" };
  }

  if (workflow.job?.status === "done") {
    return { label: "есть результаты", tone: "ok" };
  }

  return { label: "нет PR", tone: "muted" };
}

function canOpenStepWithWorkflow(workflow: RepoWorkspaceState | undefined, step: WorkspaceStep): boolean {
  if (!workflow) {
    return step === "pr";
  }

  if (step === "pr") {
    return true;
  }

  if (step === "params" || step === "job") {
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

function loadRecentRepos(): RecentRepoItem[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(RECENT_REPOS_KEY);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed
      .filter((item) => item && typeof item === "object")
      .map((item) => ({
        repoId: String(item.repoId ?? ""),
        fullName: String(item.fullName ?? ""),
        owner: String(item.owner ?? ""),
        name: String(item.name ?? ""),
        lastOpenedAt: String(item.lastOpenedAt ?? ""),
      }))
      .filter((item) => item.repoId && item.fullName)
      .slice(0, 8);
  } catch {
    return [];
  }
}

function persistRecentRepos(items: RecentRepoItem[]) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(RECENT_REPOS_KEY, JSON.stringify(items));
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

function createMockRunsFromWorkflow(workflow: RepoWorkspaceState | undefined): RepoRunSummary[] {
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
      prNumber: workflow.selectedPrNumber ?? 0,
      prTitle: workflow.prs.find((item) => item.number === workflow.selectedPrNumber)?.title ?? "Unknown PR",
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
  if (value === "params" || value === "job" || value === "results" || value === "publish" || value === "feedback" || value === "history") {
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
