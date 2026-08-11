import { getAccessToken } from "../auth/token";


const API_V1_PREFIX = "/api/v1";
const DEFAULT_API_ORIGIN = "http://127.0.0.1:8000";

export function normalizeApiBaseUrl(configuredBaseUrl?: string): string {
  const baseUrl = (configuredBaseUrl?.trim() || DEFAULT_API_ORIGIN).replace(
    /\/+$/,
    "",
  );
  return baseUrl.endsWith(API_V1_PREFIX)
    ? baseUrl
    : `${baseUrl}${API_V1_PREFIX}`;
}

export const API_BASE_URL = normalizeApiBaseUrl(
  import.meta.env.VITE_API_BASE_URL,
);
export const AUTH_UNAUTHORIZED_EVENT = "content-agent:unauthorized";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiRequestOptions {
  authenticated?: boolean;
  authToken?: string;
}

function detailMessage(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) {
    return null;
  }

  const detail = payload.detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (!Array.isArray(detail)) {
    return null;
  }

  const messages = detail
    .map((item) => {
      if (item && typeof item === "object" && "msg" in item) {
        return String(item.msg);
      }
      return null;
    })
    .filter((message): message is string => Boolean(message));
  return messages.length > 0 ? messages.join("；") : null;
}

export async function apiResponse(
  path: string,
  init: RequestInit = {},
  options: ApiRequestOptions = {},
): Promise<Response> {
  const authenticated = options.authenticated ?? true;
  const token = options.authToken ?? (authenticated ? getAccessToken() : null);
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (authenticated && token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "无法连接后端服务。");
  }

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as unknown;
    if (
      response.status === 401 &&
      authenticated &&
      token === getAccessToken()
    ) {
      window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
    }
    throw new ApiError(
      response.status,
      detailMessage(payload) ?? `请求失败（${response.status}）`,
    );
  }
  return response;
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: ApiRequestOptions = {},
): Promise<T> {
  const response = await apiResponse(path, init, options);
  const payload = (await response.json().catch(() => null)) as unknown;
  return payload as T;
}
