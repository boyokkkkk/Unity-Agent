import { Link, Navigate, useLocation } from "./router";
import { Layout } from "./components/Layout";
import { NewRunPage } from "./pages/NewRunPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";

export default function App() {
  const { pathname } = useLocation();
  let content;
  if (pathname === "/" || pathname === "") content = <Navigate to="/runs" replace />;
  else if (pathname === "/runs") content = <RunsPage />;
  else if (pathname === "/runs/new") content = <NewRunPage />;
  else if (/^\/runs\/[^/]+$/.test(pathname)) content = <RunDetailPage />;
  else content = <div className="page"><div className="state-card state-empty">
    <span className="error-code">404</span><h2>页面不存在</h2><p>这个实验入口可能已经移动。</p>
    <Link className="button button-primary" to="/runs">返回实验列表</Link>
  </div></div>;
  return <Layout>{content}</Layout>;
}
