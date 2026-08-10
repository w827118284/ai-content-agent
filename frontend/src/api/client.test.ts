import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ACCESS_TOKEN_STORAGE_KEY } from "../auth/token";
import {
  apiRequest,
  ApiError,
  AUTH_UNAUTHORIZED_EVENT,
} from "./client";


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

    await apiRequest<{ ok: boolean }>("/api/v1/projects");

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

    await apiRequest("/api/v1/auth/register", {}, { authenticated: false });

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

    await expect(apiRequest("/api/v1/projects")).rejects.toEqual(
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

    const request = apiRequest("/api/v1/projects");
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
