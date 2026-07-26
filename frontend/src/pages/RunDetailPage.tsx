import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "../router";
import { api } from "../api";
import { EmptyState, ErrorState, LoadingState, StatusBadge } from "../components/ui";
import type { ArtifactInfo, RunEvent, RunRecord, Trajectory } from "../types";
import { terminalStatuses } from "../types";
import { eventTitle, eventTone, formatBytes, formatDate, formatDuration, stringValue } from "../utils";

type DetailTab = "timeline" | "diff" | "validation" | "artifacts";

const streamEvents = [
  "run_created", "worker_started", "run_start", "model_start", "model_end", "tool_start", "tool_end",
  "validation_start", "validation_end", "artifact_created", "run_end", "run_status_changed", "run_cancelled",
  "worker_start_failed",
];

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
  const lastEventId = useRef(0);

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
      setError(reason instanceof Error ? reason.message : "????????");
    }
  }, [runId]);

  const loadInitial = useCallback(async () => {
    setLoading(true);
    try {
      const [, history] = await Promise.all([loadRun(), api.eventHistory(runId)]);
      setEvents(history);
      lastEventId.current = history.at(-1)?.id || 0;
      await loadArtifacts();
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "????????");
    } finally {
      setLoading(false);
    }
  }, [loadArtifacts, loadRun, runId]);

  useEffect(() => { loadInitial(); }, [loadInitial]);

  useEffect(() => {
    if (!run || terminalStatuses.has(run.status)) return;
    const timer = window.setInterval(() => loadRun().catch(() => undefined), 2000);
    return () => window.clearInterval(timer);
  }, [loadRun, run?.status]);

  useEffect(() => {
    if (!run || terminalStatuses.has(run.status) || loading) return;
    const source = new EventSource(`/api/runs/${runId}/events?after=${lastEventId.current}`);
    source.onopen = () => setStreamState("connected");
    const receive = (message: MessageEvent<string>) => {
      const id = Number(message.lastEventId);
      const item: RunEvent = {
        id, event: message.type, created_at: new Date().toISOString(), data: JSON.parse(message.data) as Record<string, unknown>,
      };
      lastEventId.current = Math.max(lastEventId.current, id);
      setEvents((current) => current.some((event) => event.id === id) ? current : [...current, item]);
      if (["run_status_changed", "run_cancelled", "run_end"].includes(message.type)) {
        loadRun().then((next) => { if (terminalStatuses.has(next.status)) loadArtifacts(); }).catch(() => undefined);
      }
    };
    streamEvents.forEach((name) => source.addEventListener(name, receive as EventListener));
    source.onerror = () => setStreamState("retrying");
    return () => { source.close(); setStreamState("idle"); };
  }, [loadArtifacts, loadRun, loading, run?.status, runId]);

  useEffect(() => {
    if (run && terminalStatuses.has(run.status)) loadArtifacts();
  }, [loadArtifacts, run?.status]);

  const selectedEvent = useMemo(() => events.find((item) => item.id === selectedId) || null, [events, selectedId]);
  const validationEvents = events.filter((item) => item.event.startsWith("validation_"));
  const modelCalls = numberAt(trajectory?.info as Record<string, unknown> | undefined, "model_stats", "api_calls");
  const modelCost = numberAt(trajectory?.info as Record<string, unknown> | undefined, "model_stats", "instance_cost");

  async function cancel() {
    if (!run || !window.confirm("?????????Worker ??????????")) return;
    setCancelling(true);
    try { setRun(await api.cancelRun(run.run_id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "??????"); }
    finally { setCancelling(false); }
  }

  if (loading) return <div className="page"><LoadingState label="????????" /></div>;
  if (!run) return <div className="page"><ErrorState message={error || "?????"} retry={loadInitial} /></div>;

  return <div className="page run-detail-page">
    <div className="breadcrumb"><Link to="/runs">????</Link><span>/</span><strong>{run.run_id}</strong></div>
    <header className="detail-header">
      <div className="detail-title"><div className="run-kicker"><StatusBadge status={run.status} pulse={run.status === "running"} />
        {run.status === "running" && <span className={`stream-indicator ${streamState}`}><i />
          {streamState === "connected" ? "????" : "????"}</span>}</div>
        <h1>{run.task}</h1><p><code>{run.run_id}</code><span>?</span>{run.project_path}</p></div>
      <div className="detail-actions"><button className="button button-secondary" onClick={() => loadInitial()}>? ??</button>
        {!terminalStatuses.has(run.status) && <button className="button button-danger" disabled={cancelling} onClick={cancel}>
          {cancelling ? "????" : "????"}</button>}</div>
    </header>

    {error && <div className="inline-alert" role="alert"><span>!</span><p>{error}</p><button onClick={() => setError("")}>?</button></div>}
    {run.error && <div className="inline-alert persistent" role="alert"><span>!</span><div><strong>{run.exit_status || "????"}</strong><p>{run.error}</p></div></div>}

    <section className="run-facts">
      <div><span>????</span><strong>{run.exit_status || (run.status === "running" ? "Agent ????" : "?? Worker")}</strong></div>
      <div><span>????</span><strong>{formatDuration(run.started_at, run.finished_at)}</strong></div>
      <div><span>????</span><strong>{modelCalls ?? "?"}</strong></div>
      <div><span>????</span><strong>{modelCost === null ? "?" : `$${modelCost.toFixed(4)}`}</strong></div>
      <div><span>????</span><strong>{events.length}</strong></div>
    </section>

    <nav className="detail-tabs" aria-label="????">
      {([ ["timeline", "?????", events.length], ["diff", "?? Diff", null],
        ["validation", "????", validationEvents.length], ["artifacts", "??", artifacts.length] ] as const)
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
  if (!events.length) return <EmptyState title="???????" detail="Worker ??????????????????????" />;
  return <div className="timeline-layout">
    <section className="timeline-panel panel"><div className="timeline-heading"><div><span className="eyebrow">Live Trace</span>
      <h2>Agent ???</h2></div><span>{events.length} events</span></div>
      <div className="timeline-list">{events.map((item, index) => <button key={item.id}
        className={`timeline-event tone-${eventTone(item.event)} ${selected?.id === item.id ? "selected" : ""}`}
        onClick={() => onSelect(item)}>
        <span className="timeline-rail"><i />{index < events.length - 1 && <b />}</span>
        <span className="event-body"><span className="event-meta"><strong>{eventTitle(item)}</strong>
          <time>{formatDate((item.data.ts as string) || item.created_at)}</time></span>
          <EventSummary event={item} /></span><span className="event-arrow">?</span>
      </button>)}</div>
    </section>
    <EventInspector event={selected} />
  </div>;
}

function EventSummary({ event }: { event: RunEvent }) {
  const data = event.data;
  if (event.event === "tool_start") return <code>{stringValue(data.command) || "bash"}</code>;
  if (event.event === "tool_end") return <span className="event-summary">??? {stringValue(data.returncode)} ? {stringValue(data.output).slice(0, 100) || "???"}</span>;
  if (event.event.startsWith("validation")) return <span className="event-summary">{stringValue(data.validator || data.status || "???")}</span>;
  if (event.event === "run_status_changed") return <span className="event-summary">{stringValue(data.status)}</span>;
  return <span className="event-summary">{stringValue(data.model || data.backend || data.exit_status || data.status || "?????")}</span>;
}

function EventInspector({ event }: { event: RunEvent | null }) {
  if (!event) return <aside className="inspector-panel panel inspector-empty"><div className="inspector-mark">?</div>
    <h3>???????</h3><p>???????????????????????</p></aside>;
  const data = event.data;
  const isTool = event.event.startsWith("tool_");
  const output = stringValue(data.output || data.stdout || data.exception_info);
  return <aside className="inspector-panel panel"><div className="inspector-header"><div><span className="eyebrow">Event Inspector</span>
    <h3>{eventTitle(event)}</h3></div><span className={`event-kind tone-${eventTone(event.event)}`}>{event.event}</span></div>
    <dl className="inspector-meta"><div><dt>?? ID</dt><dd>#{event.id}</dd></div><div><dt>????</dt><dd>{formatDate(event.created_at)}</dd></div>
      {data.returncode !== undefined && <div><dt>???</dt><dd className={Number(data.returncode) === 0 ? "text-success" : "text-danger"}>{stringValue(data.returncode)}</dd></div>}</dl>
    {isTool && data.command !== undefined && <div className="code-block"><div className="code-label"><span>COMMAND</span><button onClick={() => navigator.clipboard.writeText(stringValue(data.command))}>??</button></div>
      <pre><code>{stringValue(data.command)}</code></pre></div>}
    {output && <div className="code-block output-block"><div className="code-label"><span>OUTPUT</span><span>{output.length} chars</span></div><pre><code>{output}</code></pre></div>}
    {!isTool && <div className="code-block output-block"><div className="code-label"><span>EVENT PAYLOAD</span></div>
      <pre><code>{JSON.stringify(data, null, 2)}</code></pre></div>}
  </aside>;
}

function DiffPanel({ diff, running }: { diff: string | null; running: boolean }) {
  if (diff === null || diff.trim() === "") return <EmptyState title={running ? "Diff ????" : "??????"}
    detail={running ? "??????????? Git diff?" : "?????????? Git ???"} />;
  const lines = diff.split("\n");
  return <section className="panel diff-panel"><div className="diff-header"><div><span className="eyebrow">Workspace Patch</span>
    <h2>????</h2></div><span>{lines.filter((line) => line.startsWith("diff --git")).length} files</span></div>
    <div className="diff-code">{lines.map((line, index) => <div key={index} className={line.startsWith("+") && !line.startsWith("+++") ? "add" :
      line.startsWith("-") && !line.startsWith("---") ? "delete" : line.startsWith("@@") ? "hunk" : line.startsWith("diff") ? "file" : ""}>
      <span>{index + 1}</span><code>{line || " "}</code></div>)}</div></section>;
}

function ValidationPanel({ events, running }: { events: RunEvent[]; running: boolean }) {
  const completed = events.filter((item) => item.event === "validation_end");
  if (!events.length) return <EmptyState title={running ? "??????" : "??????????"}
    detail={running ? "Compile?EditMode ? PlayMode ????????????" : "?? Agent ????????????????????????"} />;
  return <section className="validation-grid">{events.map((item) => {
    const status = stringValue(item.data.status || (item.event === "validation_start" ? "running" : "unknown"));
    return <article className="panel validation-card" key={item.id}><div className={`validation-symbol ${status}`}>
      {status === "passed" ? "?" : status === "failed" ? "?" : "?"}</div><div><span className="eyebrow">{item.event}</span>
      <h3>{stringValue(item.data.validator || "Unity Validator")}</h3><p>{stringValue(item.data.message || item.data.exception || "???????")}</p></div>
      <span className={`validation-status ${status}`}>{status}</span></article>;
  })}<div className="validation-summary panel"><span>{completed.length}</span><p>??????</p></div></section>;
}

function ArtifactsPanel({ artifacts }: { artifacts: ArtifactInfo[] }) {
  if (!artifacts.length) return <EmptyState title="??????" detail="trajectory?result ? diff ?? Worker ?????????" />;
  return <section className="panel artifact-panel"><div className="artifact-heading"><span className="eyebrow">Run Files</span><h2>????</h2></div>
    <div className="artifact-list">{artifacts.map((item) => <a key={item.name} href={item.download_url} className="artifact-row">
      <span className="file-mark">{item.name.split(".").at(-1)?.toUpperCase()}</span><span><strong>{item.name}</strong>
        <small>{formatBytes(item.size)} ? {formatDate(item.created_at)}</small></span><span className="download-mark">?</span></a>)}</div></section>;
}
