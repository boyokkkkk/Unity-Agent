import type { ArtifactInfo, RunCreateInput, RunEvent, RunRecord, Trajectory } from "./types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = `?????${response.status}?`;
    try {
      const body = await response.json() as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) {
        const messages = body.detail.map((item) => {
          if (item && typeof item === "object" && "msg" in item) return String(item.msg);
          return String(item);
        });
        if (messages.length) detail = messages.join("；");
      }
    } catch {
      // Non-JSON response keeps the status-based message.
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listRuns: () => request<RunRecord[]>("/api/runs"),
  getRun: (runId: string) => request<RunRecord>(`/api/runs/${runId}`),
  createRun: (input: RunCreateInput) => request<RunRecord>("/api/runs", {
    method: "POST",
    body: JSON.stringify({ ...input, project_path: input.project_path || null }),
  }),
  cancelRun: (runId: string) => request<RunRecord>(`/api/runs/${runId}/cancel`, { method: "POST" }),
  eventHistory: (runId: string, after = 0) => request<RunEvent[]>(
    `/api/runs/${runId}/events/history?after=${after}`,
  ),
  artifacts: (runId: string) => request<ArtifactInfo[]>(`/api/runs/${runId}/artifacts`),
  trajectory: (runId: string) => request<Trajectory>(`/api/runs/${runId}/trajectory`),
  async diff(runId: string): Promise<string | null> {
    const response = await fetch(`/api/runs/${runId}/diff`);
    if (response.status === 404) return null;
    if (!response.ok) throw new ApiError(`???? diff?${response.status}?`, response.status);
    return response.text();
  },
};
