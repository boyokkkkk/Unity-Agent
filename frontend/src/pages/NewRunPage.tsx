import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "../router";
import { api } from "../api";

export function NewRunPage() {
  const navigate = useNavigate();
  const [task, setTask] = useState("");
  const [configPath, setConfigPath] = useState("configs/kitchen_chaos.json");
  const [projectPath, setProjectPath] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!task.trim()) {
      setError("请输入要交给 Agent 的任务描述");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const run = await api.createRun({
        task: task.trim(), config_path: configPath.trim(), project_path: projectPath.trim() || undefined,
      });
      navigate(`/runs/${run.run_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建任务失败");
    } finally {
      setSubmitting(false);
    }
  }

  return <div className="page new-run-page">
    <div className="breadcrumb"><Link to="/runs">实验列表</Link><span>/</span><strong>新建实验</strong></div>
    <header className="page-hero form-hero">
      <div><span className="eyebrow">New Experiment</span><h1>启动一场<br /><em>Unity</em> Agent 实验</h1>
        <p>创建独立 Worker，实时观察推理、工具调用与验证过程。</p></div>
      <div className="hero-diagram" aria-hidden="true">
        <div className="diagram-ring ring-one" /><div className="diagram-ring ring-two" />
        <span className="diagram-core">Agent</span><span className="diagram-node node-a">Model</span>
        <span className="diagram-node node-b">Unity</span><span className="diagram-node node-c">Verify</span>
      </div>
    </header>

    <form className="run-form" onSubmit={submit}>
      <section className="panel form-section primary-form-section">
        <div className="form-index">01</div>
        <div className="form-section-body">
          <span className="eyebrow">Task Brief</span><h2>任务说明</h2>
          <p className="field-help">清晰描述要检查或修复的问题，以及期望完成的验证。</p>
          <label className="field-label" htmlFor="task">任务描述 <span>必填</span></label>
          <textarea id="task" maxLength={20000} value={task} onChange={(event) => setTask(event.target.value)} rows={8}
            placeholder="例如：修复订单完成后 UI 没有刷新的问题，并运行相关 Unity 测试。" />
          <div className="field-footer"><span>Agent 将在 Unity 工程中执行受控的 shell 命令</span><span>{task.length} / 20000</span></div>
        </div>
      </section>

      <section className="panel form-section">
        <div className="form-index">02</div>
        <div className="form-section-body"><span className="eyebrow">Runtime</span><h2>运行环境</h2>
          <div className="field-grid">
            <label><span className="field-label">配置文件</span><input value={configPath}
              onChange={(event) => setConfigPath(event.target.value)} required /></label>
            <label><span className="field-label">Unity 工程路径 <small>留空则使用配置值</small></span><input value={projectPath}
              onChange={(event) => setProjectPath(event.target.value)} placeholder="E:/Unity_project/Kitchen_Chaos" /></label>
          </div>
          <div className="safety-note"><span className="shield-mark">✓</span><div><strong>本地安全模式</strong>
            <p>同一 Unity 工程同一时间仅允许一个写任务。</p></div></div>
        </div>
      </section>

      {error && <div className="form-error" role="alert"><strong>无法创建实验</strong><span>{error}</span></div>}
      <div className="form-actions"><Link className="button button-ghost" to="/runs">取消</Link>
        <button className="button button-primary launch-button" disabled={submitting}>
          {submitting ? <><span className="loader small" />正在启动</> : <>启动实验 <span>→</span></>}
        </button></div>
    </form>
  </div>;
}
