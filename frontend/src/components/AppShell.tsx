import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAppStore } from "../store/app-store";

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { session, recentRepos, actions, getRepoStatus, selectedRepoId } = useAppStore();

  return (
    <div className="shell-root">
      <aside className="shell-sidebar">
        <div className="brand-box">
          <div className="brand-logo">SR</div>
          <div>
            <p className="brand-title">SWAGReviewer</p>
            <p className="brand-sub">AI PR Review</p>
          </div>
        </div>

        <nav className="primary-nav">
          <NavLink to="/connect" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            Подключение Git SCM
          </NavLink>
          <NavLink to="/repos" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            Репозитории
          </NavLink>
        </nav>

        <section className="recent-section">
          <header>
            <h3>Недавние репозитории</h3>
          </header>

          {recentRepos.length === 0 ? <p className="empty-note">Пока нет истории репозиториев.</p> : null}

          <ul className="recent-list">
            {recentRepos.map((repo) => {
              const status = getRepoStatus(repo.repoId);
              const active = selectedRepoId === repo.repoId && location.pathname.includes("/workspace");

              return (
                <li key={repo.repoId}>
                  <button
                    className={`recent-item ${active ? "active" : ""}`}
                    onClick={() => {
                      actions.selectRepo(repo.repoId);
                      navigate(`/repos/${repo.repoId}/workspace`);
                    }}
                  >
                    <div className="recent-main">
                      <p className="recent-name">{repo.fullName}</p>
                      <p className="recent-time">{formatRelativeDate(repo.lastOpenedAt)}</p>
                    </div>
                    <span className={`status-badge ${status.tone}`}>{status.label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>

        <footer className="sidebar-footer">
          <p className="session-line">{session ? `Сессия: ${session.provider.toUpperCase()} / ${session.githubLogin}` : "Сессия: не подключена"}</p>
          {session ? (
            <button
              className="secondary-btn full"
              onClick={async () => {
                await actions.disconnectScm();
                navigate("/connect");
              }}
            >
              Отключить SCM
            </button>
          ) : null}
        </footer>
      </aside>

      <main className="shell-content">
        <Outlet />
      </main>
    </div>
  );
}

function formatRelativeDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const diffMs = Date.now() - date.getTime();
  const minutes = Math.floor(diffMs / (60 * 1000));

  if (minutes < 1) {
    return "только что";
  }
  if (minutes < 60) {
    return `${minutes} мин назад`;
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} ч назад`;
  }

  const days = Math.floor(hours / 24);
  return `${days} дн назад`;
}
