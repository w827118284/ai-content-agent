import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App, { THREAD_STORAGE_KEY } from "./App";
import {
  getWorkflowState,
  resumeWorkflow,
  startWorkflow,
  WorkflowApiError,
} from "./api/workflows";
import type {
  AgentState,
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
  };
});

const mockedStartWorkflow = vi.mocked(startWorkflow);
const mockedResumeWorkflow = vi.mocked(resumeWorkflow);
const mockedGetWorkflowState = vi.mocked(getWorkflowState);

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

function topicSelectionResponse(): WorkflowResponse {
  return {
    thread_id: threadId,
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
): WorkflowResponse {
  return {
    thread_id: threadId,
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

function completedResponse(): WorkflowResponse {
  const visualPoints = ["状态持久化", "Interrupt 恢复", "人工审核闭环"];
  return {
    thread_id: threadId,
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
});
