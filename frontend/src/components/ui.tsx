import type { ReactNode } from "react";
import type { RunStatus } from "../types";
import { statusMeta } from "../utils";

export function StatusBadge({ status, pulse = false }: { status: RunStatus; pulse?: boolean }) {
  const meta = statusMeta[status];
  return <span className={`status-badge status-${meta.tone} ${pulse ? "is-pulsing" : ""}`}>
    <span className="status-dot" />{meta.label}
  </span>;
}

export function LoadingState({ label = "加载中" }: { label?: string }) {
  return <div className="state-card state-loading" role="status">
    <span className="loader" /><p>{label}</p>
  </div>;
}

export function EmptyState({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return <div className="state-card state-empty">
    <div className="empty-orbit"><span /></div>
    <h3>{title}</h3><p>{detail}</p>{action}
  </div>;
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="state-card state-error" role="alert">
    <div className="error-glyph">!</div>
    <h3>请求失败</h3><p>{message}</p>
    {retry && <button className="button button-secondary" onClick={retry}>重新加载</button>}
  </div>;
}

export function SectionHeader({ eyebrow, title, action }: {
  eyebrow?: string; title: string; action?: ReactNode;
}) {
  return <div className="section-header">
    <div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2></div>{action}
  </div>;
}
