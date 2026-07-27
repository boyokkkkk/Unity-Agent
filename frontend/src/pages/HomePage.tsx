import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { Link } from "../router";
import type { RunRecord } from "../types";
import { formatDate } from "../utils";
import "../workspace.css";

function projectName(path: string) {
  return path.replaceAll("\\", "/").split("/").filter(Boolean).at(-1) || "未指定工程";
}

const stations = [
  { title: "任务规划", detail: "拆解目标与执行步骤", icon: "list" as const, code: "PLAN" },
  { title: "代码工位", detail: "读取与修改 Unity C#", icon: "code" as const, code: "CODE" },
  { title: "Unity 工位", detail: "编译、场景与资源检查", icon: "box" as const, code: "UNITY" },
  { title: "验证工位", detail: "测试、Diff 与交付", icon: "check" as const, code: "TEST" },
];

export function HomePage() {
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try { setRuns(await api.listRuns()); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "无法连接 Agent Runtime"); }
    finally { if (!quiet) setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => load(true), 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const active = runs.filter((run) => run.status === "running" || run.status === "pending");
  const completed = runs.filter((run) => run.status === "submitted").length;
  const projects = useMemo(() => new Set(runs.map((run) => run.project_path).filter(Boolean)), [runs]);
  const latest = runs.slice(0, 5);
  const focus = active[0] || runs[0];

  return <div className="page home-page">
    <header className="home-header"><div><span className="eyebrow">Unity Agent Workspace</span><h1>下午好，准备继续创造吗？</h1>
      <p>从项目任务出发，让 Agent 在代码、Unity 与验证工位之间自主协作。</p></div>
      <div className="home-actions"><button className="icon-button" onClick={() => load()} aria-label="刷新工作台"><Icon name="refresh" /></button>
        <Link className="button button-primary" to="/runs/new"><Icon name="plus" size={16} />创建任务</Link></div></header>

    <section className="workspace-stats" aria-label="工作空间概览">
      <div><span className="stat-icon purple"><Icon name="activity" /></span><strong>{active.length}</strong><small>正在执行</small></div>
      <div><span className="stat-icon blue"><Icon name="folder" /></span><strong>{projects.size}</strong><small>活跃项目</small></div>
      <div><span className="stat-icon green"><Icon name="check" /></span><strong>{completed}</strong><small>成功交付</small></div>
      <div><span className="stat-icon orange"><Icon name="clock" /></span><strong>{runs.length}</strong><small>累计任务</small></div>
    </section>

    <div className="home-grid">
      <section className="pixel-workspace panel">
        <div className="pixel-scene-heading"><div><span className="eyebrow">Live Agent Map</span><h2>Agent 像素工作室</h2></div>
          <span className={`scene-live ${active.length ? "active" : ""}`}><i />{active.length ? `${active.length} 个 Agent 工作中` : "等待新任务"}</span></div>
        <div className="pixel-scene">
          <div className="scene-window"><span /><span /><span /><i /></div>
          <div className="scene-board"><span>SPRINT</span><b>{focus ? projectName(focus.project_path) : "NO PROJECT"}</b><i /></div>
          <div className="scene-plant"><i /><i /><b /></div><div className="scene-floor-lines" />
          <div className="station-grid">{stations.map((station, index) => <article className={`pixel-station ${active.length && index === (active.length - 1) % 4 ? "is-active" : ""}`} key={station.code}>
            <div className="station-screen"><Icon name={station.icon} size={15} /><span>{station.code}</span></div>
            <div className="station-desk"><i /><i /></div><div className="station-chair" />
            {active.length > 0 && index <= Math.min(active.length, 3) && <div className={`pixel-agent agent-${index}`} aria-label={`${station.title} Agent`}>
              <span className="agent-head"><i /><i /></span><span className="agent-body" /><span className="agent-leg left" /><span className="agent-leg right" /></div>}
            <div className="station-caption"><strong>{station.title}</strong><span>{station.detail}</span></div>
          </article>)}</div>
          <div className="scene-status"><span className="pixel-avatar">UA</span><p><strong>{focus ? focus.task : "工作室当前空闲"}</strong>
            <small>{focus ? `${projectName(focus.project_path)} · ${focus.status === "running" ? "正在自主执行" : "最近任务"}` : "创建第一个项目任务，观察 Agent 在不同工位间推进工作。"}</small></p>
            {focus && <Link to={`/runs/${focus.run_id}`} aria-label="查看当前任务"><Icon name="arrow" /></Link>}</div>
        </div>
      </section>

      <aside className="activity-panel panel"><div className="panel-heading"><div><span className="eyebrow">Mission Feed</span><h2>最近任务</h2></div><Link to="/runs">查看全部</Link></div>
        {loading ? <div className="compact-state">正在同步任务…</div> : error ? <div className="compact-state error">{error}</div> : latest.length ?
          <div className="activity-list">{latest.map((run) => <Link className="activity-item" to={`/runs/${run.run_id}`} key={run.run_id}>
            <span className={`activity-glyph ${run.status}`}><Icon name={run.status === "submitted" ? "check" : run.status === "running" ? "activity" : "clock"} size={15} /></span>
            <span><strong>{run.task}</strong><small>{projectName(run.project_path)} · {formatDate(run.created_at)}</small></span><Icon name="chevron" size={15} />
          </Link>)}</div> : <div className="compact-state">还没有任务记录。<Link to="/runs/new">立即创建</Link></div>}
        <div className="activity-footer"><div><span>Runtime</span><strong><i /> Local API</strong></div><div><span>Mode</span><strong>Safe write</strong></div></div>
      </aside>
    </div>

    <section className="home-bottom-grid">
      <div className="panel focus-card"><span className="focus-card-icon"><Icon name="sparkles" /></span><div><span className="eyebrow">Recommended next</span><h3>为当前项目制定下一步计划</h3><p>先让 Agent 分析工程，再按可验证的步骤执行，减少无效试错。</p></div><Link className="button button-secondary" to="/runs/new">开始规划<Icon name="arrow" size={15} /></Link></div>
      <div className="panel runtime-card"><div><span className="eyebrow">Execution model</span><h3>计划 → 编码 → Unity → 验证</h3></div><div className="runtime-flow"><span>01</span><i /><span>02</span><i /><span>03</span><i /><span>04</span></div></div>
    </section>
  </div>;
}
