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
      setError("?????? Agent ??????");
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
      setError(reason instanceof Error ? reason.message : "??????");
    } finally {
      setSubmitting(false);
    }
  }

  return <div className="page new-run-page">
    <div className="breadcrumb"><Link to="/runs">????</Link><span>/</span><strong>????</strong></div>
    <header className="page-hero form-hero">
      <div><span className="eyebrow">New Experiment</span><h1>????<br /><em>???</em>???</h1>
        <p>?????? Worker ????????????????????</p></div>
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
          <span className="eyebrow">Task Brief</span><h2>????</h2>
          <p className="field-help">?????????????????????????????</p>
          <label className="field-label" htmlFor="task">?????? <span>??</span></label>
          <textarea id="task" maxLength={20000} value={task} onChange={(event) => setTask(event.target.value)} rows={8}
            placeholder="?????????????? UI ?????????????????????????? Unity ???" />
          <div className="field-footer"><span>Agent ?? Unity ??????? shell ??</span><span>{task.length} / 20000</span></div>
        </div>
      </section>

      <section className="panel form-section">
        <div className="form-index">02</div>
        <div className="form-section-body"><span className="eyebrow">Runtime</span><h2>????</h2>
          <div className="field-grid">
            <label><span className="field-label">????</span><input value={configPath}
              onChange={(event) => setConfigPath(event.target.value)} required /></label>
            <label><span className="field-label">Unity ???? <small>???????</small></span><input value={projectPath}
              onChange={(event) => setProjectPath(event.target.value)} placeholder="E:/Unity_project/Kitchen_Chaos" /></label>
          </div>
          <div className="safety-note"><span className="shield-mark">?</span><div><strong>????????</strong>
            <p>??? Unity ??????????????????</p></div></div>
        </div>
      </section>

      {error && <div className="form-error" role="alert"><strong>??????</strong><span>{error}</span></div>}
      <div className="form-actions"><Link className="button button-ghost" to="/runs">??</Link>
        <button className="button button-primary launch-button" disabled={submitting}>
          {submitting ? <><span className="loader small" />????</> : <>???? <span>?</span></>}
        </button></div>
    </form>
  </div>;
}
