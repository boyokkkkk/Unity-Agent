export type RunStatus = "pending" | "running" | "submitted" | "failed" | "cancelled" | "timed_out";

export interface RunRecord {
  run_id: string;
  task: string;
  status: RunStatus;
  config_path: string;
  project_path: string;
  artifact_dir: string;
  worker_pid: number | null;
  exit_status: string;
  submission: string;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunCreateInput {
  task: string;
  config_path: string;
  project_path?: string;
}

export interface RunEvent {
  id: number;
  event: string;
  created_at: string;
  data: Record<string, unknown>;
}

export interface ArtifactInfo {
  name: string;
  size: number;
  created_at: string;
  download_url: string;
}

export interface Trajectory {
  messages?: Array<Record<string, unknown>>;
  info?: Record<string, unknown>;
  [key: string]: unknown;
}

export const terminalStatuses = new Set<RunStatus>(["submitted", "failed", "cancelled", "timed_out"]);
