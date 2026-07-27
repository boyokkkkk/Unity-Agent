import { Link, Navigate, useLocation } from "./router";
import { WorkspaceLayout as Layout } from "./components/WorkspaceLayout";
import { AgentTaskComposerPage } from "./pages/AgentTaskComposerPage";
import { AgentRunDetailPage } from "./pages/AgentRunDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspacePage";
import { PlansPage } from "./pages/PlansPage";
import { SkillsPage } from "./pages/SkillsPage";

export default function App() {
  const { pathname } = useLocation();
  let content;
  if (pathname === "/" || pathname === "") content = <Navigate to="/workspace" replace />;
  else if (pathname === "/workspace") content = <ProjectWorkspacePage />;
  else if (pathname === "/runs") content = <RunsPage />;
  else if (pathname === "/runs/new") content = <AgentTaskComposerPage />;
  else if (pathname === "/plans") content = <PlansPage />;
  else if (pathname === "/skills") content = <SkillsPage />;
  else if (/^\/runs\/[^/]+$/.test(pathname)) content = <AgentRunDetailPage />;
  else content = <div className="page"><div className="state-card state-empty">
    <span className="error-code">404</span><h2>页面不存在</h2><p>这个实验入口可能已经移动。</p>
    <Link className="button button-primary" to="/runs">返回实验列表</Link>
  </div></div>;
  return <Layout>{content}</Layout>;
}
