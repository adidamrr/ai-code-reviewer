import { useNavigate } from "react-router-dom";
import { useAppStore } from "../store/app-store";

export function ConnectPage() {
  const navigate = useNavigate();
  const {
    githubToken,
    gitlabToken,
    scmProvider,
    session,
    busy,
    actions,
  } = useAppStore();

  async function connect() {
    const ok = await actions.connectScm();
    if (ok) {
      navigate("/repos");
    }
  }

  return (
    <div className="connect-page">
      <section className="connect-hero">
        <div className="connect-hero-copy">
          <p className="eyebrow">AI PR Review</p>
          <h1>Подключи Git и заходи сразу в review workspace.</h1>
          <p className="connect-hero-text">
            Новый flow убирает ручной шум: выбираешь репозиторий, выбираешь PR, нажимаешь analyze и сразу попадаешь
            в живой cockpit с job timeline, результатами и публикацией комментариев.
          </p>
        </div>

        <div className="connect-hero-grid">
          <article className="connect-stat-card">
            <span>Flow</span>
            <strong>Connect → Choose PR → Analyze</strong>
          </article>
          <article className="connect-stat-card">
            <span>Output</span>
            <strong>Snapshot, findings, publish</strong>
          </article>
          <article className="connect-stat-card">
            <span>Providers</span>
            <strong>GitHub + GitLab</strong>
          </article>
        </div>
      </section>

      <section className="connect-panel card">
        <div className="connect-panel-top">
          <div>
            <p className="eyebrow">Step 1</p>
            <h2>Подключение Git-провайдера</h2>
            <p className="subline">
              Введи PAT и сразу переходи к репозиториям. Экран намеренно один: без отдельного boring onboarding-step.
            </p>
          </div>
          <div className="status-badge ok">secure token input</div>
        </div>

        <div className="provider-grid">
          <button
            className={`provider-tile ${scmProvider === "github" ? "active" : ""}`}
            onClick={() => actions.setScmProvider("github")}
            type="button"
          >
            <span className="provider-mark">GH</span>
            <strong>GitHub</strong>
            <p>Personal access token</p>
          </button>

          <button
            className={`provider-tile ${scmProvider === "gitlab" ? "active" : ""}`}
            onClick={() => actions.setScmProvider("gitlab")}
            type="button"
          >
            <span className="provider-mark gitlab">GL</span>
            <strong>GitLab</strong>
            <p>Personal access token</p>
          </button>
        </div>

        <label className="field connect-token-field">
          <span>{scmProvider === "gitlab" ? "GitLab Personal Access Token" : "GitHub Personal Access Token"}</span>
          <input
            value={scmProvider === "gitlab" ? gitlabToken : githubToken}
            onChange={(event) =>
              scmProvider === "gitlab"
                ? actions.setGitlabToken(event.target.value)
                : actions.setGithubToken(event.target.value)
            }
            placeholder={scmProvider === "gitlab" ? "glpat-..." : "github_pat_..."}
            type="password"
          />
        </label>

        <div className="connect-actions">
          <button className="primary-btn connect-cta" onClick={connect} disabled={busy}>
            {busy ? "Подключаем..." : `Подключить ${scmProvider === "gitlab" ? "GitLab" : "GitHub"} и продолжить`}
          </button>

          {session ? (
            <>
              <button className="secondary-btn" onClick={() => navigate("/repos")}>
                Открыть репозитории
              </button>
              <button
                className="secondary-btn"
                onClick={async () => {
                  await actions.disconnectScm();
                }}
                disabled={busy}
              >
                Отключить
              </button>
            </>
          ) : null}
        </div>

        <div className="connect-trust-row">
          <span>Токен хранится локально в браузерном state этого UI</span>
          <span>Далее можно сразу переходить к PR-centric workflow</span>
        </div>
      </section>

      {session ? (
        <section className="connected-state card">
          <div>
            <p className="eyebrow">Connected</p>
            <h3>{session.provider === "gitlab" ? "GitLab" : "GitHub"} подключен</h3>
            <p className="subline">Пользователь: {session.githubLogin}</p>
            <p className="subline">Сессия активна до: {new Date(session.expiresAt).toLocaleString("ru-RU")}</p>
          </div>
          <button className="primary-btn" onClick={() => navigate("/repos")}>
            Перейти в repository gallery
          </button>
        </section>
      ) : null}
    </div>
  );
}
