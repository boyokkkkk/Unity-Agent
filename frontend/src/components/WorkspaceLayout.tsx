import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api";
import type { RunRecord } from "../types";
import { Link, NavLink, useLocation } from "../router";
import { Icon } from "./Icon";

function projectName(path: string) {
  if (!path) return "未指定工程";
  return path.replaceAll("\\", "/").split("/").filter(Boolean).at(-1) || path;
}

export function WorkspaceLayout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [runs, setRuns] = useState<RunRecord[]>([]);

  useEffect(() => {
    let active = true;
    const check = () => fetch("/health").then((response) => active && setBackendOnline(response.ok))
      .catch(() => active && setBackendOnline(false));
    check();
    const timer = window.setInterval(check, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => setMobileOpen(false), [location.pathname]);
  useEffect(() => {
    let active = true;
    const load = () => api.listRuns().then((items) => active && setRuns(items)).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 8000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const projects = useMemo(() => {
    const groups = new Map<string, RunRecord[]>();
    runs.forEach((run) => {
      const path = run.project_path || "未指定工程";
      groups.set(path, [...(groups.get(path) || []), run]);
    });
    return [...groups.entries()].slice(0, 5);
  }, [runs]);

  return <div className="app-shell workspace-shell">
    <button className="mobile-menu" aria-label="打开导航" onClick={() => setMobileOpen(!mobileOpen)}><span /><span /><span /></button>
    {mobileOpen && <button className="nav-backdrop" aria-label="关闭导航" onClick={() => setMobileOpen(false)} />}
    <aside className={`sidebar workspace-sidebar ${mobileOpen ? "is-open" : ""}`}>
      <Link className="brand" to="/workspace" aria-label="返回 Unity Agent 工作台">
        <div className="brand-mark"><span>UA</span></div><div><strong>Unity Agent</strong><small>Project operator</small></div>
      </Link>
      <Link className="sidebar-create" to="/runs/new"><Icon name="plus" size={16} />新建任务</Link>
      <nav className="main-nav" aria-label="主导航">
        <span className="nav-label">工作空间</span>
        <NavLink to="/workspace" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}><Icon name="home" />工作台</NavLink>
        <NavLink to="/runs" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}><Icon name="messages" />任务与对话</NavLink>
        <NavLink to="/plans" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}><Icon name="list" />执行计划</NavLink>
        <NavLink to="/skills" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}><Icon name="sparkles" />Skill 能力</NavLink>
      </nav>
      <section className="project-nav" aria-label="项目任务">
        <div className="project-nav-title"><span className="nav-label">项目</span><span>{projects.length}</span></div>
        {projects.length ? projects.map(([path, items]) => <div className="project-group" key={path}>
          <div className="project-row"><Icon name="folder" size={15} /><strong title={path}>{projectName(path)}</strong><span>{items.length}</span></div>
          {items.slice(0, 2).map((run) => <Link className="project-task" to={`/runs/${run.run_id}`} key={run.run_id}>
            <i className={`task-state ${run.status}`} /><span>{run.task}</span></Link>)}
        </div>) : <div className="project-empty">创建任务后，项目会自动出现在这里。</div>}
      </section>
      <div className="backend-status"><span className={`connection-dot ${backendOnline ? "online" : backendOnline === false ? "offline" : "checking"}`} />
        <div><strong>{backendOnline ? "Agent Runtime 在线" : backendOnline === false ? "Agent Runtime 离线" : "正在检查"}</strong><small>LOCAL · 127.0.0.1:8000</small></div></div>
    </aside>
    <main className="main-content">{children}</main>
  </div>;
}
