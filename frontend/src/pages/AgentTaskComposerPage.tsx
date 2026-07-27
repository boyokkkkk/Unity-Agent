import { useEffect, useMemo, useState, type FormEvent, type KeyboardEvent } from "react";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { Link, useNavigate } from "../router";
import type { RunRecord } from "../types";

const prompts = [
  "分析当前 Unity 项目，并给出下一步开发计划",
  "检查最近的代码变更，修复潜在编译错误",
  "为当前功能补充 EditMode 与 PlayMode 测试",
];

function projectName(path: string) {
  return path.replaceAll("\\", "/").split("/").filter(Boolean).at(-1) || path;
}

export function AgentTaskComposerPage() {
  const navigate = useNavigate();
  const [task, setTask] = useState("");
  const [configPath, setConfigPath] = useState("configs/kitchen_chaos.json");
  const [projectPath, setProjectPath] = useState("");
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { api.listRuns().then(setRuns).catch(() => undefined); }, []);
  const projects = useMemo(() => [...new Set(runs.map((run) => run.project_path).filter(Boolean))].slice(0, 6), [runs]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!task.trim()) { setError("请先描述希望 Agent 完成的任务"); return; }
    setSubmitting(true); setError("");
    try {
      const run = await api.createRun({ task: task.trim(), config_path: configPath.trim(), project_path: projectPath.trim() || undefined });
      navigate(`/runs/${run.run_id}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "创建任务失败"); }
    finally { setSubmitting(false); }
  }

  function shortcut(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); }
  }

  return <div className="page task-composer-page">
    <div className="breadcrumb"><Link to="/workspace">项目工作台</Link><span>/</span><strong>新建任务</strong></div>
    <section className="composer-hero">
      <span className="composer-agent-mark"><Icon name="sparkles" size={22} /></span>
      <span className="eyebrow">Unity Agent conversation</span>
      <h1>今天要在 Unity 项目中完成什么？</h1>
      <p>像与开发搭档对话一样描述目标。Agent 会规划、调用 Skill、修改工程并汇报验证结果。</p>
    </section>

    <form className="composer-form" onSubmit={submit}>
      <section className="composer-box panel">
        <label className="sr-only" htmlFor="agent-task">任务描述</label>
        <textarea id="agent-task" autoFocus maxLength={20000} rows={6} value={task} onChange={(event) => setTask(event.target.value)}
          onKeyDown={shortcut} placeholder="例如：检查玩家移动系统的代码，修复冲刺状态偶尔无法退出的问题，并运行相关 Unity 测试。" />
        <div className="composer-toolbar">
          <div className="composer-context">
            <span><Icon name="folder" size={15} />{projectPath ? projectName(projectPath) : "选择项目"}</span>
            <span><Icon name="sparkles" size={15} />自动选择 Skill</span>
          </div>
          <button className="composer-send" disabled={submitting || !task.trim()} aria-label="发送任务">
            {submitting ? <span className="loader small" /> : <Icon name="arrow" size={18} />}
          </button>
        </div>
      </section>
      <div className="composer-hint"><span>Ctrl / ⌘ + Enter 发送</span><span>{task.length} / 20000</span></div>

      <details className="runtime-disclosure panel">
        <summary><span><Icon name="terminal" size={17} />运行设置</span><small>项目路径、Agent 配置</small><Icon name="chevron" size={16} /></summary>
        <div className="runtime-fields">
          <label><span>Unity 工程路径</span><input list="known-projects" value={projectPath} onChange={(event) => setProjectPath(event.target.value)} placeholder="D:/Projects/MyUnityGame" /></label>
          <datalist id="known-projects">{projects.map((path) => <option value={path} key={path}>{projectName(path)}</option>)}</datalist>
          <label><span>Agent 配置</span><input value={configPath} onChange={(event) => setConfigPath(event.target.value)} required /></label>
        </div>
        {projects.length > 0 && <div className="known-projects"><span>最近项目</span>{projects.map((path) => <button type="button" key={path} onClick={() => setProjectPath(path)}>{projectName(path)}</button>)}</div>}
      </details>

      {error && <div className="composer-error" role="alert"><strong>暂时无法发送任务</strong><span>{error}</span></div>}
    </form>

    <section className="prompt-suggestions" aria-label="任务示例">
      <span>试试这样问</span><div>{prompts.map((prompt) => <button type="button" key={prompt} onClick={() => setTask(prompt)}>{prompt}<Icon name="arrow" size={14} /></button>)}</div>
    </section>
    <p className="composer-safety"><Icon name="check" size={14} />同一 Unity 工程同一时间仅允许一个写任务，所有代码变更均可在 Diff 中检查。</p>
  </div>;
}
