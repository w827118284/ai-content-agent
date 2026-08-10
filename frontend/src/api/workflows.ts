import type {
  ProjectListResponse,
  WorkflowResponse,
  WorkflowResumeRequest,
} from "../types/workflow";
import { ApiError, apiRequest } from "./client";


export { ApiError as WorkflowApiError };

export function startWorkflow(topicDirection: string): Promise<WorkflowResponse> {
  return apiRequest<WorkflowResponse>("/api/v1/workflows/start", {
    method: "POST",
    body: JSON.stringify({ topic_direction: topicDirection }),
  });
}

export function resumeWorkflow(
  threadId: string,
  body: WorkflowResumeRequest,
): Promise<WorkflowResponse> {
  return apiRequest<WorkflowResponse>(
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
  return apiRequest<WorkflowResponse>(
    `/api/v1/workflows/${encodeURIComponent(threadId)}/state`,
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
  return apiRequest<ProjectListResponse>(`/api/v1/projects?${query.toString()}`);
}
