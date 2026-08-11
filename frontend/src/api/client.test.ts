import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ACCESS_TOKEN_STORAGE_KEY } from "../auth/token";
import {
  API_BASE_URL,
  apiRequest,
  ApiError,
  AUTH_UNAUTHORIZED_EVENT,
  normalizeApiBaseUrl,
} from "./client";


describe("API base URL", () => {
  it("adds the API prefix to the local development origin", () => {
    expect(normalizeApiBaseUrl("http://127.0.0.1:8000")).toBe(
      "http://127.0.0.1:8000/api/v1",
    );
  });

  it("keeps the production relative API prefix without duplicating it", () => {
    expect(normalizeApiBaseUrl("/api/v1/")).toBe("/api/v1");
  });
});


describe("API client authentication", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("adds the stored Bearer token to an authenticated request", async () => {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "header-test-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest<{ ok: boolean }>("/projects");

    expect(fetchMock.mock.calls[0][0]).toBe(`${API_BASE_URL}/projects`);
    const requestInit = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(requestInit.headers).get("Authorization")).toBe(
      "Bearer header-test-token",
    );
  });

  it("does not send Authorization for a public auth request", async () => {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "stored-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "user-id" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/auth/register", {}, { authenticated: false });

    const requestInit = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(requestInit.headers).has("Authorization")).toBe(false);
  });

  it("emits the unauthorized event for an authenticated 401", async () => {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "expired-token");
    const listener = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, listener);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "expired" }), { status: 401 }),
      ),
    );

    await expect(apiRequest("/projects")).rejects.toEqual(
      new ApiError(401, "expired"),
    );
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, listener);
  });

  it("does not emit unauthorized when an older token request returns 401", async () => {
    let resolveRequest!: (response: Response) => void;
    const pendingRequest = new Promise<Response>((resolve) => {
      resolveRequest = resolve;
    });
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "token-A");
    const listener = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, listener);
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(pendingRequest));

    const request = apiRequest("/projects");
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "token-B");
    resolveRequest(
      new Response(JSON.stringify({ detail: "expired" }), { status: 401 }),
    );

    await expect(request).rejects.toEqual(new ApiError(401, "expired"));
    expect(listener).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe(
      "token-B",
    );
    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, listener);
  });
});
