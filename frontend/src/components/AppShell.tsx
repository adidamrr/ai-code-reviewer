import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAppStore } from "../store/app-store";

const REVIEW_STATUS_LABELS = {
  ready: "snapshot",
  running: "running",
  results: "results",
  published: "published",
} as const;

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { session, recentReviews, actions } = useAppStore();
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname]);

  const activeReviewKey = useMemo(() => {
    const match = location.pathname.match(/^\/repos\/([^/]+)\/reviews\/(\d+)/);
    if (!match) {
      return null;
    }
    return `${decodeURIComponent(match[1] ?? "")}:${Number(match[2])}`;
  }, [location.pathname]);

  return (
    <div className={`shell-root ${navOpen ? "nav-open" : ""}`}>
      <button
        type="button"
        className={`shell-backdrop ${navOpen ? "visible" : ""}`}
        aria-label="Закрыть меню"
        onClick={() => setNavOpen(false)}
      />

      <aside className="shell-sidebar">
        <div className="shell-sidebar-inner">
          <div className="brand-box shell-brand-box">
            <div className="brand-logo">SR</div>
            <div>
              <p className="brand-title">SWAGReviewer</p>
              <p className="brand-sub">PR Review Cockpit</p>
            </div>
          </div>

          <nav className="primary-nav shell-primary-nav">
            <NavLink to="/repos" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              Репозитории
            </NavLink>
            <NavLink to="/connect" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              Провайдер
            </NavLink>
          </nav>

          <section className="rail-section">
            <header className="rail-section-head">
              <p className="rail-section-kicker">Review Queue</p>
              <h3>Синхронизированные PR</h3>
            </header>

            {recentReviews.length === 0 ? (
              <p className="empty-note shell-empty-note">
                После первого snapshot здесь появятся PR с последней активностью.
              </p>
            ) : null}

            <ul className="recent-list review-list">
              {recentReviews.map((review) => {
                const active = activeReviewKey === review.reviewKey;
                const tone = review.status === "running" ? "warn" : "ok";

                return (
                  <li key={review.reviewKey}>
                    <button
                      className={`recent-item review-item ${active ? "active" : ""}`}
                      onClick={() => {
                        actions.selectRepo(review.repoId);
                        actions.selectPullRequest(review.repoId, review.prNumber);
                        navigate(`/repos/${review.repoId}/reviews/${review.prNumber}`);
                      }}
                    >
                      <div className="recent-main">
                        <p className="recent-name">{review.repoFullName}</p>
                        <p className="review-pr-line">#{review.prNumber} · {review.prTitle}</p>
                        <p className="recent-time">{formatRelativeDate(review.lastOpenedAt)}</p>
                      </div>
                      <span className={`status-badge ${tone}`}>{REVIEW_STATUS_LABELS[review.status]}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>

          <footer className="sidebar-footer shell-footer">
            <p className="session-line">
              {session
                ? `${session.provider.toUpperCase()} · ${session.githubLogin}`
                : "Провайдер не подключен"}
            </p>
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
            ) : (
              <button className="secondary-btn full" onClick={() => navigate("/connect")}>
                Подключить SCM
              </button>
            )}
          </footer>
        </div>
      </aside>

      <div className="shell-main">
        <header className="shell-topbar">
          <button
            type="button"
            className="shell-menu-btn"
            aria-label="Открыть меню"
            onClick={() => setNavOpen((current) => !current)}
          >
            <span />
            <span />
            <span />
          </button>

          <div className="shell-topbar-copy">
            <p className="eyebrow">Review cockpit</p>
            <strong>{resolveTopbarTitle(location.pathname)}</strong>
          </div>

          <div className="shell-topbar-meta">
            <span className="pill shell-pill">
              {session ? `${session.provider.toUpperCase()} connected` : "No provider"}
            </span>
          </div>
        </header>

        <main className="shell-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function resolveTopbarTitle(pathname: string): string {
  if (pathname === "/repos") {
    return "Repository gallery";
  }
  if (pathname.startsWith("/repos/")) {
    return "Review workspace";
  }
  return "SWAGReviewer";
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
