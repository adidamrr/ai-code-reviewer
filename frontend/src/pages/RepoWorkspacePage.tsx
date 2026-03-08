import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiClient } from "../lib/api";
import { useAppStore, ALL_SCOPES, JOB_STAGE_LABELS, JOB_STATUS_LABELS, SCOPE_LABELS, SEVERITY_LABELS, STEP_LABELS, WORKSPACE_STEPS } from "../store/app-store";
import type { Suggestion } from "../types";

export function RepoWorkspacePage() {
  const { repoId } = useParams<{ repoId: string }>();
  const navigate = useNavigate();
  const {
    session,
    backendUrl,
    serviceToken,
    repos,
    busy,
    actions,
    canOpenStep,
    getWorkflow,
  } = useAppStore();
  const api = useMemo(
    () =>
      new ApiClient({
        baseUrl: backendUrl,
        serviceToken: serviceToken.trim().length > 0 ? serviceToken.trim() : undefined,
      }),
    [backendUrl, serviceToken],
  );

  const repo = useMemo(() => repos.find((item) => item.repoId === repoId) ?? null, [repoId, repos]);
  const workflow = getWorkflow(repoId);
  const [patchByFile, setPatchByFile] = useState<Record<string, string>>({});
  const [patchLoading, setPatchLoading] = useState(false);
  const [patchError, setPatchError] = useState<string | null>(null);

  useEffect(() => {
    if (!repoId) {
      return;
    }
    actions.selectRepo(repoId);
  }, [actions, repoId]);

  useEffect(() => {
    if (!repoId || !workflow?.job || workflow.jobBooting) {
      return;
    }
    if (workflow.activeStep !== "job") {
      return;
    }
    if (workflow.job.status !== "queued" && workflow.job.status !== "running") {
      return;
    }

    const timer = window.setInterval(() => {
      actions.refreshJob(repoId).catch(() => undefined);
    }, 2500);

    return () => {
      window.clearInterval(timer);
    };
  }, [actions, repoId, workflow?.activeStep, workflow?.job?.id, workflow?.job?.status]);

  useEffect(() => {
    if (!repoId || workflow?.activeStep !== "history") {
      return;
    }

    actions.loadRepoRuns(repoId, true).catch(() => undefined);
  }, [actions, repoId, workflow?.activeStep]);

  if (!session) {
    return (
      <div className="page-wrap">
        <section className="card stack-gap">
          <h1>Сессия GitHub не активна</h1>
          <p className="subline">Подключи GitHub на предыдущем шаге, затем возвращайся в workspace.</p>
          <button className="primary-btn" onClick={() => navigate("/connect")}>Открыть подключение</button>
        </section>
      </div>
    );
  }

  if (!repoId || !repo || !workflow) {
    return (
      <div className="page-wrap">
        <section className="card stack-gap">
          <h1>Репозиторий не найден</h1>
          <p className="subline">Выбери доступный репозиторий из списка.</p>
          <button className="primary-btn" onClick={() => navigate("/repos")}>К списку репозиториев</button>
        </section>
      </div>
    );
  }

  const filteredPrs = workflow.prs.filter((pr) => {
    const q = workflow.prSearch.trim().toLowerCase();
    if (!q) {
      return true;
    }
    return `${pr.number} ${pr.title} ${pr.authorLogin}`.toLowerCase().includes(q);
  });

  const suggestionsBySearch = workflow.suggestions.filter((item) => {
    const query = workflow.suggestionSearch.trim().toLowerCase();
    if (!query) {
      return true;
    }

    return `${item.title} ${item.body} ${item.filePath}`.toLowerCase().includes(query);
  });

  const suggestionsForSeverityCounts = useMemo(() => {
    if (workflow.suggestionCategoryFilter === "all") {
      return suggestionsBySearch;
    }
    return suggestionsBySearch.filter((item) => item.category === workflow.suggestionCategoryFilter);
  }, [suggestionsBySearch, workflow.suggestionCategoryFilter]);

  const suggestionsForCategoryCounts = useMemo(() => {
    if (workflow.severityFilter === "all") {
      return suggestionsBySearch;
    }
    return suggestionsBySearch.filter((item) => item.severity === workflow.severityFilter);
  }, [suggestionsBySearch, workflow.severityFilter]);

  const filteredSuggestions = suggestionsBySearch.filter((item) => {
    if (workflow.suggestionCategoryFilter !== "all" && item.category !== workflow.suggestionCategoryFilter) {
      return false;
    }
    if (workflow.severityFilter !== "all" && item.severity !== workflow.severityFilter) {
      return false;
    }
    return true;
  });

  const inlineSuggestions = filteredSuggestions.filter((item) => (item.deliveryMode ?? "inline") === "inline");
  const summarySuggestions = filteredSuggestions.filter((item) => item.deliveryMode === "summary");

  const severityCounts = useMemo(() => ({
    critical: suggestionsForSeverityCounts.filter((item) => item.severity === "critical").length,
    high: suggestionsForSeverityCounts.filter((item) => item.severity === "high").length,
    medium: suggestionsForSeverityCounts.filter((item) => item.severity === "medium").length,
    low: suggestionsForSeverityCounts.filter((item) => item.severity === "low").length,
    info: suggestionsForSeverityCounts.filter((item) => item.severity === "info").length,
  }), [suggestionsForSeverityCounts]);

  const categoryCounts = useMemo(() => ({
    security: suggestionsForCategoryCounts.filter((item) => item.category === "security").length,
    style: suggestionsForCategoryCounts.filter((item) => item.category === "style").length,
    bugs: suggestionsForCategoryCounts.filter((item) => item.category === "bugs").length,
    performance: suggestionsForCategoryCounts.filter((item) => item.category === "performance").length,
  }), [suggestionsForCategoryCounts]);

  const groupedSuggestions = useMemo(() => {
    const grouped = new Map<string, typeof inlineSuggestions>();

    for (const suggestion of inlineSuggestions) {
      if (!grouped.has(suggestion.filePath)) {
        grouped.set(suggestion.filePath, []);
      }
      grouped.get(suggestion.filePath)?.push(suggestion);
    }

    return [...grouped.entries()]
      .map(([filePath, items]) => ({
        filePath,
        items: items.sort((a, b) => a.lineStart - b.lineStart),
      }))
      .sort((a, b) => a.filePath.localeCompare(b.filePath));
  }, [inlineSuggestions]);

  const selectedVisibleCount = filteredSuggestions.filter((item) => workflow.selectedSuggestionIds.includes(item.id)).length;
  const enabledScopes = ALL_SCOPES.filter((item) => workflow.scope[item]);
  const bootStartedLabel = workflow.jobBootStartedAt
    ? new Date(workflow.jobBootStartedAt).toLocaleTimeString("ru-RU")
    : null;

  const activeSuggestion =
    filteredSuggestions.find((item) => item.id === workflow.activeSuggestionId) ??
    filteredSuggestions[0] ??
    null;

  useEffect(() => {
    if (!repoId || workflow?.activeStep !== "results" || !activeSuggestion) {
      return;
    }

    const filePath = activeSuggestion.filePath;
    if (patchByFile[filePath] !== undefined) {
      return;
    }

    const prId = workflow?.syncData?.prId ?? workflow?.job?.prId;
    if (!prId) {
      return;
    }

    let cancelled = false;
    setPatchLoading(true);
    setPatchError(null);

    api.getPrDiff(prId, filePath)
      .then((response) => {
        if (cancelled) {
          return;
        }

        const patch = response.items[0]?.patch ?? "";
        setPatchByFile((prev) => ({ ...prev, [filePath]: patch }));
      })
      .catch(() => {
        if (cancelled) {
          return;
        }

        setPatchError("Не удалось загрузить diff для этого файла.");
      })
      .finally(() => {
        if (!cancelled) {
          setPatchLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [api, activeSuggestion, patchByFile, repoId, workflow?.activeStep, workflow?.job?.prId, workflow?.syncData?.prId]);

  const activePatch = activeSuggestion ? patchByFile[activeSuggestion.filePath] ?? null : null;
  const diffPreviewLines = useMemo(() => {
    if (!activeSuggestion || !activePatch) {
      return [];
    }

    return buildDiffPreview(activeSuggestion, activePatch);
  }, [activePatch, activeSuggestion]);

  return (
    <div className="workspace-wrap">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">Repo Workspace</p>
          <h1>{repo.fullName}</h1>
          <p className="subline">
            PR: {workflow.selectedPrNumber ? `#${workflow.selectedPrNumber}` : "не выбран"} ·
            {" "}
            Snapshot: {workflow.syncData?.snapshotId ?? "нет"}
          </p>
        </div>
        <div className="status-pills">
          <span className="pill">Сессия: {session.githubLogin}</span>
          <span className="pill">Job: {workflow.job ? JOB_STATUS_LABELS[workflow.job.status] : "не запущен"}</span>
        </div>
      </header>

      <section className="stepper-card">
        {WORKSPACE_STEPS.map((step) => {
          const allowed = canOpenStep(repo.repoId, step);
          const active = workflow.activeStep === step;

          return (
            <button
              key={step}
              className={`step-chip ${active ? "active" : ""}`}
              disabled={!allowed}
              onClick={() => actions.setActiveStep(repo.repoId, step)}
            >
              {STEP_LABELS[step]}
            </button>
          );
        })}
      </section>

      {workflow.activeStep === "pr" ? (
        <section className="card stack-gap">
          <div className="toolbar-row">
            <select
              value={workflow.prState}
              onChange={(event) => actions.setPrState(repo.repoId, event.target.value as "open" | "closed" | "all")}
            >
              <option value="open">open</option>
              <option value="closed">closed</option>
              <option value="all">all</option>
            </select>
            <input
              value={workflow.prSearch}
              onChange={(event) => actions.setPrSearch(repo.repoId, event.target.value)}
              placeholder="Поиск PR"
            />
            <button className="secondary-btn" onClick={() => actions.loadPullRequests(repo.repoId)} disabled={busy}>
              Загрузить PR
            </button>
          </div>

          <div className="pr-list">
            {filteredPrs.map((pr) => {
              const selected = workflow.selectedPrNumber === pr.number;

              return (
                <button
                  key={pr.number}
                  className={`pr-item ${selected ? "active" : ""}`}
                  onClick={() => actions.selectPullRequest(repo.repoId, pr.number)}
                >
                  <div className="pr-title-line">
                    <strong>#{pr.number}</strong>
                    <span>{pr.title}</span>
                  </div>
                  <p className="pr-meta">
                    {pr.authorLogin} · {pr.state} · обновлено {new Date(pr.updatedAt).toLocaleString("ru-RU")}
                  </p>
                </button>
              );
            })}

            {filteredPrs.length === 0 ? (
              <p className="empty-note">PR пока не загружены. Нажми «Загрузить PR».</p>
            ) : null}
          </div>

          <div className="row-actions">
            <div className="sync-inline-card">
              <div className="sync-inline-head">
                <h3>Синхронизация GitHub PR</h3>
                <p className="subline">После sync сразу открываются параметры анализа.</p>
              </div>
              <div className="row-actions">
                <button
                  className="primary-btn"
                  disabled={!workflow.selectedPrNumber || busy}
                  onClick={() => actions.syncPullRequest(repo.repoId)}
                >
                  Синхронизировать PR #{workflow.selectedPrNumber ?? "?"}
                </button>
                {workflow.syncData ? (
                  <button className="secondary-btn" onClick={() => actions.setActiveStep(repo.repoId, "params")}>
                    К параметрам
                  </button>
                ) : null}
              </div>

              {workflow.syncData ? (
                <div className="sync-inline-metrics">
                  <span>snapshot: {workflow.syncData.snapshotId}</span>
                  <span>files: {workflow.syncData.counts.files}</span>
                  <span>+/-: {workflow.syncData.counts.additions}/{workflow.syncData.counts.deletions}</span>
                  <span>idempotent: {String(workflow.syncData.idempotent)}</span>
                </div>
              ) : (
                <p className="empty-note">Выбери PR и запусти синхронизацию.</p>
              )}
            </div>
          </div>
        </section>
      ) : null}

      {workflow.activeStep === "params" ? (
        <section className="card stack-gap">
          <h2>Параметры анализа</h2>
          <div className="chips-row">
            {ALL_SCOPES.map((scope) => (
              <button
                key={scope}
                className={`chip ${workflow.scope[scope] ? "active" : ""}`}
                onClick={() => actions.toggleScope(repo.repoId, scope)}
              >
                {SCOPE_LABELS[scope]}
              </button>
            ))}
          </div>

          <div className="form-grid">
            <label className="field">
              <span>Максимум комментариев</span>
              <input
                type="number"
                value={workflow.maxComments}
                min={1}
                max={500}
                onChange={(event) => actions.setMaxComments(repo.repoId, Number(event.target.value))}
              />
            </label>

            <label className="field">
              <span>Минимальная severity (UI-only)</span>
              <select
                value={workflow.minSeverity}
                onChange={(event) =>
                  actions.setMinSeverity(
                    repo.repoId,
                    event.target.value as "none" | "low" | "medium" | "high" | "critical" | "info",
                  )
                }
              >
                <option value="none">без фильтра</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="critical">critical</option>
              </select>
            </label>
          </div>

          <label className="field">
            <span>File filter (UI-only, mock)</span>
            <input
              value={workflow.fileFilter}
              onChange={(event) => actions.setFileFilter(repo.repoId, event.target.value)}
              placeholder="*.ts, !tests/**"
            />
          </label>

          <div className="row-actions">
            <button className="primary-btn" onClick={() => actions.createAnalysisJob(repo.repoId)} disabled={busy || !workflow.syncData}>
              Запустить анализ
            </button>
            <button className="secondary-btn" onClick={() => actions.setActiveStep(repo.repoId, "pr")}>Назад к PR</button>
          </div>
        </section>
      ) : null}

      {workflow.activeStep === "job" ? (
        <section className="card stack-gap">
          <div className="job-head">
            <div>
              <h2>{workflow.jobBooting ? "Запуск анализа" : "Выполнение job"}</h2>
              <p className="subline">
                {workflow.jobBooting
                  ? "Создаем analysis job и подготавливаем первый прогон. Для больших PR это может занять несколько минут."
                  : workflow.job
                    ? `jobId: ${workflow.job.id}`
                    : "job не создан"}
              </p>
            </div>
            {workflow.jobBooting ? (
              <span className="status-badge warn">запуск</span>
            ) : workflow.job ? (
              <span className={`status-badge ${workflow.job.status === "done" ? "ok" : "warn"}`}>{JOB_STATUS_LABELS[workflow.job.status]}</span>
            ) : null}
          </div>

          {workflow.jobBooting ? (
            <article className="analysis-launch-card">
              <div className="analysis-launch-top">
                <div className="analysis-loader" aria-hidden="true" />
                <div className="analysis-launch-copy">
                  <h3>Анализ запущен и backend сейчас работает</h3>
                  <p>
                    Сервис не упал. Сервер синхронно создает job и начинает обработку файлов. Для крупных PR
                    старт может занимать 2-15 минут до появления первых результатов.
                  </p>
                </div>
              </div>

              <div className="kpi-grid">
                <article className="kpi-card">
                  <span>файлов в snapshot</span>
                  <strong>{workflow.syncData?.counts.files ?? workflow.job?.progress.total ?? 0}</strong>
                </article>
                <article className="kpi-card">
                  <span>области анализа</span>
                  <strong>{enabledScopes.map((scope) => SCOPE_LABELS[scope]).join(", ")}</strong>
                </article>
                <article className="kpi-card">
                  <span>max comments</span>
                  <strong>{workflow.maxComments}</strong>
                </article>
                <article className="kpi-card">
                  <span>старт</span>
                  <strong>{bootStartedLabel ?? "сейчас"}</strong>
                </article>
              </div>

              <div className="analysis-launch-note">
                <strong>Что происходит сейчас</strong>
                <p>
                  Идет создание analysis job, после чего интерфейс автоматически покажет обычный экран job со статусом,
                  событиями и затем результаты.
                </p>
              </div>

              <div className="console-card">
                {workflow.jobEvents.map((event) => (
                  <div key={event.id} className={`console-line ${event.level}`}>
                    <span>{new Date(event.createdAt).toLocaleTimeString("ru-RU")}</span>
                    <span>{event.stage ? `[${JOB_STAGE_LABELS[event.stage]}]` : ""}</span>
                    <span>{event.filePath ? `[${event.filePath}]` : ""}</span>
                    <span>{event.message}</span>
                  </div>
                ))}
              </div>
            </article>
          ) : workflow.job ? (
            <>
              <div className="kpi-grid">
                <article className="kpi-card">
                  <span>progress</span>
                  <strong>{workflow.job.progress.filesDone}/{workflow.job.progress.total}</strong>
                </article>
                <article className="kpi-card">
                  <span>stage</span>
                  <strong>{workflow.job.progress.stage ? JOB_STAGE_LABELS[workflow.job.progress.stage] : "не указан"}</strong>
                </article>
                <article className="kpi-card">
                  <span>stage progress</span>
                  <strong>
                    {workflow.job.progress.stageProgress?.done ?? 0}/{workflow.job.progress.stageProgress?.total ?? 0}
                  </strong>
                </article>
                <article className="kpi-card">
                  <span>suggestions</span>
                  <strong>{workflow.job.summary.totalSuggestions}</strong>
                </article>
                <article className="kpi-card">
                  <span>updated</span>
                  <strong>{new Date(workflow.job.updatedAt).toLocaleTimeString("ru-RU")}</strong>
                </article>
                <article className="kpi-card">
                  <span>partial failures</span>
                  <strong>{workflow.job.summary.partialFailures}</strong>
                </article>
              </div>

              <div className="row-actions">
                <button className="secondary-btn" onClick={() => actions.refreshJob(repo.repoId)} disabled={busy}>Обновить job</button>
                <button className="secondary-btn" onClick={() => actions.loadJobEvents(repo.repoId)} disabled={busy}>Обновить события</button>
                {workflow.job.status === "queued" || workflow.job.status === "running" ? (
                  <button className="secondary-btn danger" onClick={() => actions.cancelJob(repo.repoId)} disabled={busy}>Отменить</button>
                ) : null}
                {workflow.job.status === "done" ? (
                  <button className="primary-btn" onClick={() => actions.setActiveStep(repo.repoId, "results")}>Открыть результаты</button>
                ) : null}
              </div>

              <div className="console-card">
                {workflow.jobEvents.map((event) => (
                  <div key={event.id} className={`console-line ${event.level}`}>
                    <span>{new Date(event.createdAt).toLocaleTimeString("ru-RU")}</span>
                    <span>{event.stage ? `[${JOB_STAGE_LABELS[event.stage]}]` : ""}</span>
                    <span>{event.filePath ? `[${event.filePath}]` : ""}</span>
                    <span>{event.message}</span>
                  </div>
                ))}
                {workflow.jobEvents.length === 0 ? <p className="empty-note">Событий пока нет.</p> : null}
              </div>
            </>
          ) : (
            <p className="empty-note">Сначала создай задачу анализа на шаге параметров.</p>
          )}
        </section>
      ) : null}

      {workflow.activeStep === "results" ? (
        <section className="card split-results results-shell">
          <div className="results-toolbar">
            <div className="results-toolbar-left">
              <div className="severity-group">
                <button
                  className={`severity-filter-chip ${workflow.severityFilter === "all" ? "active" : ""}`}
                  onClick={() => actions.setSeverityFilter(repo.repoId, "all")}
                >
                  Все ({suggestionsForSeverityCounts.length})
                </button>
                <button
                  className={`severity-filter-chip critical ${workflow.severityFilter === "critical" ? "active" : ""}`}
                  onClick={() => actions.setSeverityFilter(repo.repoId, "critical")}
                >
                  Critical ({severityCounts.critical})
                </button>
                <button
                  className={`severity-filter-chip high ${workflow.severityFilter === "high" ? "active" : ""}`}
                  onClick={() => actions.setSeverityFilter(repo.repoId, "high")}
                >
                  High ({severityCounts.high})
                </button>
                <button
                  className={`severity-filter-chip medium ${workflow.severityFilter === "medium" ? "active" : ""}`}
                  onClick={() => actions.setSeverityFilter(repo.repoId, "medium")}
                >
                  Medium ({severityCounts.medium})
                </button>
                <button
                  className={`severity-filter-chip low ${workflow.severityFilter === "low" ? "active" : ""}`}
                  onClick={() => actions.setSeverityFilter(repo.repoId, "low")}
                >
                  Low ({severityCounts.low})
                </button>
                <button
                  className={`severity-filter-chip info ${workflow.severityFilter === "info" ? "active" : ""}`}
                  onClick={() => actions.setSeverityFilter(repo.repoId, "info")}
                >
                  Info ({severityCounts.info})
                </button>
              </div>

              <div className="results-controls">
                <div className="severity-group category-group">
                  <button
                    className={`severity-filter-chip ${workflow.suggestionCategoryFilter === "all" ? "active" : ""}`}
                    onClick={() => actions.setSuggestionCategoryFilter(repo.repoId, "all")}
                  >
                    Все категории ({suggestionsForCategoryCounts.length})
                  </button>
                  <button
                    className={`severity-filter-chip category security ${workflow.suggestionCategoryFilter === "security" ? "active" : ""}`}
                    onClick={() => actions.setSuggestionCategoryFilter(repo.repoId, "security")}
                  >
                    {SCOPE_LABELS.security} ({categoryCounts.security})
                  </button>
                  <button
                    className={`severity-filter-chip category bugs ${workflow.suggestionCategoryFilter === "bugs" ? "active" : ""}`}
                    onClick={() => actions.setSuggestionCategoryFilter(repo.repoId, "bugs")}
                  >
                    {SCOPE_LABELS.bugs} ({categoryCounts.bugs})
                  </button>
                  <button
                    className={`severity-filter-chip category style ${workflow.suggestionCategoryFilter === "style" ? "active" : ""}`}
                    onClick={() => actions.setSuggestionCategoryFilter(repo.repoId, "style")}
                  >
                    {SCOPE_LABELS.style} ({categoryCounts.style})
                  </button>
                  <button
                    className={`severity-filter-chip category performance ${workflow.suggestionCategoryFilter === "performance" ? "active" : ""}`}
                    onClick={() => actions.setSuggestionCategoryFilter(repo.repoId, "performance")}
                  >
                    {SCOPE_LABELS.performance} ({categoryCounts.performance})
                  </button>
                </div>
                <input
                  value={workflow.suggestionSearch}
                  onChange={(event) => actions.setSuggestionSearch(repo.repoId, event.target.value)}
                  placeholder="Поиск по title / file / body"
                />
                <button className="secondary-btn" onClick={() => actions.reloadSuggestions(repo.repoId)} disabled={busy}>Обновить</button>
              </div>
            </div>

            <div className="results-toolbar-right">
              <p className="selected-counter">
                Выбрано: <strong>{workflow.selectedSuggestionIds.length}</strong>
                {" "}
                <span>(в текущем списке {selectedVisibleCount})</span>
              </p>
              <div className="row-actions">
                <button className="secondary-btn" onClick={() => actions.selectAllSuggestions(repo.repoId)}>Выбрать все</button>
                <button className="secondary-btn" onClick={() => actions.clearSuggestionSelection(repo.repoId)}>Снять выбор</button>
                <button
                  className="primary-btn"
                  onClick={() => actions.setActiveStep(repo.repoId, "publish")}
                  disabled={!workflow.suggestions.some((item) => (item.deliveryMode ?? "inline") === "inline")}
                >
                  К публикации
                </button>
              </div>
            </div>
          </div>

          <div className="result-left results-list-panel">
            {summarySuggestions.length > 0 ? (
              <div className="file-group">
                <div className="file-group-header">
                  <span>PR summary findings</span>
                  <span>{summarySuggestions.length}</span>
                </div>
                {summarySuggestions.map((item) => (
                  <button
                    key={item.id}
                    className={`suggestion-item ux ${workflow.activeSuggestionId === item.id ? "active" : ""}`}
                    onClick={() => actions.setActiveSuggestion(repo.repoId, item.id)}
                  >
                    <div className="suggestion-item-head">
                      <span className={`severity-pill ${item.severity}`}>{SEVERITY_LABELS[item.severity]}</span>
                      <span className={`category-pill ${item.category}`}>{SCOPE_LABELS[item.category]}</span>
                      <span className="status-badge warn">summary</span>
                    </div>
                    <strong>{item.title}</strong>
                    <p className="suggestion-snippet">{item.body}</p>
                    <p className="suggestion-footnote">Evidence: {item.evidence?.length ?? 0}</p>
                  </button>
                ))}
              </div>
            ) : null}

            {groupedSuggestions.map((group) => (
              <div className="file-group" key={group.filePath}>
                <div className="file-group-header">
                  <span className="mono">{group.filePath}</span>
                  <span>{group.items.length} issue(s)</span>
                </div>

                {group.items.map((item) => {
                  const selected = workflow.selectedSuggestionIds.includes(item.id);
                  const active = workflow.activeSuggestionId === item.id;

                  return (
                    <button
                      key={item.id}
                      className={`suggestion-item ux ${active ? "active" : ""}`}
                      onClick={() => actions.setActiveSuggestion(repo.repoId, item.id)}
                    >
                      <div className="suggestion-item-head">
                        <span className={`severity-pill ${item.severity}`}>{SEVERITY_LABELS[item.severity]}</span>
                        <span className={`category-pill ${item.category}`}>{SCOPE_LABELS[item.category]}</span>
                        <span className="mono">L{item.lineStart}-{item.lineEnd}</span>
                        {item.deliveryMode === "summary" ? <span className="status-badge warn">summary</span> : null}
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={item.deliveryMode === "summary"}
                          onChange={() => actions.toggleSuggestionSelection(repo.repoId, item.id)}
                          onClick={(event) => event.stopPropagation()}
                        />
                      </div>
                      <strong>{item.title}</strong>
                      <p className="suggestion-snippet">{item.body}</p>
                      <p className="suggestion-footnote">Evidence: {item.evidence?.length ?? 0} · Источников: {item.citations.length}</p>
                    </button>
                  );
                })}
              </div>
            ))}

            {groupedSuggestions.length === 0 ? <p className="empty-note">Нет suggestions по текущим фильтрам.</p> : null}
          </div>

          <div className="result-right results-detail-panel">
            {activeSuggestion ? (
              <>
                <article className="detail-main-card">
                  <div className="detail-head">
                    <div className="detail-badges">
                      <span className={`severity-pill ${activeSuggestion.severity}`}>{SEVERITY_LABELS[activeSuggestion.severity]}</span>
                      <span className={`category-pill ${activeSuggestion.category}`}>{SCOPE_LABELS[activeSuggestion.category]}</span>
                      <span className={`status-badge ${(activeSuggestion.deliveryMode ?? "inline") === "inline" ? "ok" : "warn"}`}>
                        {(activeSuggestion.deliveryMode ?? "inline") === "inline" ? "inline" : "summary"}
                      </span>
                    </div>
                    <span className="mono">confidence {Math.round(activeSuggestion.confidence * 100)}%</span>
                  </div>
                  <h3>{activeSuggestion.title}</h3>
                  <p className="detail-body">{activeSuggestion.body}</p>
                  <p className="mono">{activeSuggestion.filePath}:{activeSuggestion.lineStart}-{activeSuggestion.lineEnd}</p>
                </article>

                <article className="detail-code-card">
                  <header className="detail-code-header">
                    <span className="mono">{activeSuggestion.filePath}</span>
                    <span className="detail-code-hint">real diff preview</span>
                  </header>
                  {patchLoading ? <p className="detail-code-state">Загрузка diff...</p> : null}
                  {!patchLoading && patchError ? <p className="detail-code-state warn">{patchError}</p> : null}
                  {!patchLoading && !patchError && diffPreviewLines.length > 0 ? (
                    <div className="diff-lines">
                      {diffPreviewLines.map((line, index) => (
                        <div key={`${line.newLine}-${line.oldLine}-${index}`} className={`diff-line ${line.kind}`}>
                          <span className="diff-line-num">
                            {line.newLine ?? line.oldLine ?? ""}
                          </span>
                          <code>{line.kind === "add" ? "+" : line.kind === "del" ? "-" : " "}{line.text}</code>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {!patchLoading && !patchError && diffPreviewLines.length === 0 ? (
                    <pre className="detail-code-preview">
                      <code>{buildSuggestionPreview(activeSuggestion)}</code>
                    </pre>
                  ) : null}
                </article>

                <section className="citation-box detail-citation-card">
                  <h4>Evidence</h4>
                  {(activeSuggestion.evidence?.length ?? 0) === 0 ? (
                    <p className="empty-note">Для этой рекомендации evidence пока отсутствует.</p>
                  ) : null}
                  {activeSuggestion.evidence?.map((item) => (
                    item.type === "doc" && item.url ? (
                      <a key={item.evidenceId} href={item.url} target="_blank" rel="noreferrer" className="citation-link">
                        <strong>{item.type === "doc" ? "Документация" : item.type}: {item.title}</strong>
                        <span>{item.snippet}</span>
                      </a>
                    ) : (
                      <article key={item.evidenceId} className="citation-link evidence-block">
                        <strong>{item.type === "code" ? "Код" : item.type === "rule" ? "Правило" : item.type}: {item.title}</strong>
                        <span>{item.snippet}</span>
                        {item.filePath ? <span className="mono">{item.filePath}:{item.lineStart ?? "?"}-{item.lineEnd ?? item.lineStart ?? "?"}</span> : null}
                      </article>
                    )
                  ))}
                </section>
              </>
            ) : (
              <p className="empty-note">Выбери рекомендацию слева.</p>
            )}
          </div>
        </section>
      ) : null}

      {workflow.activeStep === "publish" ? (
        <section className="card stack-gap">
          <h2>Публикация комментариев</h2>
          <p className="subline">
            Выбрано в UI: {workflow.selectedSuggestionIds.length} из {inlineSuggestions.length}. В текущем backend MVP публикуются все inline suggestions job.
          </p>

          <label className="field">
            <span>Режим</span>
            <select value={workflow.publishMode} onChange={(event) => actions.setPublishMode(repo.repoId, event.target.value as "review_comments" | "issue_comments")}>
              <option value="review_comments">review_comments</option>
              <option value="issue_comments">issue_comments</option>
            </select>
          </label>

          <label className="toggle-line">
            <input type="checkbox" checked={workflow.dryRun} onChange={(event) => actions.setDryRun(repo.repoId, event.target.checked)} />
            dry-run (без отправки в GitHub)
          </label>

          <div className="row-actions">
            <button className="primary-btn" onClick={() => actions.publishSuggestions(repo.repoId)} disabled={busy || !workflow.job}>
              Опубликовать
            </button>
            <button className="secondary-btn" onClick={() => actions.loadComments(repo.repoId)} disabled={busy}>Обновить comments</button>
          </div>

          {workflow.publishResult ? (
            <div className="kpi-grid">
              <article className="kpi-card">
                <span>publishRunId</span>
                <strong>{workflow.publishResult.publishRunId}</strong>
              </article>
              <article className="kpi-card">
                <span>publishedCount</span>
                <strong>{workflow.publishResult.publishedCount}</strong>
              </article>
              <article className="kpi-card">
                <span>idempotent</span>
                <strong>{String(workflow.publishResult.idempotent)}</strong>
              </article>
              <article className="kpi-card">
                <span>errors</span>
                <strong>{workflow.publishResult.errors.length}</strong>
              </article>
            </div>
          ) : null}

          <button className="primary-btn" disabled={workflow.comments.length === 0 && (workflow.publishResult?.publishedCount ?? 0) === 0} onClick={() => actions.setActiveStep(repo.repoId, "feedback")}>
            Далее: фидбек
          </button>
        </section>
      ) : null}

      {workflow.activeStep === "feedback" ? (
        <section className="card split-results">
          <div className="result-left">
            <h2>Голоса команды</h2>

            <label className="field">
              <span>Пользователь</span>
              <input value={workflow.feedbackUserId} onChange={(event) => actions.setFeedbackUserId(repo.repoId, event.target.value)} />
            </label>

            <label className="field">
              <span>Причина (опционально)</span>
              <input value={workflow.feedbackReason} onChange={(event) => actions.setFeedbackReason(repo.repoId, event.target.value)} />
            </label>

            <div className="comment-list">
              {workflow.comments.map((comment) => (
                <article className="comment-item" key={comment.id}>
                  <p className="mono">{comment.filePath}:{comment.lineStart}-{comment.lineEnd}</p>
                  <p>{comment.body}</p>
                  <div className="row-actions">
                    <button className="secondary-btn" onClick={() => actions.voteComment(repo.repoId, comment.id, "up")}>Полезно</button>
                    <button className="secondary-btn danger" onClick={() => actions.voteComment(repo.repoId, comment.id, "down")}>Неполезно</button>
                  </div>
                </article>
              ))}
              {workflow.comments.length === 0 ? <p className="empty-note">Нет опубликованных комментариев.</p> : null}
            </div>
          </div>

          <div className="result-right">
            <h3>Сводка фидбека</h3>
            <div className="row-actions">
              <button className="secondary-btn" onClick={() => actions.loadFeedbackSummary(repo.repoId)}>Обновить summary</button>
            </div>

            {workflow.feedbackSummary ? (
              <div className="stack-gap">
                <div className="kpi-grid">
                  <article className="kpi-card">
                    <span>up</span>
                    <strong>{workflow.feedbackSummary.overall.up}</strong>
                  </article>
                  <article className="kpi-card">
                    <span>down</span>
                    <strong>{workflow.feedbackSummary.overall.down}</strong>
                  </article>
                  <article className="kpi-card">
                    <span>score</span>
                    <strong>{workflow.feedbackSummary.overall.score}</strong>
                  </article>
                </div>

                <section className="summary-list">
                  <h4>По категориям</h4>
                  {workflow.feedbackSummary.byCategory.map((entry) => (
                    <p key={entry.category}>{SCOPE_LABELS[entry.category]}: {entry.score}</p>
                  ))}
                  {workflow.feedbackSummary.byCategory.length === 0 ? <p>-</p> : null}
                </section>
              </div>
            ) : (
              <p className="empty-note">Сводка появится после голосов.</p>
            )}

            <button className="primary-btn" onClick={() => actions.setActiveStep(repo.repoId, "history")}>Открыть историю</button>
          </div>
        </section>
      ) : null}

      {workflow.activeStep === "history" ? (
        <section className="card stack-gap">
          <div className="job-head">
            <div>
              <h2>История запусков</h2>
              <p className="subline">Запуски по текущему репозиторию.</p>
            </div>
            {workflow.historyIsMock ? <span className="status-badge warn">mock fallback</span> : null}
          </div>

          <div className="row-actions">
            <button className="secondary-btn" onClick={() => actions.loadRepoRuns(repo.repoId, true)} disabled={busy}>Обновить</button>
            <button className="secondary-btn" onClick={() => actions.loadRepoRuns(repo.repoId, false)} disabled={busy || !workflow.runsCursor}>Загрузить еще</button>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>PR</th>
                  <th>Status</th>
                  <th>Suggestions</th>
                  <th>Comments</th>
                  <th>Score</th>
                  <th>Дата</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {workflow.runs.map((run) => (
                  <tr key={run.runId}>
                    <td className="mono">{run.runId}</td>
                    <td>
                      #{run.prNumber}
                      <p>{run.prTitle}</p>
                    </td>
                    <td>{JOB_STATUS_LABELS[run.status]}</td>
                    <td>{run.totalSuggestions}</td>
                    <td>{run.publishedComments}</td>
                    <td>{run.feedbackScore}</td>
                    <td>{new Date(run.createdAt).toLocaleString("ru-RU")}</td>
                    <td>
                      <button className="secondary-btn tiny" onClick={() => actions.reopenRun(repo.repoId, run)}>
                        Открыть
                      </button>
                    </td>
                  </tr>
                ))}
                {workflow.runs.length === 0 ? (
                  <tr>
                    <td colSpan={8}><em>Запуски не найдены.</em></td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function buildSuggestionPreview(suggestion: Suggestion): string {
  const lines = suggestion.body
    .split(/[\r\n]+/g)
    .map((line) => line.trim())
    .filter(Boolean);

  const preview = lines.slice(0, 3).join("\n");

  return [
    `// ${suggestion.filePath}:${suggestion.lineStart}-${suggestion.lineEnd}`,
    preview || "// Для этого предложения нет доступного patch в snapshot.",
  ].join("\n");
}

interface DiffPreviewLine {
  kind: "add" | "del" | "ctx";
  oldLine: number | null;
  newLine: number | null;
  text: string;
}

function buildDiffPreview(suggestion: Suggestion, patch: string): DiffPreviewLine[] {
  const parsed = parseUnifiedPatchLines(patch);
  if (parsed.length === 0) {
    return [];
  }

  const targetStart = Math.max(1, suggestion.lineStart - 3);
  const targetEnd = suggestion.lineEnd + 3;

  const matchedIndices = parsed
    .map((line, index) => ({ line, index }))
    .filter(({ line }) => {
      if (line.newLine !== null) {
        return line.newLine >= targetStart && line.newLine <= targetEnd;
      }
      if (line.oldLine !== null) {
        return line.oldLine >= targetStart && line.oldLine <= targetEnd;
      }
      return false;
    })
    .map(({ index }) => index);

  if (matchedIndices.length === 0) {
    return parsed.slice(0, 16);
  }

  const start = Math.max(0, matchedIndices[0]! - 4);
  const end = Math.min(parsed.length, matchedIndices[matchedIndices.length - 1]! + 5);
  return parsed.slice(start, end);
}

function parseUnifiedPatchLines(patch: string): DiffPreviewLine[] {
  if (!patch.trim()) {
    return [];
  }

  const rows = patch.split("\n");
  const result: DiffPreviewLine[] = [];

  let oldLine = 0;
  let newLine = 0;

  for (const row of rows) {
    if (!row) {
      continue;
    }

    if (row.startsWith("@@")) {
      const match = row.match(/^@@\s-\s?(\d+)(?:,(\d+))?\s\+\s?(\d+)(?:,(\d+))?\s@@/);
      const legacyMatch = row.match(/^@@\s-(\d+)(?:,(\d+))?\s\+(\d+)(?:,(\d+))?\s@@/);
      const effective = match ?? legacyMatch;
      if (effective) {
        oldLine = Number(effective[1]);
        newLine = Number(effective[3]);
      }
      continue;
    }

    const marker = row[0];
    const text = row.slice(1);

    if (marker === "+") {
      result.push({
        kind: "add",
        oldLine: null,
        newLine,
        text,
      });
      newLine += 1;
      continue;
    }

    if (marker === "-") {
      result.push({
        kind: "del",
        oldLine,
        newLine: null,
        text,
      });
      oldLine += 1;
      continue;
    }

    if (marker === " ") {
      result.push({
        kind: "ctx",
        oldLine,
        newLine,
        text,
      });
      oldLine += 1;
      newLine += 1;
    }
  }

  return result;
}
