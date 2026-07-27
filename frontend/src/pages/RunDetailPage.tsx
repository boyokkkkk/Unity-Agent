import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "../router";
import { api } from "../api";
import { EmptyState, ErrorState, LoadingState, StatusBadge } from "../components/ui";
import { connectRunEventStream, mergeRunEvents } from "../runEventStream";
import type { ArtifactInfo, RunEvent, RunRecord, Trajectory } from "../types";
import { terminalStatuses } from "../types";
import { eventTitle, eventTone, formatBytes, formatDate, formatDuration, stringValue } from "../utils";

type DetailTab = "timeline" | "diff" | "validation" | "artifacts";

function numberAt(source: Record<string, unknown> | undefined, ...path: string[]): number | null {
  let value: unknown = source;
  for (const key of path) {
    if (!value || typeof value !== "object") return null;
    value = (value as Record<string, unknown>)[key];
  }
  return typeof value === "number" ? value : null;
}

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<RunRecord | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [trajectory, setTrajectory] = useState<Trajectory | null>(null);
  const [diff, setDiff] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>("timeline");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [streamState, setStreamState] = useState<"idle" | "connected" | "retrying">("idle");
  const [cancelling, setCancelling] = useState(false);

  const loadRun = useCallback(async () => {
    const next = await api.getRun(runId);
    setRun(next);
    return next;
  }, [runId]);

  const loadArtifacts = useCallback(async () => {
    try {
      const [items, nextDiff, nextTrajectory] = await Promise.all([
        api.artifacts(runId), api.diff(runId), api.trajectory(runId).catch(() => null),
      ]);
      setArtifacts(items); setDiff(nextDiff); setTrajectory(nextTrajectory);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载运行产物");
    }
  }, [runId]);

  const loadInitial = useCallback(async () => {
    setLoading(true);
    try {
      const [, history] = await Promise.all([loadRun(), api.eventHistory(runId)]);
      setEvents(history);
      await loadArtifacts();
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载运行详情");
    } finally {
      setLoading(false);
    }
  }, [loadArtifacts, loadRun, runId]);

  useEffect(() => { loadInitial(); }, [loadInitial]);

  useEffect(() => {
    if (!run || terminalStatuses.has(run.status)) return;
    const timer = window.setInterval(() => loadRun().catch(() => undefined), 15000);
    return () => window.clearInterval(timer);
  }, [loadRun, run?.status]);

  useEffect(() => {
    if (!run || terminalStatuses.has(run.status) || loading) return;
    const after = events.reduce((largest, event) => Math.max(largest, event.id), 0);
    return connectRunEventStream({
      runId,
      after,
      onEvent: (item) => {
        setEvents((current) => mergeRunEvents(current, item));
        if (["run_status_changed", "run_cancelled", "run_end"].includes(item.event)) {
          loadRun().then((next) => { if (terminalStatuses.has(next.status)) loadArtifacts(); }).catch(() => undefined);
        }
      },
      onState: (state) => {
        setStreamState(state === "connected" ? "connected" : state === "reconnecting" ? "retrying" : "idle");
      },
      onError: (reason) => setError(`实时事件格式错误：${reason.message}`),
    });
  }, [loadArtifacts, loadRun, loading, run?.status, runId]);

  useEffect(() => {
    if (run && terminalStatuses.has(run.status)) loadArtifacts();
  }, [loadArtifacts, run?.status]);

  const selectedEvent = useMemo(() => events.find((item) => item.id === selectedId) || null, [events, selectedId]);
  const validationEvents = events.filter((item) => item.event.startsWith("validation_"));
  const modelCalls = numberAt(trajectory?.info as Record<string, unknown> | undefined, "model_stats", "api_calls");
  const modelCost = numberAt(trajectory?.info as Record<string, unknown> | undefined, "model_stats", "instance_cost");

  async function cancel() {
    if (!run || !window.confirm("确认取消这个任务？Worker 进程及其子进程将被终止。")) return;
    setCancelling(true);
    try { setRun(await api.cancelRun(run.run_id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "取消任务失败"); }
    finally { setCancelling(false); }
  }

  if (loading) return <div className="page"><LoadingState label="正在加载运行详情" /></div>;
  if (!run) return <div className="page"><ErrorState message={error || "运行不存在"} retry={loadInitial} /></div>;

  return <div className="page run-detail-page">
    <div className="breadcrumb"><Link to="/runs">实验列表</Link><span>/</span><strong>{run.run_id}</strong></div>
    <header className="detail-header">
      <div className="detail-title"><div className="run-kicker"><StatusBadge status={run.status} pulse={run.status === "running"} />
        {run.status === "running" && <span className={`stream-indicator ${streamState}`}><i />
          {streamState === "connected" ? "实时连接" : "正在重连"}</span>}</div>
        <h1>{run.task}</h1><p><code>{run.run_id}</code><span>·</span>{run.project_path}</p></div>
      <div className="detail-actions"><button className="button button-secondary" onClick={() => loadInitial()}>↻ 刷新</button>
        {!terminalStatuses.has(run.status) && <button className="button button-danger" disabled={cancelling} onClick={cancel}>
          {cancelling ? "正在取消" : "取消任务"}</button>}</div>
    </header>

    {error && <div className="inline-alert" role="alert"><span>!</span><p>{error}</p><button aria-label="关闭提示" onClick={() => setError("")}>×</button></div>}
    {run.error && <div className="inline-alert persistent" role="alert"><span>!</span><div><strong>{run.exit_status || "运行异常"}</strong><p>{run.error}</p></div></div>}

    <section className="run-facts">
      <div><span>退出状态</span><strong>{run.exit_status || (run.status === "running" ? "Agent 运行中" : "等待 Worker")}</strong></div>
      <div><span>运行耗时</span><strong>{formatDuration(run.started_at, run.finished_at)}</strong></div>
      <div><span>模型调用</span><strong>{modelCalls ?? "—"}</strong></div>
      <div><span>模型成本</span><strong>{modelCost === null ? "—" : `$${modelCost.toFixed(4)}`}</strong></div>
      <div><span>事件数量</span><strong>{events.length}</strong></div>
    </section>

    <nav className="detail-tabs" aria-label="运行详情">
      {([ ["timeline", "运行时间线", events.length], ["diff", "代码 Diff", null],
        ["validation", "验证结果", validationEvents.length], ["artifacts", "产物", artifacts.length] ] as const)
        .map(([value, label, count]) => <button key={value} className={activeTab === value ? "active" : ""}
          onClick={() => setActiveTab(value)}>{label}{count !== null && <span>{count}</span>}</button>)}
    </nav>

    {activeTab === "timeline" && <Timeline events={events} selected={selectedEvent}
      onSelect={(event) => setSelectedId(event.id)} />}
    {activeTab === "diff" && <DiffPanel diff={diff} running={!terminalStatuses.has(run.status)} />}
    {activeTab === "validation" && <ValidationPanel events={validationEvents} running={!terminalStatuses.has(run.status)} />}
    {activeTab === "artifacts" && <ArtifactsPanel artifacts={artifacts} />}
  </div>;
}

function Timeline({ events, selected, onSelect }: {
  events: RunEvent[]; selected: RunEvent | null; onSelect: (event: RunEvent) => void;
}) {
  if (!events.length) return <EmptyState title="还没有运行事件" detail="Worker 启动并写入事件后，时间线会自动更新。" />;
  return <div className="timeline-layout">
    <section className="timeline-panel panel"><div className="timeline-heading"><div><span className="eyebrow">Live Trace</span>
      <h2>Agent 时间线</h2></div><span>{events.length} 个事件</span></div>
      <div className="timeline-list">{events.map((item, index) => <button key={item.id}
        className={`timeline-event tone-${eventTone(item.event)} ${selected?.id === item.id ? "selected" : ""}`}
        onClick={() => onSelect(item)}>
        <span className="timeline-rail"><i />{index < events.length - 1 && <b />}</span>
        <span className="event-body"><span className="event-meta"><strong>{eventTitle(item)}</strong>
          <time>{formatDate((item.data.ts as string) || item.created_at)}</time></span>
          <EventSummary event={item} /></span><span className="event-arrow">→</span>
      </button>)}</div>
    </section>
    <EventInspector event={selected} />
  </div>;
}

function EventSummary({ event }: { event: RunEvent }) {
  const data = event.data;
  if (event.event === "tool_start") return <code>{stringValue(data.command) || "bash"}</code>;
  if (event.event === "tool_end") return <span className="event-summary">返回码 {stringValue(data.returncode)} · {stringValue(data.output).slice(0, 100) || "无输出"}</span>;
  if (event.event.startsWith("validation")) return <span className="event-summary">{stringValue(data.validator || data.status || "验证事件")}</span>;
  if (event.event === "run_status_changed") return <span className="event-summary">{stringValue(data.status)}</span>;
  return <span className="event-summary">{stringValue(data.model || data.backend || data.exit_status || data.status || "运行事件")}</span>;
}

function EventInspector({ event }: { event: RunEvent | null }) {
  if (!event) return <aside className="inspector-panel panel inspector-empty"><div className="inspector-mark">·</div>
    <h3>选择一个事件</h3><p>点击左侧时间线，查看命令、输出和完整事件数据。</p></aside>;
  const data = event.data;
  const isTool = event.event.startsWith("tool_");
  const output = stringValue(data.output || data.stdout || data.exception_info);
  return <aside className="inspector-panel panel"><div className="inspector-header"><div><span className="eyebrow">Event Inspector</span>
    <h3>{eventTitle(event)}</h3></div><span className={`event-kind tone-${eventTone(event.event)}`}>{event.event}</span></div>
    <dl className="inspector-meta"><div><dt>事件 ID</dt><dd>#{event.id}</dd></div><div><dt>发生时间</dt><dd>{formatDate(event.created_at)}</dd></div>
      {data.returncode !== undefined && <div><dt>返回码</dt><dd className={Number(data.returncode) === 0 ? "text-success" : "text-danger"}>{stringValue(data.returncode)}</dd></div>}</dl>
    {isTool && data.command !== undefined && <div className="code-block"><div className="code-label"><span>COMMAND</span><button onClick={() => navigator.clipboard.writeText(stringValue(data.command))}>复制</button></div>
      <pre><code>{stringValue(data.command)}</code></pre></div>}
    {output && <div className="code-block output-block"><div className="code-label"><span>OUTPUT</span><span>{output.length} chars</span></div><pre><code>{output}</code></pre></div>}
    {!isTool && <div className="code-block output-block"><div className="code-label"><span>EVENT PAYLOAD</span></div>
      <pre><code>{JSON.stringify(data, null, 2)}</code></pre></div>}
  </aside>;
}

function DiffPanel({ diff, running }: { diff: string | null; running: boolean }) {
  if (diff === null || diff.trim() === "") return <EmptyState title={running ? "Diff 尚未生成" : "没有代码变更"}
    detail={running ? "任务结束后会自动捕获 Git diff。" : "本次运行没有检测到 Git 变更。"} />;
  const lines = diff.split("\n");
  return <section className="panel diff-panel"><div className="diff-header"><div><span className="eyebrow">Workspace Patch</span>
    <h2>代码变更</h2></div><span>{lines.filter((line) => line.startsWith("diff --git")).length} 个文件</span></div>
    <div className="diff-code">{lines.map((line, index) => <div key={index} className={line.startsWith("+") && !line.startsWith("+++") ? "add" :
      line.startsWith("-") && !line.startsWith("---") ? "delete" : line.startsWith("@@") ? "hunk" : line.startsWith("diff") ? "file" : ""}>
      <span>{index + 1}</span><code>{line || " "}</code></div>)}</div></section>;
}

function ValidationPanel({ events, running }: { events: RunEvent[]; running: boolean }) {
  const completed = events.filter((item) => item.event === "validation_end");
  if (!events.length) return <EmptyState title={running ? "等待验证结果" : "没有结构化验证记录"}
    detail={running ? "Compile、EditMode 与 PlayMode 结果会显示在这里。" : "本次 Agent 运行没有产生结构化验证事件。"} />;
  return <section className="validation-grid">{events.map((item) => {
    const status = stringValue(item.data.status || (item.event === "validation_start" ? "running" : "unknown"));
    return <article className="panel validation-card" key={item.id}><div className={`validation-symbol ${status}`}>
      {status === "passed" ? "✓" : status === "failed" ? "×" : "…"}</div><div><span className="eyebrow">{item.event}</span>
      <h3>{stringValue(item.data.validator || "Unity Validator")}</h3><p>{stringValue(item.data.message || item.data.exception || "没有附加信息")}</p></div>
      <span className={`validation-status ${status}`}>{status}</span></article>;
  })}<div className="validation-summary panel"><span>{completed.length}</span><p>已完成验证</p></div></section>;
}

function ArtifactsPanel({ artifacts }: { artifacts: ArtifactInfo[] }) {
  if (!artifacts.length) return <EmptyState title="还没有运行产物" detail="trajectory、result 和 diff 会在 Worker 运行后生成。" />;
  return <section className="panel artifact-panel"><div className="artifact-heading"><span className="eyebrow">Run Files</span><h2>产物文件</h2></div>
    <div className="artifact-list">{artifacts.map((item) => <a key={item.name} href={item.download_url} className="artifact-row">
      <span className="file-mark">{item.name.split(".").at(-1)?.toUpperCase()}</span><span><strong>{item.name}</strong>
        <small>{formatBytes(item.size)} · {formatDate(item.created_at)}</small></span><span className="download-mark">↓</span></a>)}</div></section>;
}
