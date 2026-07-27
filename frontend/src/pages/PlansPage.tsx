import { useEffect, useState } from "react";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { StatusBadge } from "../components/ui";
import { Link } from "../router";
import type { RunRecord } from "../types";
import { formatDate } from "../utils";

const stages = [
  { title: "待执行", statuses: ["pending"], detail: "已进入 Worker 队列" },
  { title: "执行中", statuses: ["running"], detail: "Agent 正在调用模型与工具" },
  { title: "已交付", statuses: ["submitted"], detail: "代码与验证产物已生成" },
  { title: "需关注", statuses: ["failed", "cancelled", "timed_out"], detail: "需要检查或重新规划" },
] as const;

export function PlansPage() {
  const [runs, setRuns] = useState<RunRecord[]>([]);
  useEffect(() => { api.listRuns().then(setRuns).catch(() => undefined); }, []);
  return <div className="page plans-page">
    <header className="page-hero compact-hero"><div><span className="eyebrow">Execution Plans</span><h1>任务执行计划</h1>
      <p>用看板观察项目任务从排队、执行到 Unity 验证与交付的完整流转。</p></div>
      <Link className="button button-primary" to="/runs/new"><Icon name="plus" size={16} />创建任务</Link></header>
    <section className="plan-board">{stages.map((stage, index) => {
      const items = runs.filter((run) => (stage.statuses as readonly string[]).includes(run.status));
      return <div className="plan-column" key={stage.title}><div className="plan-column-head"><span className={`plan-number tone-${index}`}>0{index + 1}</span>
        <div><h2>{stage.title}<b>{items.length}</b></h2><p>{stage.detail}</p></div></div>
        <div className="plan-column-body">{items.map((run) => <Link className="plan-card panel" to={`/runs/${run.run_id}`} key={run.run_id}>
          <StatusBadge status={run.status} pulse={run.status === "running"} /><h3>{run.task}</h3><p>{run.project_path || "未指定工程"}</p>
          <div><span>{formatDate(run.created_at)}</span><Icon name="arrow" size={15} /></div></Link>)}
          {!items.length && <div className="plan-empty"><Icon name="box" /><span>当前没有任务</span></div>}</div></div>;
    })}</section>
  </div>;
}
