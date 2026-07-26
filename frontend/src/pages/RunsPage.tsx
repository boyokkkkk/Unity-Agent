import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "../router";
import { api } from "../api";
import { EmptyState, ErrorState, LoadingState, SectionHeader, StatusBadge } from "../components/ui";
import type { RunRecord, RunStatus } from "../types";
import { formatDate, formatDuration } from "../utils";

const filters: Array<{ value: "all" | RunStatus; label: string }> = [
  { value: "all", label: "全部" }, { value: "running", label: "运行中" },
  { value: "submitted", label: "已提交" }, { value: "failed", label: "失败" },
  { value: "cancelled", label: "已取消" },
];

export function RunsPage() {
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | RunStatus>("all");
  const [query, setQuery] = useState("");

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      setRuns(await api.listRuns());
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载实验列表");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => load(true), 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const visibleRuns = useMemo(() => runs.filter((run) => {
    const matchesStatus = filter === "all" || run.status === filter;
    const needle = query.trim().toLowerCase();
    return matchesStatus && (!needle || run.task.toLowerCase().includes(needle) || run.run_id.includes(needle));
  }), [filter, query, runs]);

  const runningCount = runs.filter((run) => run.status === "running" || run.status === "pending").length;
  const successCount = runs.filter((run) => run.status === "submitted").length;
  const failedCount = runs.filter((run) => run.status === "failed" || run.status === "timed_out").length;

  return <div className="page runs-page">
    <header className="page-hero compact-hero">
      <div><span className="eyebrow">Experiment Registry</span><h1>实验运行记录</h1>
        <p>集中查看每一次 Unity Agent 实验的状态、耗时与产物。</p></div>
      <Link className="button button-primary" to="/runs/new"><span>＋</span>新建实验</Link>
    </header>

    <section className="metric-strip" aria-label="实验概览">
      <div><span className="metric-value">{runs.length}</span><span className="metric-label">实验总数</span></div>
      <div><span className="metric-value live-value">{runningCount}</span><span className="metric-label">正在运行</span></div>
      <div><span className="metric-value success-value">{successCount}</span><span className="metric-label">成功提交</span></div>
      <div><span className="metric-value danger-value">{failedCount}</span><span className="metric-label">失败或超时</span></div>
    </section>

    <section className="panel run-registry">
      <SectionHeader eyebrow="Runs" title="实验列表" action={<button className="icon-button" onClick={() => load()} aria-label="刷新">↻</button>} />
      <div className="toolbar">
        <label className="search-box"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索任务或 Run ID" aria-label="搜索实验" /></label>
        <div className="filter-tabs" role="tablist">
          {filters.map((item) => <button key={item.value} className={filter === item.value ? "active" : ""}
            onClick={() => setFilter(item.value)}>{item.label}</button>)}
        </div>
      </div>

      {loading ? <LoadingState label="正在加载实验记录" /> : error ? <ErrorState message={error} retry={() => load()} /> :
        runs.length === 0 ? <EmptyState title="还没有实验" detail="创建第一个 Unity Agent 任务后，运行记录会显示在这里。"
          action={<Link className="button button-primary" to="/runs/new">创建第一个实验</Link>} /> :
        visibleRuns.length === 0 ? <EmptyState title="没有匹配的实验" detail="请调整状态筛选或搜索关键词。" /> :
        <div className="run-table-wrap"><table className="run-table">
          <thead><tr><th>任务</th><th>状态</th><th>Run ID</th><th>创建时间</th><th>耗时</th><th /></tr></thead>
          <tbody>{visibleRuns.map((run) => <tr key={run.run_id}>
            <td><Link className="task-link" to={`/runs/${run.run_id}`}>{run.task}</Link>
              <span className="project-path">{run.project_path}</span></td>
            <td><StatusBadge status={run.status} pulse={run.status === "running"} /></td>
            <td><code>{run.run_id}</code></td><td>{formatDate(run.created_at)}</td>
            <td>{formatDuration(run.started_at, run.finished_at)}</td>
            <td><Link className="row-arrow" to={`/runs/${run.run_id}`} aria-label="查看详情">→</Link></td>
          </tr>)}</tbody>
        </table></div>}
    </section>
  </div>;
}
