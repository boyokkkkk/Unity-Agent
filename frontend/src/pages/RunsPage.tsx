import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "../router";
import { api } from "../api";
import { EmptyState, ErrorState, LoadingState, SectionHeader, StatusBadge } from "../components/ui";
import type { RunRecord, RunStatus } from "../types";
import { formatDate, formatDuration } from "../utils";

const filters: Array<{ value: "all" | RunStatus; label: string }> = [
  { value: "all", label: "??" }, { value: "running", label: "???" },
  { value: "submitted", label: "???" }, { value: "failed", label: "??" },
  { value: "cancelled", label: "???" },
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
      setError(reason instanceof Error ? reason.message : "????????");
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
      <div><span className="eyebrow">Experiment Registry</span><h1>????</h1>
        <p>??????????? Unity Agent ?????</p></div>
      <Link className="button button-primary" to="/runs/new"><span>?</span>????</Link>
    </header>

    <section className="metric-strip" aria-label="????">
      <div><span className="metric-value">{runs.length}</span><span className="metric-label">????</span></div>
      <div><span className="metric-value live-value">{runningCount}</span><span className="metric-label">????</span></div>
      <div><span className="metric-value success-value">{successCount}</span><span className="metric-label">????</span></div>
      <div><span className="metric-value danger-value">{failedCount}</span><span className="metric-label">????</span></div>
    </section>

    <section className="panel run-registry">
      <SectionHeader eyebrow="Runs" title="????" action={<button className="icon-button" onClick={() => load()} aria-label="??">?</button>} />
      <div className="toolbar">
        <label className="search-box"><span>?</span><input value={query} onChange={(event) => setQuery(event.target.value)}
          placeholder="????? Run ID" aria-label="????" /></label>
        <div className="filter-tabs" role="tablist">
          {filters.map((item) => <button key={item.value} className={filter === item.value ? "active" : ""}
            onClick={() => setFilter(item.value)}>{item.label}</button>)}
        </div>
      </div>

      {loading ? <LoadingState label="????????" /> : error ? <ErrorState message={error} retry={() => load()} /> :
        runs.length === 0 ? <EmptyState title="?????" detail="????? Unity ????????????????"
          action={<Link className="button button-primary" to="/runs/new">???????</Link>} /> :
        visibleRuns.length === 0 ? <EmptyState title="??????" detail="???????????????" /> :
        <div className="run-table-wrap"><table className="run-table">
          <thead><tr><th>??</th><th>??</th><th>Run ID</th><th>????</th><th>??</th><th /></tr></thead>
          <tbody>{visibleRuns.map((run) => <tr key={run.run_id}>
            <td><Link className="task-link" to={`/runs/${run.run_id}`}>{run.task}</Link>
              <span className="project-path">{run.project_path}</span></td>
            <td><StatusBadge status={run.status} pulse={run.status === "running"} /></td>
            <td><code>{run.run_id}</code></td><td>{formatDate(run.created_at)}</td>
            <td>{formatDuration(run.started_at, run.finished_at)}</td>
            <td><Link className="row-arrow" to={`/runs/${run.run_id}`} aria-label="????">?</Link></td>
          </tr>)}</tbody>
        </table></div>}
    </section>
  </div>;
}
