import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { EmptyState, ErrorState, LoadingState, StatusBadge } from "../components/ui";
import { Link, useParams } from "../router";
import { connectRunEventStream, mergeRunEvents, type StreamState } from "../runEventStream";
import type { ArtifactInfo, RunEvent, RunRecord, Trajectory } from "../types";
import { terminalStatuses } from "../types";
import { eventTitle, formatBytes, formatDate, formatDuration, stringValue } from "../utils";

type DetailTab = "conversation" | "diff" | "validation" | "artifacts";
type StepKind = "thinking" | "skill" | "tool" | "validation" | "system";

function numberAt(source: Record<string, unknown> | undefined, ...path: string[]): number | null {
  let value: unknown = source;
  for (const key of path) {
    if (!value || typeof value !== "object") return null;
    value = (value as Record<string, unknown>)[key];
  }
  return typeof value === "number" ? value : null;
}

function stepKind(event: RunEvent): StepKind {
  if (event.event.startsWith("skill_")) return "skill";
  if (event.event.startsWith("tool_")) return "tool";
  if (event.event.startsWith("validation_")) return "validation";
  if (event.event.startsWith("model_")) return "thinking";
  return "system";
}

function stepIcon(kind: StepKind) {
  if (kind === "skill") return "sparkles" as const;
  if (kind === "tool") return "terminal" as const;
  if (kind === "validation") return "check" as const;
  if (kind === "thinking") return "activity" as const;
  return "clock" as const;
}

function stepSubtitle(event: RunEvent, kind: StepKind) {
  const data = event.data;
  if (kind === "skill") return stringValue(data.skill || data.name || data.command).slice(0, 140) || "已加载专业执行能力";
  if (kind === "tool") return stringValue(data.command || data.tool || data.output).slice(0, 140) || "工具执行事件";
  if (kind === "validation") return stringValue(data.validator || data.status || data.message) || "Unity 验证";
  if (kind === "thinking") return stringValue(data.model || data.backend || "分析上下文并决定下一步");
  return stringValue(data.status || data.exit_status || "Agent 运行状态变化");
}

function stepPayload(event: RunEvent) {
  const data = event.data;
  const parts = [
    data.command !== undefined ? `COMMAND\n${stringValue(data.command)}` : "",
    data.output !== undefined ? `OUTPUT\n${stringValue(data.output)}` : "",
    data.stdout !== undefined ? `STDOUT\n${stringValue(data.stdout)}` : "",
    data.exception_info !== undefined ? `ERROR\n${stringValue(data.exception_info)}` : "",
  ].filter(Boolean);
  return parts.join("\n\n") || JSON.stringify(data, null, 2);
}

function trajectoryAnswer(trajectory: Trajectory | null): string {
  const messages = trajectory?.messages;
  if (!Array.isArray(messages)) return "";
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (stringValue(message.role).toLowerCase() !== "assistant") continue;
    const content = message.content;
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      const text = content.map((part) => part && typeof part === "object" && "text" in part ? stringValue(part.text) : "").filter(Boolean).join("\n");
      if (text) return text;
    }
  }
  return "";
}

export function AgentRunDetailPage() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<RunRecord | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [trajectory, setTrajectory] = useState<Trajectory | null>(null);
  const [diff, setDiff] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>("conversation");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const [streamState, setStreamState] = useState<StreamState>("closed");

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [nextRun, history, items, nextDiff, nextTrajectory] = await Promise.all([
        api.getRun(runId), api.eventHistory(runId), api.artifacts(runId).catch(() => []),
        api.diff(runId).catch(() => null), api.trajectory(runId).catch(() => null),
      ]);
      setRun(nextRun); setEvents(history); setArtifacts(items); setDiff(nextDiff); setTrajectory(nextTrajectory); setError("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法加载任务对话"); }
    finally { if (!quiet) setLoading(false); }
  }, [runId]);

  const refreshOutcome = useCallback(async () => {
    try {
      const nextRun = await api.getRun(runId);
      setRun(nextRun);
      if (terminalStatuses.has(nextRun.status)) {
        const [history, items, nextDiff, nextTrajectory] = await Promise.all([
          api.eventHistory(runId), api.artifacts(runId).catch(() => []),
          api.diff(runId).catch(() => null), api.trajectory(runId).catch(() => null),
        ]);
        setEvents((current) => mergeRunEvents(current, history));
        setArtifacts(items);
        setDiff(nextDiff);
        setTrajectory(nextTrajectory);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法刷新任务状态");
    }
  }, [runId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!run || terminalStatuses.has(run.status)) return;
    const after = events.reduce((largest, event) => Math.max(largest, event.id), 0);
    const close = connectRunEventStream({
      runId,
      after,
      onEvent: (event) => {
        setEvents((current) => mergeRunEvents(current, event));
        if (
          event.event === "run_end"
          || event.event === "run_status_changed"
          || event.event === "run_cancelled"
          || event.event === "worker_start_failed"
        ) {
          void refreshOutcome();
        }
      },
      onState: setStreamState,
      onError: (reason) => setError(`实时事件格式错误：${reason.message}`),
    });
    const timer = window.setInterval(() => { void refreshOutcome(); }, 15000);
    return () => {
      window.clearInterval(timer);
      close();
    };
  }, [refreshOutcome, run?.status, runId]);

  const validationEvents = events.filter((item) => item.event.startsWith("validation_"));
  const modelCalls = numberAt(trajectory?.info as Record<string, unknown> | undefined, "model_stats", "api_calls");
  const modelCost = numberAt(trajectory?.info as Record<string, unknown> | undefined, "model_stats", "instance_cost");
  const answer = useMemo(() => run?.submission || trajectoryAnswer(trajectory), [run?.submission, trajectory]);

  async function cancel() {
    if (!run || !window.confirm("确认取消这个任务？Worker 进程及其子进程将被终止。")) return;
    setCancelling(true);
    try { setRun(await api.cancelRun(run.run_id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "取消任务失败"); }
    finally { setCancelling(false); }
  }

  if (loading) return <div className="page"><LoadingState label="正在加载 Agent 对话" /></div>;
  if (!run) return <div className="page"><ErrorState message={error || "任务不存在"} retry={() => load()} /></div>;

  return <div className="page run-detail-page">
    <div className="breadcrumb"><Link to="/workspace">项目工作台</Link><span>/</span><Link to="/runs">任务与对话</Link><span>/</span><strong>{run.run_id}</strong></div>
    <header className="detail-header agent-detail-header">
      <div className="detail-title"><div className="run-kicker"><StatusBadge status={run.status} pulse={run.status === "running"} />
        {run.status === "running" && <span className={`stream-indicator ${streamState === "connected" ? "connected" : ""}`}><i />{
          streamState === "connected" ? "实时同步" : streamState === "reconnecting" ? "正在重连" : "正在连接"
        }</span>}</div>
        <h1>{run.task}</h1><p><code>{run.run_id}</code><span>·</span>{run.project_path}</p></div>
      <div className="detail-actions"><button className="button button-secondary" onClick={() => load()}><Icon name="refresh" size={16} />刷新</button>
        {!terminalStatuses.has(run.status) && <button className="button button-danger" disabled={cancelling} onClick={cancel}>{cancelling ? "正在取消" : "取消任务"}</button>}</div>
    </header>

    {error && <div className="inline-alert" role="alert"><span>!</span><p>{error}</p><button aria-label="关闭提示" onClick={() => setError("")}>×</button></div>}
    {run.error && <div className="inline-alert persistent" role="alert"><span>!</span><div><strong>{run.exit_status || "运行异常"}</strong><p>{run.error}</p></div></div>}

    <section className="run-facts">
      <div><span>执行状态</span><strong>{run.exit_status || (run.status === "running" ? "Agent 运行中" : run.status)}</strong></div>
      <div><span>运行耗时</span><strong>{formatDuration(run.started_at, run.finished_at)}</strong></div>
      <div><span>模型调用</span><strong>{modelCalls ?? "—"}</strong></div>
      <div><span>模型成本</span><strong>{modelCost === null ? "—" : `$${modelCost.toFixed(4)}`}</strong></div>
      <div><span>执行步骤</span><strong>{events.length}</strong></div>
    </section>

    <nav className="detail-tabs" aria-label="任务内容">
      {([ ["conversation", "Agent 对话", events.length], ["diff", "Code Diff", diff ? diff.split("\n").filter((line) => line.startsWith("diff --git")).length : 0],
        ["validation", "验证", validationEvents.length], ["artifacts", "产出", artifacts.length] ] as const)
        .map(([value, label, count]) => <button key={value} className={activeTab === value ? "active" : ""} onClick={() => setActiveTab(value)}>{label}<span>{count}</span></button>)}
    </nav>

    {activeTab === "conversation" && <Conversation run={run} events={events} answer={answer} onOpenTab={setActiveTab} artifactCount={artifacts.length} hasDiff={Boolean(diff)} />}
    {activeTab === "diff" && <DiffPanel diff={diff} running={!terminalStatuses.has(run.status)} />}
    {activeTab === "validation" && <ValidationPanel events={validationEvents} running={!terminalStatuses.has(run.status)} />}
    {activeTab === "artifacts" && <ArtifactsPanel artifacts={artifacts} />}
  </div>;
}

function Conversation({ run, events, answer, onOpenTab, artifactCount, hasDiff }: {
  run: RunRecord; events: RunEvent[]; answer: string; onOpenTab: (tab: DetailTab) => void; artifactCount: number; hasDiff: boolean;
}) {
  return <section className="conversation-shell" aria-label="Agent 对话过程">
    <article className="conversation-intro panel"><div className="conversation-avatar"><Icon name="messages" size={18} /></div><div><span>你的任务</span><p>{run.task}</p></div></article>
    <div className="agent-response">
      {events.length ? events.map((event) => {
        const kind = stepKind(event);
        return <details className={`agent-step ${kind}`} key={event.id} open={event.event === "worker_start_failed"}>
          <summary><span className="step-icon"><Icon name={stepIcon(kind)} size={16} /></span><span className="step-copy"><strong>{kind === "thinking" ? `思考 · ${eventTitle(event)}` : kind === "skill" ? `Skill · ${eventTitle(event)}` : eventTitle(event)}</strong><small>{stepSubtitle(event, kind)}</small></span><time className="step-time">{formatDate((event.data.ts as string) || event.created_at)}</time></summary>
          <div className="step-details"><pre><code>{stepPayload(event)}</code></pre></div>
        </details>;
      }) : <div className="conversation-empty panel">Agent 启动后，思考、Skill 与工具执行过程会实时显示在这里。</div>}
      <article className="answer-card panel"><span>Final answer</span><h2>{run.status === "running" || run.status === "pending" ? "Agent 正在形成答案" : "执行结果"}</h2>
        <p>{answer || (run.status === "running" || run.status === "pending" ? "任务仍在执行中。你可以展开上方步骤查看当前思考、Skill 和工具调用。" : run.error || "本次运行没有返回文本答案，请查看验证与产出。")}</p>
        <div className="answer-meta">{hasDiff && <button onClick={() => onOpenTab("diff")}><Icon name="git" size={15} />查看 Code Diff</button>}
          {artifactCount > 0 && <button onClick={() => onOpenTab("artifacts")}><Icon name="box" size={15} />查看 {artifactCount} 个产出</button>}
          <button onClick={() => onOpenTab("validation")}><Icon name="check" size={15} />查看验证结果</button></div>
      </article>
    </div>
  </section>;
}

function DiffPanel({ diff, running }: { diff: string | null; running: boolean }) {
  if (!diff?.trim()) return <EmptyState title={running ? "Diff 尚未生成" : "没有代码变更"} detail={running ? "Agent 修改工程后，Code Diff 会自动更新。" : "本次运行没有检测到 Git 变更。"} />;
  const lines = diff.split("\n");
  return <section className="panel diff-panel"><div className="diff-header"><div><span className="eyebrow">Workspace patch</span><h2>代码变更</h2></div><span>{lines.filter((line) => line.startsWith("diff --git")).length} 个文件</span></div>
    <div className="diff-code">{lines.map((line, index) => <div key={index} className={line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "delete" : line.startsWith("@@") ? "hunk" : line.startsWith("diff") ? "file" : ""}><span>{index + 1}</span><code>{line || " "}</code></div>)}</div></section>;
}

function ValidationPanel({ events, running }: { events: RunEvent[]; running: boolean }) {
  if (!events.length) return <EmptyState title={running ? "等待验证结果" : "没有结构化验证记录"} detail={running ? "Compile、EditMode 与 PlayMode 结果会显示在这里。" : "本次运行没有产生结构化验证事件。"} />;
  return <section className="validation-grid">{events.map((item) => { const status = stringValue(item.data.status || (item.event === "validation_start" ? "running" : "unknown")); return <article className="panel validation-card" key={item.id}><div className={`validation-symbol ${status}`}><Icon name={status === "passed" ? "check" : "activity"} /></div><div><span className="eyebrow">{item.event}</span><h3>{stringValue(item.data.validator || "Unity Validator")}</h3><p>{stringValue(item.data.message || item.data.exception || "没有附加信息")}</p></div><span className={`validation-status ${status}`}>{status}</span></article>; })}</section>;
}

function ArtifactsPanel({ artifacts }: { artifacts: ArtifactInfo[] }) {
  if (!artifacts.length) return <EmptyState title="还没有任务产出" detail="代码补丁、trajectory、结果和日志会在 Worker 运行后生成。" />;
  return <section className="panel artifact-panel"><div className="artifact-heading"><span className="eyebrow">Deliverables</span><h2>任务产出</h2></div><div className="artifact-list">{artifacts.map((item) => <a key={item.name} href={item.download_url} className="artifact-row"><span className="file-mark">{item.name.split(".").at(-1)?.toUpperCase()}</span><span><strong>{item.name}</strong><small>{formatBytes(item.size)} · {formatDate(item.created_at)}</small></span><span className="download-mark">↓</span></a>)}</div></section>;
}
