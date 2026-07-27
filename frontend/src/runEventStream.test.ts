import { describe, expect, it } from "vitest";
import {
  connectRunEventStream,
  mergeRunEvents,
  parseRunEvent,
  type RunEventSource,
  type StreamState,
} from "./runEventStream";
import type { RunEvent } from "./types";

function event(id: number, name = "tool_end"): RunEvent {
  return { id, event: name, created_at: "2026-07-27T00:00:00Z", data: { id } };
}

class FakeEventSource implements RunEventSource {
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  listeners = new Map<string, EventListenerOrEventListenerObject>();
  closed = false;

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    this.listeners.set(type, listener);
  }

  emit(type: string, data: string) {
    const listener = this.listeners.get(type);
    const message = { data } as MessageEvent<string>;
    if (typeof listener === "function") listener(message);
    else listener?.handleEvent(message);
  }

  close() {
    this.closed = true;
  }
}

describe("run event stream", () => {
  it("merges history and live events by ID without duplicates", () => {
    expect(mergeRunEvents([event(2), event(1)], [event(2, "updated"), event(3)]))
      .toEqual([event(1), event(2, "updated"), event(3)]);
  });

  it("parses only stable run_event envelopes", () => {
    expect(parseRunEvent(JSON.stringify(event(4)))).toEqual(event(4));
    expect(() => parseRunEvent('{"event":"tool_end"}')).toThrow("invalid");
  });

  it("uses the history cursor, reports states, forwards events, and closes", () => {
    const source = new FakeEventSource();
    const states: StreamState[] = [];
    const received: RunEvent[] = [];
    let requestedUrl = "";
    const close = connectRunEventStream({
      runId: "run/id",
      after: 42,
      onEvent: (item) => received.push(item),
      onState: (state) => states.push(state),
      factory: (url) => {
        requestedUrl = url;
        return source;
      },
    });

    source.onopen?.(new Event("open"));
    source.emit("run_event", JSON.stringify(event(43, "run_status_changed")));
    source.onerror?.(new Event("error"));
    close();

    expect(requestedUrl).toBe("/api/runs/run%2Fid/events?after=42");
    expect(received).toEqual([event(43, "run_status_changed")]);
    expect(states).toEqual(["connecting", "connected", "reconnecting", "closed"]);
    expect(source.closed).toBe(true);
  });
});
