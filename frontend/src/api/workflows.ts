import type {
  ProjectListResponse,
  WorkflowResponse,
  WorkflowResumeRequest,
  WorkflowStreamEvent,
} from "../types/workflow";
import { ApiError, apiRequest, apiResponse } from "./client";
import { consumeSseStream } from "./sse";


export { ApiError as WorkflowApiError };

export function startWorkflow(topicDirection: string): Promise<WorkflowResponse> {
  return apiRequest<WorkflowResponse>("/workflows/start", {
    method: "POST",
    body: JSON.stringify({ topic_direction: topicDirection }),
  });
}

export function resumeWorkflow(
  threadId: string,
  body: WorkflowResumeRequest,
): Promise<WorkflowResponse> {
  return apiRequest<WorkflowResponse>(
    `/workflows/${encodeURIComponent(threadId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

interface WorkflowStreamOptions {
  signal: AbortSignal;
  onEvent: (event: WorkflowStreamEvent) => void;
}

async function streamWorkflow(
  path: string,
  body: unknown,
  options: WorkflowStreamOptions,
): Promise<void> {
  const response = await apiResponse(path, {
    method: "POST",
    body: JSON.stringify(body),
    signal: options.signal,
  });
  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().includes("text/event-stream")) {
    throw new ApiError(0, "服务端未返回工作流事件流");
  }
  if (!response.body) {
    throw new ApiError(0, "浏览器无法读取工作流事件流");
  }

  await consumeSseStream(response.body, (event) => {
    if (
      !["meta", "progress", "interrupt", "completed", "error"].includes(
        event.event,
      )
    ) {
      return;
    }
    let data: unknown;
    try {
      data = JSON.parse(event.data);
    } catch {
      throw new ApiError(0, "工作流事件格式无效");
    }
    options.onEvent({ type: event.event, data } as WorkflowStreamEvent);
  });
}

export function startWorkflowStream(
  topicDirection: string,
  options: WorkflowStreamOptions,
): Promise<void> {
  return streamWorkflow(
    "/workflows/start/stream",
    { topic_direction: topicDirection },
    options,
  );
}

export function resumeWorkflowStream(
  threadId: string,
  body: WorkflowResumeRequest,
  options: WorkflowStreamOptions,
): Promise<void> {
  return streamWorkflow(
    `/workflows/${encodeURIComponent(threadId)}/resume/stream`,
    body,
    options,
  );
}

export function getWorkflowState(
  threadId: string,
): Promise<WorkflowResponse> {
  return apiRequest<WorkflowResponse>(
    `/workflows/${encodeURIComponent(threadId)}/state`,
  );
}

export function listProjects(
  limit = 20,
  offset = 0,
): Promise<ProjectListResponse> {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiRequest<ProjectListResponse>(`/projects?${query.toString()}`);
}
