import { describe, expect, it, vi } from "vitest";

import { ACCESS_TOKEN_STORAGE_KEY } from "../auth/token";
import { AUTH_UNAUTHORIZED_EVENT, ApiError } from "./client";
import { consumeSseStream } from "./sse";
import { startWorkflowStream } from "./workflows";

function chunkedStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

describe("SSE parser", () => {
  it("reassembles an event split across chunks", async () => {
    const events: unknown[] = [];

    await consumeSseStream(
      chunkedStream([
        "event: progr",
        "ess\ndata: {\"node\":\"plan_topics\"}\n\n",
      ]),
      (event) => events.push(event),
    );

    expect(events).toEqual([
      {
        event: "progress",
        data: '{"node":"plan_topics"}',
      },
    ]);
  });

  it("parses multiple events from one chunk", async () => {
    const events: unknown[] = [];

    await consumeSseStream(
      chunkedStream([
        "event: meta\ndata: {\"thread_id\":\"t1\"}\n\n" +
          "event: progress\ndata: {\"node\":\"write_draft\"}\n\n",
      ]),
      (event) => events.push(event),
    );

    expect(events).toHaveLength(2);
    expect(events).toEqual([
      { event: "meta", data: '{"thread_id":"t1"}' },
      { event: "progress", data: '{"node":"write_draft"}' },
    ]);
  });

  it("supports CRLF framing", async () => {
    const events: unknown[] = [];

    await consumeSseStream(
      chunkedStream([
        "event: progress\r\ndata: first\r\ndata: second\r\n\r\n",
      ]),
      (event) => events.push(event),
    );

    expect(events).toEqual([
      { event: "progress", data: "first\nsecond" },
    ]);
  });
});

describe("workflow streaming API", () => {
  it("uses POST with the stored Bearer token and parses events", async () => {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "stream-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        chunkedStream([
          "event: meta\ndata: {\"thread_id\":\"t1\",\"action\":\"start\"}\n\n",
        ]),
        { headers: { "Content-Type": "text/event-stream; charset=utf-8" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onEvent = vi.fn();

    await startWorkflowStream("LangGraph SSE", {
      signal: new AbortController().signal,
      onEvent,
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer stream-token",
    );
    expect(onEvent).toHaveBeenCalledWith({
      type: "meta",
      data: { thread_id: "t1", action: "start" },
    });
    vi.unstubAllGlobals();
  });

  it("keeps the centralized 401 logout behavior", async () => {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "expired-stream-token");
    const listener = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, listener);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "expired" }), { status: 401 }),
      ),
    );

    await expect(
      startWorkflowStream("SSE 401", {
        signal: new AbortController().signal,
        onEvent: vi.fn(),
      }),
    ).rejects.toEqual(new ApiError(401, "expired"));
    expect(listener).toHaveBeenCalledOnce();

    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, listener);
    vi.unstubAllGlobals();
  });
});
