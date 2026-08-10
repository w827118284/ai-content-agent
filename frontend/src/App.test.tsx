import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App, { THREAD_STORAGE_KEY } from "./App";
import { getCurrentUser, loginUser, registerUser } from "./api/auth";
import { ApiError, AUTH_UNAUTHORIZED_EVENT } from "./api/client";
import {
  getWorkflowState,
  listProjects,
  resumeWorkflow,
  startWorkflow,
  WorkflowApiError,
} from "./api/workflows";
import { ACCESS_TOKEN_STORAGE_KEY } from "./auth/token";
import type { AuthUser } from "./types/auth";
import type {
  AgentState,
  ContentProjectSummary,
  ProjectListResponse,
  TopicOption,
  WorkflowResponse,
} from "./types/workflow";

vi.mock("./api/workflows", async () => {
  const actual = await vi.importActual<typeof import("./api/workflows")>(
    "./api/workflows",
  );
  return {
    ...actual,
    startWorkflow: vi.fn(),
    resumeWorkflow: vi.fn(),
    getWorkflowState: vi.fn(),
    listProjects: vi.fn(),
  };
});

vi.mock("./api/auth", () => ({
  getCurrentUser: vi.fn(),
  loginUser: vi.fn(),
  registerUser: vi.fn(),
}));

const mockedStartWorkflow = vi.mocked(startWorkflow);
const mockedResumeWorkflow = vi.mocked(resumeWorkflow);
const mockedGetWorkflowState = vi.mocked(getWorkflowState);
const mockedListProjects = vi.mocked(listProjects);
const mockedGetCurrentUser = vi.mocked(getCurrentUser);
const mockedLoginUser = vi.mocked(loginUser);
const mockedRegisterUser = vi.mocked(registerUser);

const authUser: AuthUser = {
  id: "018f0000-0000-7000-8000-000000000100",
  username: "phase6_user_a",
  created_at: "2026-08-10T05:00:00Z",
};

const threadId = "thread-12345678";
const topics: TopicOption[] = Array.from({ length: 5 }, (_, index) => ({
  id: `topic_${index + 1}`,
  title: `候选选题 ${index + 1}`,
}));

function state(overrides: Partial<AgentState>): AgentState {
  return {
    topic_direction: "LangGraph Human-in-the-loop 实战",
    generated_topics: topics,
    selected_topic: null,
    article_content: null,
    review_feedback: null,
    review_status: null,
    visual_points: [],
    image_urls: [],
    status: "waiting_topic_selection",
    revision_count: 0,
    ...overrides,
  };
}

function topicSelectionResponse(responseThreadId = threadId): WorkflowResponse {
  return {
    thread_id: responseThreadId,
    status: "waiting_topic_selection",
    is_completed: false,
    interrupt: {
      type: "topic_selection",
      message: "请选择一个选题",
      topics,
    },
    state: state({}),
  };
}

function articleReviewResponse(
  revisionCount = 0,
  articleContent = "# 初稿标题\n\n这是第一版文章。",
  responseThreadId = threadId,
): WorkflowResponse {
  return {
    thread_id: responseThreadId,
    status: "waiting_article_review",
    is_completed: false,
    interrupt: {
      type: "article_review",
      message: "请审核文章",
      article_content: articleContent,
      revision_count: revisionCount,
      actions: ["approve", "reject"],
    },
    state: state({
      selected_topic: topics[0].title,
      article_content: articleContent,
      review_status: "pending",
      status: "waiting_article_review",
      revision_count: revisionCount,
    }),
  };
}

function completedResponse(responseThreadId = threadId): WorkflowResponse {
  const visualPoints = ["状态持久化", "Interrupt 恢复", "人工审核闭环"];
  return {
    thread_id: responseThreadId,
    status: "completed",
    is_completed: true,
    interrupt: null,
    state: state({
      selected_topic: topics[0].title,
      article_content: "# 最终文章\n\n文章已经通过审核。",
      review_status: "approved",
      status: "completed",
      revision_count: 1,
      visual_points: visualPoints,
      image_urls: visualPoints.map(
        (_, index) => `https://example.com/mock/image-${index + 1}.png`,
      ),
    }),
  };
}

function projectSummary(
  overrides: Partial<ContentProjectSummary> = {},
): ContentProjectSummary {
  return {
    id: "018f0000-0000-7000-8000-000000000001",
    thread_id: "history-thread-1",
    topic_direction: "历史选题任务",
    selected_topic_title: null,
    status: "waiting_topic_selection",
    revision_count: 0,
    created_at: "2026-08-10T05:00:00Z",
    updated_at: "2026-08-10T06:00:00Z",
    ...overrides,
  };
}

function projectListResponse(
  items: ContentProjectSummary[],
): ProjectListResponse {
  return {
    items,
    total: items.length,
    limit: 20,
    offset: 0,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

async function startFromInitialPage(user: ReturnType<typeof userEvent.setup>) {
  render(<App />);
  const directionInput = await screen.findByRole("textbox", {
    name: "内容方向",
  });
  await user.type(directionInput, "LangGraph Human-in-the-loop 实战");
  await user.click(screen.getByRole("button", { name: "生成选题" }));
  await screen.findByText(topics[0].title);
}

describe("AI content workflow", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "test-access-token");
    mockedGetCurrentUser.mockResolvedValue(authUser);
    mockedListProjects.mockResolvedValue(projectListResponse([]));
  });

  it("starts a workflow and shows five topics", async () => {
    const user = userEvent.setup();
    mockedStartWorkflow.mockResolvedValue(topicSelectionResponse());

    await startFromInitialPage(user);

    expect(mockedStartWorkflow).toHaveBeenCalledWith(
      "LangGraph Human-in-the-loop 实战",
    );
    for (const topic of topics) {
      expect(screen.getByText(topic.title)).toBeInTheDocument();
    }
    expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBe(threadId);
  });

  it("selects a topic and shows the article review page", async () => {
    const user = userEvent.setup();
    mockedStartWorkflow.mockResolvedValue(topicSelectionResponse());
    mockedResumeWorkflow.mockResolvedValue(articleReviewResponse());

    await startFromInitialPage(user);
    await user.click(
      screen.getByRole("button", { name: `选择选题：${topics[0].title}` }),
    );

    expect(await screen.findByText("初稿标题")).toBeInTheDocument();
    expect(screen.getByText("文章审核")).toBeInTheDocument();
    expect(mockedResumeWorkflow).toHaveBeenCalledWith(threadId, {
      action: "select_topic",
      data: { topic_id: "topic_1" },
    });
  });

  it("sends reject feedback and shows the rewritten article", async () => {
    const user = userEvent.setup();
    mockedStartWorkflow.mockResolvedValue(topicSelectionResponse());
    mockedResumeWorkflow
      .mockResolvedValueOnce(articleReviewResponse())
      .mockResolvedValueOnce(
        articleReviewResponse(1, "# 重写标题\n\n已增加实际代码示例。"),
      );

    await startFromInitialPage(user);
    await user.click(
      screen.getByRole("button", { name: `选择选题：${topics[0].title}` }),
    );
    await screen.findByText("初稿标题");

    await user.click(screen.getByRole("button", { name: "要求修改" }));
    await user.type(
      screen.getByRole("textbox", { name: "修改意见" }),
      "增加实际代码示例",
    );
    await user.click(screen.getByRole("button", { name: "提交修改意见" }));

    expect(await screen.findByText("重写标题")).toBeInTheDocument();
    expect(screen.getByText("第 1 次修改")).toBeInTheDocument();
    expect(mockedResumeWorkflow).toHaveBeenNthCalledWith(2, threadId, {
      action: "reject",
      data: { feedback: "增加实际代码示例" },
    });
  });

  it("keeps the new task page when a pending reject resolves later", async () => {
    const user = userEvent.setup();
    const pendingReject = deferred<WorkflowResponse>();
    window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
    mockedGetWorkflowState.mockResolvedValue(articleReviewResponse());
    mockedResumeWorkflow.mockReturnValue(pendingReject.promise);

    render(<App />);
    await screen.findByText("初稿标题");
    await user.click(screen.getByRole("button", { name: "要求修改" }));
    await user.type(
      screen.getByRole("textbox", { name: "修改意见" }),
      "增加实际代码示例",
    );
    await user.click(screen.getByRole("button", { name: "提交修改意见" }));
    await user.click(screen.getByRole("button", { name: "新任务" }));

    await act(async () => {
      pendingReject.resolve(
        articleReviewResponse(1, "# 不应重新激活的旧工作流"),
      );
      await pendingReject.promise;
    });

    expect(
      screen.getByRole("heading", { name: "创建今天的内容方向" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("不应重新激活的旧工作流")).not.toBeInTheDocument();
    expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
  });

  it("supports two consecutive reject cycles", async () => {
    const user = userEvent.setup();
    mockedStartWorkflow.mockResolvedValue(topicSelectionResponse());
    mockedResumeWorkflow
      .mockResolvedValueOnce(articleReviewResponse())
      .mockResolvedValueOnce(articleReviewResponse(1, "# 第一次重写"))
      .mockResolvedValueOnce(articleReviewResponse(2, "# 第二次重写"));

    await startFromInitialPage(user);
    await user.click(
      screen.getByRole("button", { name: `选择选题：${topics[0].title}` }),
    );
    await screen.findByText("初稿标题");

    await user.click(screen.getByRole("button", { name: "要求修改" }));
    await user.type(
      screen.getByRole("textbox", { name: "修改意见" }),
      "第一次意见",
    );
    await user.click(screen.getByRole("button", { name: "提交修改意见" }));
    await screen.findByText("第一次重写");

    await user.click(screen.getByRole("button", { name: "要求修改" }));
    await user.type(
      screen.getByRole("textbox", { name: "修改意见" }),
      "第二次意见",
    );
    await user.click(screen.getByRole("button", { name: "提交修改意见" }));

    expect(await screen.findByText("第二次重写")).toBeInTheDocument();
    expect(screen.getByText("第 2 次修改")).toBeInTheDocument();
    expect(mockedResumeWorkflow).toHaveBeenCalledTimes(3);
  });

  it("approves an article and shows the completed result", async () => {
    const user = userEvent.setup();
    mockedStartWorkflow.mockResolvedValue(topicSelectionResponse());
    mockedResumeWorkflow
      .mockResolvedValueOnce(articleReviewResponse())
      .mockResolvedValueOnce(completedResponse());

    await startFromInitialPage(user);
    await user.click(
      screen.getByRole("button", { name: `选择选题：${topics[0].title}` }),
    );
    await screen.findByText("初稿标题");
    await user.click(screen.getByRole("button", { name: "通过" }));

    expect(await screen.findByText("任务完成")).toBeInTheDocument();
    expect(screen.getByText("最终文章")).toBeInTheDocument();
    expect(screen.getByText("视觉知识点")).toBeInTheDocument();
    expect(screen.getAllByText(/知识点 \d{2}/)).toHaveLength(3);
  });

  it("restores a waiting article review from localStorage", async () => {
    window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
    mockedGetWorkflowState.mockResolvedValue(articleReviewResponse());

    render(<App />);

    expect(await screen.findByText("初稿标题")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "要求修改" })).toBeEnabled();
    expect(mockedGetWorkflowState).toHaveBeenCalledWith(threadId);
  });

  it("clears an obsolete thread after a 404 and returns to start", async () => {
    window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
    mockedGetWorkflowState.mockRejectedValue(
      new WorkflowApiError(404, "workflow thread_id 不存在"),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "创建今天的内容方向" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
    });
  });

  it("loads and displays the history list", async () => {
    mockedListProjects.mockResolvedValue(
      projectListResponse([
        projectSummary(),
        projectSummary({
          id: "018f0000-0000-7000-8000-000000000002",
          thread_id: "history-thread-2",
          topic_direction: "已完成的历史任务",
          selected_topic_title: "LangGraph 状态恢复",
          status: "completed",
          revision_count: 2,
        }),
      ]),
    );

    render(<App />);

    const history = await screen.findByLabelText("历史任务");
    expect(await within(history).findByText("历史选题任务")).toBeInTheDocument();
    expect(within(history).getByText("已完成的历史任务")).toBeInTheDocument();
    expect(within(history).getByText("LangGraph 状态恢复")).toBeInTheDocument();
    expect(within(history).getByText("2 次修改")).toBeInTheDocument();
  });

  it("opens a waiting topic selection history item", async () => {
    const user = userEvent.setup();
    const project = projectSummary();
    mockedListProjects.mockResolvedValue(projectListResponse([project]));
    mockedGetWorkflowState.mockResolvedValue(
      topicSelectionResponse(project.thread_id),
    );

    render(<App />);
    await user.click(
      await screen.findByRole("button", {
        name: `打开历史任务：${project.topic_direction}`,
      }),
    );

    expect(await screen.findByText(topics[0].title)).toBeInTheDocument();
    expect(mockedGetWorkflowState).toHaveBeenCalledWith(project.thread_id);
  });

  it("opens a waiting review history item and can reject it", async () => {
    const user = userEvent.setup();
    const project = projectSummary({
      thread_id: "history-review-thread",
      topic_direction: "历史审核任务",
      selected_topic_title: topics[0].title,
      status: "waiting_article_review",
    });
    mockedListProjects.mockResolvedValue(projectListResponse([project]));
    mockedGetWorkflowState.mockResolvedValue(
      articleReviewResponse(0, "# 历史初稿", project.thread_id),
    );
    mockedResumeWorkflow.mockResolvedValue(
      articleReviewResponse(1, "# 历史重写稿", project.thread_id),
    );

    render(<App />);
    await user.click(
      await screen.findByRole("button", {
        name: `打开历史任务：${project.topic_direction}`,
      }),
    );
    await screen.findByText("历史初稿");
    await user.click(screen.getByRole("button", { name: "要求修改" }));
    await user.type(
      screen.getByRole("textbox", { name: "修改意见" }),
      "增加恢复示例",
    );
    await user.click(screen.getByRole("button", { name: "提交修改意见" }));

    expect(await screen.findByText("历史重写稿")).toBeInTheDocument();
    expect(mockedResumeWorkflow).toHaveBeenCalledWith(project.thread_id, {
      action: "reject",
      data: { feedback: "增加恢复示例" },
    });
  });

  it("opens a completed history item in the result view", async () => {
    const user = userEvent.setup();
    const project = projectSummary({
      thread_id: "history-completed-thread",
      topic_direction: "历史完成任务",
      selected_topic_title: topics[0].title,
      status: "completed",
      revision_count: 1,
    });
    mockedListProjects.mockResolvedValue(projectListResponse([project]));
    mockedGetWorkflowState.mockResolvedValue(
      completedResponse(project.thread_id),
    );

    render(<App />);
    await user.click(
      await screen.findByRole("button", {
        name: `打开历史任务：${project.topic_direction}`,
      }),
    );

    expect(await screen.findByText("任务完成")).toBeInTheDocument();
    expect(screen.getByText("最终文章")).toBeInTheDocument();
  });

  it("refreshes history after starting a new workflow", async () => {
    const user = userEvent.setup();
    mockedListProjects
      .mockResolvedValueOnce(projectListResponse([]))
      .mockResolvedValueOnce(
        projectListResponse([
          projectSummary({
            thread_id: threadId,
            topic_direction: "LangGraph Human-in-the-loop 实战",
          }),
        ]),
      );
    mockedStartWorkflow.mockResolvedValue(topicSelectionResponse());

    await startFromInitialPage(user);

    await waitFor(() => expect(mockedListProjects).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByRole("button", {
        name: "打开历史任务：LangGraph Human-in-the-loop 实战",
      }),
    ).toBeInTheDocument();
  });

  it("refreshes history after a resume changes workflow status", async () => {
    const user = userEvent.setup();
    const waitingProject = projectSummary({ thread_id: threadId });
    const reviewProject = projectSummary({
      thread_id: threadId,
      selected_topic_title: topics[0].title,
      status: "waiting_article_review",
    });
    mockedListProjects
      .mockResolvedValueOnce(projectListResponse([waitingProject]))
      .mockResolvedValueOnce(projectListResponse([reviewProject]));
    window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
    mockedGetWorkflowState.mockResolvedValue(topicSelectionResponse());
    mockedResumeWorkflow.mockResolvedValue(articleReviewResponse());

    render(<App />);
    await screen.findByRole("button", {
      name: `选择选题：${topics[0].title}`,
    });
    await user.click(
      screen.getByRole("button", { name: `选择选题：${topics[0].title}` }),
    );

    expect(await screen.findByText("初稿标题")).toBeInTheDocument();
    await waitFor(() => expect(mockedListProjects).toHaveBeenCalledTimes(2));
    const history = screen.getByLabelText("历史任务");
    expect(within(history).getByText("等待审核")).toBeInTheDocument();
  });

  it("keeps the active workflow usable when history loading fails", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
    mockedListProjects.mockRejectedValue(new Error("history unavailable"));
    mockedGetWorkflowState.mockResolvedValue(articleReviewResponse());
    mockedResumeWorkflow.mockResolvedValue(
      articleReviewResponse(1, "# 历史服务失败后的重写稿"),
    );

    render(<App />);

    expect(await screen.findByText("初稿标题")).toBeInTheDocument();
    expect(screen.getByText("历史记录加载失败")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "要求修改" }));
    await user.type(
      screen.getByRole("textbox", { name: "修改意见" }),
      "继续重写",
    );
    await user.click(screen.getByRole("button", { name: "提交修改意见" }));

    expect(
      await screen.findByText("历史服务失败后的重写稿"),
    ).toBeInTheDocument();
  });

  it("updates localStorage when switching to another history thread", async () => {
    const user = userEvent.setup();
    const newProject = projectSummary({
      thread_id: "new-active-history-thread",
      topic_direction: "切换后的历史任务",
    });
    window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
    mockedListProjects.mockResolvedValue(projectListResponse([newProject]));
    mockedGetWorkflowState
      .mockResolvedValueOnce(articleReviewResponse())
      .mockResolvedValueOnce(topicSelectionResponse(newProject.thread_id));

    render(<App />);
    await screen.findByText("初稿标题");
    await user.click(
      await screen.findByRole("button", {
        name: `打开历史任务：${newProject.topic_direction}`,
      }),
    );

    await screen.findByText(topics[0].title);
    expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBe(
      newProject.thread_id,
    );
  });

  it("keeps the user-selected history thread when startup restore resolves later", async () => {
    const user = userEvent.setup();
    const startupThreadId = "startup-thread-a";
    const selectedThreadId = "selected-thread-b";
    const startupRestore = deferred<WorkflowResponse>();
    const historySwitch = deferred<WorkflowResponse>();
    const selectedProject = projectSummary({
      thread_id: selectedThreadId,
      topic_direction: "用户选择的任务 B",
      status: "waiting_article_review",
      selected_topic_title: topics[0].title,
    });
    window.localStorage.setItem(THREAD_STORAGE_KEY, startupThreadId);
    mockedListProjects.mockResolvedValue(
      projectListResponse([selectedProject]),
    );
    mockedGetWorkflowState
      .mockReturnValueOnce(startupRestore.promise)
      .mockReturnValueOnce(historySwitch.promise);

    render(<App />);
    await waitFor(() => {
      expect(mockedGetWorkflowState).toHaveBeenCalledWith(startupThreadId);
    });
    await user.click(
      await screen.findByRole("button", {
        name: `打开历史任务：${selectedProject.topic_direction}`,
      }),
    );

    await act(async () => {
      historySwitch.resolve(
        articleReviewResponse(0, "# 用户选择的 B 文章", selectedThreadId),
      );
      await historySwitch.promise;
    });
    expect(await screen.findByText("用户选择的 B 文章")).toBeInTheDocument();

    await act(async () => {
      startupRestore.resolve(
        articleReviewResponse(0, "# 过期的 A 文章", startupThreadId),
      );
      await startupRestore.promise;
    });

    expect(screen.getByText("用户选择的 B 文章")).toBeInTheDocument();
    expect(screen.queryByText("过期的 A 文章")).not.toBeInTheDocument();
    expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBe(
      selectedThreadId,
    );
  });

  it("keeps the new task page when a pending history switch resolves later", async () => {
    const user = userEvent.setup();
    const selectedProject = projectSummary({
      thread_id: "pending-history-thread-b",
      topic_direction: "等待返回的任务 B",
      status: "waiting_article_review",
      selected_topic_title: topics[0].title,
    });
    const historySwitch = deferred<WorkflowResponse>();
    mockedListProjects.mockResolvedValue(
      projectListResponse([selectedProject]),
    );
    mockedGetWorkflowState.mockReturnValue(historySwitch.promise);

    render(<App />);
    await user.click(
      await screen.findByRole("button", {
        name: `打开历史任务：${selectedProject.topic_direction}`,
      }),
    );
    await user.click(screen.getByRole("button", { name: "新任务" }));

    await act(async () => {
      historySwitch.resolve(
        articleReviewResponse(
          0,
          "# 不应重新激活的 B 文章",
          selectedProject.thread_id,
        ),
      );
      await historySwitch.promise;
    });

    expect(
      screen.getByRole("heading", { name: "创建今天的内容方向" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("不应重新激活的 B 文章"),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
  });

  it("keeps the newest history refresh when the initial request resolves later", async () => {
    const user = userEvent.setup();
    const initialHistory = deferred<ProjectListResponse>();
    const postStartHistory = deferred<ProjectListResponse>();
    const staleProject = projectSummary({
      thread_id: "stale-history-thread-a",
      topic_direction: "过期历史列表 A",
    });
    const newestProject = projectSummary({
      id: "018f0000-0000-7000-8000-000000000099",
      thread_id: threadId,
      topic_direction: "最新历史列表 B",
    });
    mockedListProjects
      .mockReturnValueOnce(initialHistory.promise)
      .mockReturnValueOnce(postStartHistory.promise);
    mockedStartWorkflow.mockResolvedValue(topicSelectionResponse());

    render(<App />);
    const directionInput = await screen.findByRole("textbox", {
      name: "内容方向",
    });
    await user.type(directionInput, "LangGraph 异步竞态测试");
    await user.click(screen.getByRole("button", { name: "生成选题" }));
    await screen.findByText(topics[0].title);
    await waitFor(() => expect(mockedListProjects).toHaveBeenCalledTimes(2));

    await act(async () => {
      postStartHistory.resolve(projectListResponse([newestProject]));
      await postStartHistory.promise;
    });
    expect(
      await screen.findByRole("button", {
        name: `打开历史任务：${newestProject.topic_direction}`,
      }),
    ).toBeInTheDocument();

    await act(async () => {
      initialHistory.resolve(projectListResponse([staleProject]));
      await initialHistory.promise;
    });

    expect(
      screen.getByRole("button", {
        name: `打开历史任务：${newestProject.topic_direction}`,
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: `打开历史任务：${staleProject.topic_direction}`,
      }),
    ).not.toBeInTheDocument();
  });
});

describe("authentication lifecycle", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    mockedGetCurrentUser.mockResolvedValue(authUser);
    mockedListProjects.mockResolvedValue(projectListResponse([]));
  });

  it("shows login UI when no token exists", async () => {
    render(<App />);

    expect(
      await screen.findByRole("tab", { name: "登录" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("textbox", { name: "用户名" })).toBeInTheDocument();
    expect(mockedGetCurrentUser).not.toHaveBeenCalled();
  });

  it("registers, logs in, stores the token, and opens the workspace", async () => {
    const user = userEvent.setup();
    const registeredUser = { ...authUser, username: "registered_user" };
    mockedRegisterUser.mockResolvedValue(registeredUser);
    mockedLoginUser.mockResolvedValue({
      access_token: "registered-access-token",
      token_type: "bearer",
      expires_in: 3600,
    });

    render(<App />);
    await user.click(await screen.findByRole("tab", { name: "注册" }));
    await user.type(screen.getByRole("textbox", { name: "用户名" }), "registered_user");
    await user.type(screen.getByLabelText("密码"), "registered-password");
    await user.click(screen.getByRole("button", { name: "注册并登录" }));

    expect(await screen.findByText("registered_user")).toBeInTheDocument();
    expect(mockedRegisterUser).toHaveBeenCalledWith({
      username: "registered_user",
      password: "registered-password",
    });
    expect(mockedLoginUser).toHaveBeenCalledOnce();
    expect(window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe(
      "registered-access-token",
    );
  });

  it("logs in, verifies /auth/me, and clears a previous user's thread", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(THREAD_STORAGE_KEY, "user-a-thread");
    const userB = { ...authUser, username: "phase6_user_b" };
    mockedLoginUser.mockResolvedValue({
      access_token: "user-b-access-token",
      token_type: "bearer",
      expires_in: 3600,
    });
    mockedGetCurrentUser.mockResolvedValue(userB);

    render(<App />);
    await user.type(await screen.findByRole("textbox", { name: "用户名" }), "phase6_user_b");
    await user.type(screen.getByLabelText("密码"), "user-b-password");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("phase6_user_b")).toBeInTheDocument();
    expect(mockedGetCurrentUser).toHaveBeenCalledWith("user-b-access-token");
    expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
    expect(mockedGetWorkflowState).not.toHaveBeenCalled();
  });

  it("restores authentication from a stored token through /auth/me", async () => {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "stored-access-token");

    render(<App />);

    expect(await screen.findByText(authUser.username)).toBeInTheDocument();
    expect(mockedGetCurrentUser).toHaveBeenCalledWith("stored-access-token");
    expect(await screen.findByLabelText("历史任务")).toBeInTheDocument();
  });

  it("clears invalid startup credentials and returns to login", async () => {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "expired-access-token");
    window.localStorage.setItem(THREAD_STORAGE_KEY, "expired-user-thread");
    mockedGetCurrentUser.mockRejectedValue(new ApiError(401, "token expired"));

    render(<App />);

    expect(await screen.findByRole("tab", { name: "登录" })).toBeInTheDocument();
    expect(window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
  });

  it("logs out and clears both token and active thread", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "active-access-token");
    window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
    mockedGetWorkflowState.mockResolvedValue(topicSelectionResponse());

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "退出登录" }));

    expect(await screen.findByRole("tab", { name: "登录" })).toBeInTheDocument();
    expect(window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
  });

  it("ignores user A workflow response after logout and user B login", async () => {
    const user = userEvent.setup();
    const pendingStart = deferred<WorkflowResponse>();
    const userB = { ...authUser, username: "phase6_user_b" };
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "user-a-token");
    mockedStartWorkflow.mockReturnValue(pendingStart.promise);

    render(<App />);
    await user.type(
      await screen.findByRole("textbox", { name: "内容方向" }),
      "用户 A 的工作流",
    );
    await user.click(screen.getByRole("button", { name: "生成选题" }));
    await user.click(screen.getByRole("button", { name: "退出登录" }));

    mockedLoginUser.mockResolvedValue({
      access_token: "user-b-token",
      token_type: "bearer",
      expires_in: 3600,
    });
    mockedGetCurrentUser.mockResolvedValue(userB);
    await user.type(
      await screen.findByRole("textbox", { name: "用户名" }),
      userB.username,
    );
    await user.type(screen.getByLabelText("密码"), "user-b-password");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText(userB.username)).toBeInTheDocument();

    await act(async () => {
      pendingStart.resolve(topicSelectionResponse("user-a-thread"));
      await pendingStart.promise;
    });

    expect(screen.getByText(userB.username)).toBeInTheDocument();
    expect(window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe(
      "user-b-token",
    );
    expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
    expect(screen.queryByText(topics[0].title)).not.toBeInTheDocument();
  });

  it("automatically logs out when an authenticated API emits a 401", async () => {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "active-access-token");
    window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);

    render(<App />);
    await screen.findByText(authUser.username);
    act(() => {
      window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
    });

    expect(await screen.findByRole("tab", { name: "登录" })).toBeInTheDocument();
    expect(window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
  });

  it("treats a history 401 as session expiration instead of history failure", async () => {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "active-access-token");
    mockedListProjects.mockImplementation(() => {
      window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
      return Promise.reject(new ApiError(401, "expired"));
    });

    render(<App />);

    expect(await screen.findByRole("tab", { name: "登录" })).toBeInTheDocument();
    expect(screen.queryByText("历史记录加载失败")).not.toBeInTheDocument();
  });
});
