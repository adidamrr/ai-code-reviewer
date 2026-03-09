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
    <div className="page-wrap">
      <header className="page-header">
        <p className="eyebrow">Шаг 1</p>
        <h1>Подключение Git-провайдера</h1>
        <p className="subline">Поддерживаются GitHub и GitLab. После подключения загружаем репозитории и продолжаем workflow.</p>
      </header>

      <section className="card connect-ux-card">
        <div className="connect-ux-top">
          <div className="connect-ux-icon">GH</div>
          <div>
            <p className="status-title">SCM Token Access</p>
            <p className="status-sub">Выберите провайдера и укажите персональный токен доступа.</p>
          </div>
        </div>

        <label className="field connect-token-field">
          <span>Провайдер</span>
          <select value={scmProvider} onChange={(event) => actions.setScmProvider(event.target.value as "github" | "gitlab") }>
            <option value="github">GitHub</option>
            <option value="gitlab">GitLab</option>
          </select>
        </label>

        <label className="field connect-token-field">
          <span>{scmProvider === "gitlab" ? "GitLab Personal Access Token" : "GitHub Personal Access Token (PAT)"}</span>
          <input
            value={scmProvider === "gitlab" ? gitlabToken : githubToken}
            onChange={(event) => scmProvider === "gitlab" ? actions.setGitlabToken(event.target.value) : actions.setGithubToken(event.target.value)}
            placeholder={scmProvider === "gitlab" ? "glpat-..." : "github_pat_..."}
            type="password"
          />
        </label>

        <div className="row-actions">
          <button className="primary-btn" onClick={connect} disabled={busy}>
            Подключить {scmProvider === "gitlab" ? "GitLab" : "GitHub"}
          </button>
          {session ? (
            <>
              <button
                className="secondary-btn"
                onClick={async () => {
                  await actions.disconnectScm();
                }}
                disabled={busy}
              >
                Отключить
              </button>
              <button className="secondary-btn" onClick={() => navigate("/repos")}>
                К репозиториям
              </button>
            </>
          ) : null}
        </div>
      </section>

      {session ? (
        <section className="card status-card">
          <div>
            <p className="status-title">{session.provider === "gitlab" ? "GitLab" : "GitHub"} подключен</p>
            <p className="status-sub">Пользователь: {session.githubLogin}</p>
            <p className="status-sub">Сессия активна до: {new Date(session.expiresAt).toLocaleString("ru-RU")}</p>
          </div>
          <button className="primary-btn" onClick={() => navigate("/repos")}>Открыть репозитории</button>
        </section>
      ) : null}
    </div>
  );
}
