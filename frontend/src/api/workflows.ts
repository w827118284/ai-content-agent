import type {
  WorkflowResponse,
  WorkflowResumeRequest,
} from "../types/workflow";

const configuredBaseUrl =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const API_BASE_URL = configuredBaseUrl.replace(/\/$/, "");

export class WorkflowApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "WorkflowApiError";
  }
}

function detailMessage(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) {
    return null;
  }

  const detail = payload.detail;
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
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

  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
  } catch {
    throw new WorkflowApiError(0, "无法连接后端服务。");
  }

  const payload = (await response.json().catch(() => null)) as unknown;

  if (!response.ok) {
    if (response.status === 409) {
      throw new WorkflowApiError(
        response.status,
        "当前工作流不接受这个操作，请刷新状态。",
      );
    }

    throw new WorkflowApiError(
      response.status,
      detailMessage(payload) ?? `请求失败（${response.status}）`,
    );
  }

  return payload as T;
}

export function startWorkflow(topicDirection: string): Promise<WorkflowResponse> {
  return request<WorkflowResponse>("/api/v1/workflows/start", {
    method: "POST",
    body: JSON.stringify({ topic_direction: topicDirection }),
  });
}

export function resumeWorkflow(
  threadId: string,
  body: WorkflowResumeRequest,
): Promise<WorkflowResponse> {
  return request<WorkflowResponse>(
    `/api/v1/workflows/${encodeURIComponent(threadId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export function getWorkflowState(
  threadId: string,
): Promise<WorkflowResponse> {
  return request<WorkflowResponse>(
    `/api/v1/workflows/${encodeURIComponent(threadId)}/state`,
  );
}
