import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "../router";

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    let active = true;
    const check = () => fetch("/health").then((response) => {
      if (active) setBackendOnline(response.ok);
    }).catch(() => { if (active) setBackendOnline(false); });
    check();
    const timer = window.setInterval(check, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => setMobileOpen(false), [location.pathname]);

  return <div className="app-shell">
    <button className="mobile-menu" aria-label="????" onClick={() => setMobileOpen(!mobileOpen)}>
      <span /><span /><span />
    </button>
    {mobileOpen && <button className="nav-backdrop" aria-label="????" onClick={() => setMobileOpen(false)} />}
    <aside className={`sidebar ${mobileOpen ? "is-open" : ""}`}>
      <div className="brand">
        <div className="brand-mark"><span>SG</span></div>
        <div><strong>SkillGameAgent</strong><small>Unity Lab Console</small></div>
      </div>
      <nav className="main-nav" aria-label="???">
        <span className="nav-label">?????</span>
        <NavLink to="/runs" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
          <span className="nav-icon grid-icon" />????
        </NavLink>
        <NavLink to="/runs/new" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
          <span className="nav-icon plus-icon" />????
        </NavLink>
      </nav>
      <div className="sidebar-note">
        <span className="note-index">03</span>
        <p>React ?????</p><small>???? Agent????????</small>
      </div>
      <div className="backend-status">
        <span className={`connection-dot ${backendOnline ? "online" : backendOnline === false ? "offline" : "checking"}`} />
        <div><strong>{backendOnline ? "API ???" : backendOnline === false ? "API ??" : "????"}</strong>
          <small>127.0.0.1:8000</small></div>
      </div>
    </aside>
    <main className="main-content">{children}</main>
  </div>;
}
