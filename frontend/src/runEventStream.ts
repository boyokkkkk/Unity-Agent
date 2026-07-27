import type { RunEvent } from "./types";

export type StreamState = "connecting" | "connected" | "reconnecting" | "closed";

export interface RunEventSource {
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void;
  close(): void;
}

export type EventSourceFactory = (url: string) => RunEventSource;

export function mergeRunEvents(current: RunEvent[], incoming: RunEvent | RunEvent[]): RunEvent[] {
  const merged = new Map(current.map((event) => [event.id, event]));
  for (const event of Array.isArray(incoming) ? incoming : [incoming]) merged.set(event.id, event);
  return [...merged.values()].sort((left, right) => left.id - right.id);
}

export function parseRunEvent(raw: string): RunEvent {
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object") throw new Error("SSE event is not an object");
  const item = value as Record<string, unknown>;
  if (
    typeof item.id !== "number"
    || typeof item.event !== "string"
    || typeof item.created_at !== "string"
    || !item.data
    || typeof item.data !== "object"
    || Array.isArray(item.data)
  ) {
    throw new Error("SSE event envelope is invalid");
  }
  return item as unknown as RunEvent;
}

export function connectRunEventStream(options: {
  runId: string;
  after: number;
  onEvent: (event: RunEvent) => void;
  onState?: (state: StreamState) => void;
  onError?: (error: Error) => void;
  factory?: EventSourceFactory;
}): () => void {
  const factory = options.factory ?? ((url) => new EventSource(url));
  options.onState?.("connecting");
  const source = factory(`/api/runs/${encodeURIComponent(options.runId)}/events?after=${options.after}`);
  source.onopen = () => options.onState?.("connected");
  source.onerror = () => options.onState?.("reconnecting");
  source.addEventListener("run_event", (rawEvent) => {
    try {
      options.onEvent(parseRunEvent((rawEvent as MessageEvent<string>).data));
    } catch (reason) {
      options.onError?.(reason instanceof Error ? reason : new Error("Could not parse SSE event"));
    }
  });
  return () => {
    source.close();
    options.onState?.("closed");
  };
}
