import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { Link } from "../router";
import type { RunRecord } from "../types";
import { formatDate } from "../utils";

function projectName(path: string) {
  return path.replaceAll("\\", "/").split("/").filter(Boolean).at(-1) || "未指定工程";
}

const stations = [
  { title: "任务规划", detail: "分析工程并拆解任务", icon: "list" as const, code: "PLAN", bubble: "正在理解目标，建立可验证的执行计划。" },
  { title: "Skill 协作", detail: "调用专业能力与工具", icon: "sparkles" as const, code: "SKILL", bubble: "正在选择 Skill，并整理需要调用的工具。" },
  { title: "代码执行", detail: "读取、修改 Unity 工程", icon: "code" as const, code: "CODE", bubble: "正在编辑代码与资源，变更会记录到 Diff。" },
  { title: "验证交付", detail: "编译、测试与生成产物", icon: "check" as const, code: "VERIFY", bubble: "正在运行验证，并整理最终答案与产物。" },
];

function stageIndex(run: RunRecord | undefined) {
  if (!run) return -1;
  if (run.status === "pending") return 0;
  if (run.status === "running") return 2;
  return 3;
}

export function ProjectWorkspacePage() {
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [selectedStation, setSelectedStation] = useState(0);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try { setRuns(await api.listRuns()); setError(""); }
    catch { setRuns([]); setError("Agent Runtime 当前离线"); }
    finally { if (!quiet) setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => load(true), 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const projects = useMemo(() => {
    const groups = new Map<string, RunRecord[]>();
    runs.forEach((run) => {
      const path = run.project_path || "未指定工程";
      groups.set(path, [...(groups.get(path) || []), run]);
    });
    return [...groups.entries()].sort((a, b) => (b[1][0]?.created_at || "").localeCompare(a[1][0]?.created_at || ""));
  }, [runs]);

  useEffect(() => {
    if (!selectedPath || !projects.some(([path]) => path === selectedPath)) setSelectedPath(projects[0]?.[0] || "");
  }, [projects, selectedPath]);

  const projectRuns = projects.find(([path]) => path === selectedPath)?.[1] || [];
  const active = projectRuns.filter((run) => run.status === "running" || run.status === "pending");
  const completed = projectRuns.filter((run) => run.status === "submitted").length;
  const focus = active[0] || projectRuns[0];
  const focusStage = stageIndex(focus);
  const latest = projectRuns.slice(0, 5);

  useEffect(() => { if (focusStage >= 0) setSelectedStation(focusStage); }, [focus?.run_id, focusStage]);

  return <div className="page home-page">
    <div className="project-switcher" role="tablist" aria-label="切换项目工作台">
      <span className="project-switcher-label"><Icon name="folder" size={15} />项目工作台</span>
      {projects.map(([path, items]) => {
        const isRunning = items.some((run) => run.status === "running" || run.status === "pending");
        return <button type="button" role="tab" aria-selected={selectedPath === path} className={`project-chip ${selectedPath === path ? "active" : ""}`}
          key={path} onClick={() => setSelectedPath(path)}><i className={isRunning ? "running" : ""} />{projectName(path)}<small>{items.length}</small></button>;
      })}
      {!projects.length && <span className="project-chip active"><i />等待第一个项目</span>}
    </div>

    <header className="project-context">
      <div><span className="eyebrow">Unity Agent / Project workspace</span><h1>{selectedPath ? projectName(selectedPath) : "创建你的第一个项目任务"}</h1>
        <p className="project-context-path">{selectedPath || "工作台会按项目独立呈现任务、Agent 状态和执行产物。"}</p></div>
      <div className="project-context-actions"><button className="icon-button" onClick={() => load()} aria-label="刷新项目工作台"><Icon name="refresh" /></button>
        <Link className="button button-primary" to="/runs/new"><Icon name="plus" size={16} />新建任务</Link></div>
    </header>

    <section className="workspace-stats" aria-label="当前项目概览">
      <div><span className="stat-icon purple"><Icon name="activity" /></span><strong>{active.length}</strong><small>正在执行</small></div>
      <div><span className="stat-icon blue"><Icon name="messages" /></span><strong>{projectRuns.length}</strong><small>任务与对话</small></div>
      <div><span className="stat-icon green"><Icon name="check" /></span><strong>{completed}</strong><small>成功交付</small></div>
      <div><span className="stat-icon orange"><Icon name="git" /></span><strong>{focus ? focus.status : "idle"}</strong><small>项目状态</small></div>
    </section>

    <div className="home-grid">
      <section className="pixel-workspace panel">
        <div className="pixel-scene-heading"><div><span className="eyebrow">Interactive Agent Map</span><h2>项目协作空间</h2></div>
          <div className="project-scene-meta"><span className={`scene-live ${active.length ? "active" : ""}`}><i />{active.length ? `${active.length} 个任务执行中` : "项目当前空闲"}</span></div></div>
        <div className="pixel-scene">
          <div className="scene-window"><span /><span /><span /><i /></div>
          <div className="scene-board"><span>PROJECT</span><b>{selectedPath ? projectName(selectedPath) : "NO PROJECT"}</b><i /></div>
          <div className="scene-plant"><i /><i /><b /></div><div className="scene-floor-lines" />
          <div className="station-grid">{stations.map((station, index) => <article role="button" tabIndex={0}
            aria-label={`查看${station.title}状态`} aria-pressed={selectedStation === index}
            className={`pixel-station ${focusStage === index ? "is-active" : ""} ${selectedStation === index ? "is-selected" : ""}`}
            key={station.code} onClick={() => setSelectedStation(index)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedStation(index); }}>
            <div className="station-screen"><Icon name={station.icon} size={15} /><span>{station.code}</span></div>
            <div className="station-desk"><i /><i /></div><div className="station-chair" />
            <div className={`pixel-agent sprite-agent sprite-char-${index} phase-${index} ${focusStage === index ? "is-working" : "is-idle"}`}
              aria-label={`${station.title} Agent ${focusStage === index ? "正在工作" : "待命"}`} />
            {selectedStation === index && <div className="agent-bubble"><strong>{focusStage === index ? "Agent 正在这里" : station.code}</strong>
              {focusStage === index && focus ? `${station.bubble} 当前任务：${focus.task}` : station.bubble}</div>}
            <div className="station-caption"><strong>{station.title}</strong><span>{station.detail}</span></div>
          </article>)}</div>
          <div className="scene-status"><span className="pixel-avatar">UA</span><p><strong>{focus ? focus.task : "等待项目任务"}</strong>
            <small>{focus ? `${projectName(focus.project_path)} · ${focus.status === "running" ? "Agent 正在自主执行" : `状态：${focus.status}`}` : "创建任务后，Agent 会在规划、Skill、代码和验证阶段之间移动。"}</small></p>
            {focus && <Link to={`/runs/${focus.run_id}`} aria-label="打开当前任务对话"><Icon name="arrow" /></Link>}</div>
        </div>
      </section>

      <aside className="activity-panel panel"><div className="panel-heading"><div><span className="eyebrow">Project conversations</span><h2>任务与对话</h2></div><Link to="/runs">查看全部</Link></div>
        {loading ? <div className="compact-state">正在同步任务…</div> : error ? <div className="compact-state">{error}<small>启动后端后，项目任务会自动同步到这里</small></div> : latest.length ?
          <div className="activity-list">{latest.map((run) => <Link className="activity-item" to={`/runs/${run.run_id}`} key={run.run_id}>
            <span className={`activity-glyph ${run.status}`}><Icon name={run.status === "submitted" ? "check" : run.status === "running" ? "activity" : "clock"} size={15} /></span>
            <span><strong>{run.task}</strong><small>{run.status} · {formatDate(run.created_at)}</small></span><Icon name="chevron" size={15} />
          </Link>)}</div> : <div className="compact-state">当前项目还没有任务。<Link to="/runs/new">创建任务</Link></div>}
        <div className="activity-footer"><div><span>Project</span><strong>{selectedPath ? projectName(selectedPath) : "—"}</strong></div><div><span>Execution</span><strong>Safe workspace</strong></div></div>
      </aside>
    </div>
  </div>;
}
