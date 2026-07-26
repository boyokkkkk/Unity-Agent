import type { RunEvent, RunStatus } from "./types";

export const statusMeta: Record<RunStatus, { label: string; tone: string }> = {
  pending: { label: "???", tone: "muted" },
  running: { label: "???", tone: "live" },
  submitted: { label: "???", tone: "success" },
  failed: { label: "??", tone: "danger" },
  cancelled: { label: "???", tone: "warning" },
  timed_out: { label: "???", tone: "warning" },
};

export function formatDate(value: string | null): string {
  if (!value) return "?";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date(value));
}

export function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "?";
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
    run_created: "?????", worker_started: "Worker ???", run_start: "Agent ????",
    model_start: "????", model_end: "????", tool_start: "????",
    tool_end: "????", validation_start: "????", validation_end: "????",
    run_end: "Agent ????", run_status_changed: "?????", run_cancelled: "?????",
    artifact_created: "????", worker_start_failed: "Worker ????",
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
