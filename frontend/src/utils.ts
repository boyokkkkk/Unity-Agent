import type { RunEvent, RunStatus } from "./types";

export const statusMeta: Record<RunStatus, { label: string; tone: string }> = {
  pending: { label: "等待中", tone: "muted" },
  running: { label: "运行中", tone: "live" },
  submitted: { label: "已提交", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "warning" },
  timed_out: { label: "已超时", tone: "warning" },
};

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date(value));
}

export function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const milliseconds = Math.max(0, new Date(end || Date.now()).getTime() - new Date(start).getTime());
  const seconds = Math.floor(milliseconds / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function eventTitle(event: RunEvent): string {
  const labels: Record<string, string> = {
    run_created: "任务已创建", worker_started: "Worker 已启动", run_start: "Agent 开始运行",
    model_start: "模型调用开始", model_end: "模型调用结束", tool_start: "工具调用开始",
    tool_end: "工具调用结束", validation_start: "验证开始", validation_end: "验证结束",
    run_end: "Agent 运行结束", run_status_changed: "运行状态更新", run_cancelled: "任务已取消",
    artifact_created: "产物已生成", worker_start_failed: "Worker 启动失败",
  };
  return labels[event.event] || event.event.replaceAll("_", " ");
}

export function eventTone(event: string): string {
  if (event.includes("failed") || event === "run_cancelled") return "danger";
  if (event.startsWith("validation")) return "validation";
  if (event.startsWith("tool")) return "tool";
  if (event.startsWith("model")) return "model";
  if (event === "run_end" || event === "run_status_changed") return "success";
  return "default";
}

export function stringValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  return JSON.stringify(value, null, 2);
}
