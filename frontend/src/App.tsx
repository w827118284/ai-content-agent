import {
  Bot,
  LoaderCircle,
  LogOut,
  RefreshCw,
  UserRound,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { getCurrentUser } from "./api/auth";
import { AUTH_UNAUTHORIZED_EVENT } from "./api/client";
import {
  getWorkflowState,
  listProjects,
  resumeWorkflow,
  startWorkflow,
  WorkflowApiError,
} from "./api/workflows";
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "./auth/token";
import { ArticleReview } from "./components/ArticleReview";
import { AuthScreen } from "./components/AuthScreen";
import { HistorySidebar } from "./components/HistorySidebar";
import { ResultView } from "./components/ResultView";
import { StartPanel } from "./components/StartPanel";
import { TopicSelection } from "./components/TopicSelection";
import { WorkflowProgress } from "./components/WorkflowProgress";
import type { AuthUser } from "./types/auth";
import type {
  ContentProjectSummary,
  WorkflowResponse,
  WorkflowStatus,
} from "./types/workflow";

export const THREAD_STORAGE_KEY = "content_agent_thread_id";

const statusLabels: Record<WorkflowStatus, string> = {
  planning_topics: "正在生成选题",
  waiting_topic_selection: "等待选择选题",
  drafting: "正在生成文章",
  waiting_article_review: "等待文章审核",
  rewriting: "正在重写文章",
  extracting_visuals: "正在提炼视觉点",
  generating_images: "正在生成图片",
  completed: "已完成",
};

function errorMessage(error: unknown): string {
  if (error instanceof WorkflowApiError) {
    return error.message;
  }
  return "请求处理失败，请稍后重试。";
}

interface WorkspaceProps {
  user: AuthUser;
  onLogout: () => void;
}

function Workspace({ user, onLogout }: WorkspaceProps) {
  const [workflow, setWorkflow] = useState<WorkflowResponse | null>(null);
  const [projects, setProjects] = useState<ContentProjectSummary[]>([]);
  const [projectTotal, setProjectTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [switchingThreadId, setSwitchingThreadId] = useState<string | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const workflowLoadGeneration = useRef(0);
  const historyRefreshGeneration = useRef(0);

  useEffect(() => {
    return () => {
      workflowLoadGeneration.current += 1;
      historyRefreshGeneration.current += 1;
    };
  }, []);

  const refreshHistory = useCallback(
    async (initialLoad = false): Promise<void> => {
      const refreshGeneration = ++historyRefreshGeneration.current;
      if (initialLoad) {
        setHistoryLoading(true);
      }
      try {
        const response = await listProjects();
        if (refreshGeneration !== historyRefreshGeneration.current) {
          return;
        }
        setProjects(response.items);
        setProjectTotal(response.total);
        setHistoryError(null);
      } catch {
        if (refreshGeneration !== historyRefreshGeneration.current) {
          return;
        }
        setHistoryError(
          initialLoad ? "历史记录加载失败" : "历史记录刷新失败",
        );
      } finally {
        if (refreshGeneration === historyRefreshGeneration.current) {
          setHistoryLoading(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    void refreshHistory(true);

    const storedThreadId = window.localStorage.getItem(THREAD_STORAGE_KEY);
    if (!storedThreadId) {
      setRestoring(false);
      return;
    }

    let cancelled = false;
    const loadGeneration = ++workflowLoadGeneration.current;

    getWorkflowState(storedThreadId)
      .then((response) => {
        if (
          cancelled ||
          loadGeneration !== workflowLoadGeneration.current
        ) {
          return;
        }
        setWorkflow(response);
      })
      .catch((requestError: unknown) => {
        if (
          cancelled ||
          loadGeneration !== workflowLoadGeneration.current
        ) {
          return;
        }
        if (
          requestError instanceof WorkflowApiError &&
          requestError.status === 404
        ) {
          window.localStorage.removeItem(THREAD_STORAGE_KEY);
          return;
        }
        setError(errorMessage(requestError));
      })
      .finally(() => {
        if (
          !cancelled &&
          loadGeneration === workflowLoadGeneration.current
        ) {
          setRestoring(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [refreshHistory]);

  function applyWorkflow(response: WorkflowResponse) {
    setWorkflow(response);
    window.localStorage.setItem(THREAD_STORAGE_KEY, response.thread_id);
  }

  async function runRequest(
    request: () => Promise<WorkflowResponse>,
  ): Promise<void> {
    if (busy) {
      return;
    }
    const requestGeneration = ++workflowLoadGeneration.current;
    setBusy(true);
    setError(null);
    try {
      const response = await request();
      if (requestGeneration !== workflowLoadGeneration.current) {
        return;
      }
      applyWorkflow(response);
      void refreshHistory();
    } catch (requestError) {
      if (requestGeneration !== workflowLoadGeneration.current) {
        return;
      }
      setError(errorMessage(requestError));
    } finally {
      if (requestGeneration === workflowLoadGeneration.current) {
        setBusy(false);
      }
    }
  }

  async function handleStart(topicDirection: string) {
    await runRequest(() => startWorkflow(topicDirection));
  }

  async function handleSelect(topicId: string) {
    if (!workflow) {
      return;
    }
    await runRequest(() =>
      resumeWorkflow(workflow.thread_id, {
        action: "select_topic",
        data: { topic_id: topicId },
      }),
    );
  }

  async function handleReject(feedback: string) {
    if (!workflow) {
      return;
    }
    await runRequest(() =>
      resumeWorkflow(workflow.thread_id, {
        action: "reject",
        data: { feedback },
      }),
    );
  }

  async function handleApprove() {
    if (!workflow) {
      return;
    }
    await runRequest(() =>
      resumeWorkflow(workflow.thread_id, { action: "approve" }),
    );
  }

  async function handleOpenProject(project: ContentProjectSummary) {
    if (busy || switchingThreadId !== null) {
      return;
    }

    const loadGeneration = ++workflowLoadGeneration.current;
    setSwitchingThreadId(project.thread_id);
    setError(null);
    try {
      const response = await getWorkflowState(project.thread_id);
      if (loadGeneration !== workflowLoadGeneration.current) {
        return;
      }
      applyWorkflow(response);
    } catch (requestError) {
      if (loadGeneration !== workflowLoadGeneration.current) {
        return;
      }
      setError(errorMessage(requestError));
    } finally {
      if (loadGeneration === workflowLoadGeneration.current) {
        setSwitchingThreadId(null);
        setRestoring(false);
      }
    }
  }

  function handleNewTask() {
    workflowLoadGeneration.current += 1;
    historyRefreshGeneration.current += 1;
    window.localStorage.removeItem(THREAD_STORAGE_KEY);
    setWorkflow(null);
    setError(null);
    setBusy(false);
    setRestoring(false);
    setSwitchingThreadId(null);
  }

  function renderWorkflow() {
    if (!workflow) {
      return <StartPanel busy={busy} onStart={handleStart} />;
    }

    if (
      workflow.status === "waiting_topic_selection" &&
      workflow.interrupt?.type === "topic_selection"
    ) {
      return (
        <TopicSelection
          topics={workflow.state.generated_topics}
          busy={busy}
          onSelect={handleSelect}
        />
      );
    }

    if (
      workflow.status === "waiting_article_review" &&
      workflow.interrupt?.type === "article_review" &&
      workflow.state.selected_topic &&
      workflow.state.article_content
    ) {
      return (
        <ArticleReview
          selectedTopic={workflow.state.selected_topic}
          articleContent={workflow.state.article_content}
          revisionCount={workflow.state.revision_count}
          busy={busy}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      );
    }

    if (
      workflow.status === "completed" &&
      workflow.state.selected_topic &&
      workflow.state.article_content
    ) {
      return (
        <ResultView
          selectedTopic={workflow.state.selected_topic}
          articleContent={workflow.state.article_content}
          revisionCount={workflow.state.revision_count}
          visualPoints={workflow.state.visual_points}
          imageUrls={workflow.state.image_urls}
          onNewTask={handleNewTask}
        />
      );
    }

    return (
      <div className="processing-state" role="status">
        <LoaderCircle className="spin" size={26} aria-hidden="true" />
        <h2>{statusLabels[workflow.status]}</h2>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <Bot size={22} />
          </span>
          <div>
            <p>AI CONTENT DESK</p>
            <h1>AI 内容运营智能体</h1>
          </div>
        </div>
        <div className="topbar-actions">
          {workflow ? (
            <div className="workflow-identity">
              <span className="status-dot" aria-hidden="true" />
              <div>
                <span>{statusLabels[workflow.status]}</span>
                <code>{workflow.thread_id.slice(0, 8)}</code>
              </div>
            </div>
          ) : null}
          <div className="account-identity">
            <UserRound size={17} aria-hidden="true" />
            <span>{user.username}</span>
            <button
              className="icon-button"
              type="button"
              onClick={onLogout}
              aria-label="退出登录"
              title="退出登录"
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </header>

      <main className="main-content">
        <div className="workspace-layout">
          <HistorySidebar
            projects={projects}
            total={projectTotal}
            activeThreadId={workflow?.thread_id ?? null}
            loading={historyLoading}
            error={historyError}
            switchingThreadId={switchingThreadId}
            onOpenProject={(project) => void handleOpenProject(project)}
            onNewTask={handleNewTask}
            onRefresh={() => void refreshHistory(true)}
          />

          <div className="workspace-main">
            {error ? (
              <div className="error-banner" role="alert">
                <span>{error}</span>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => setError(null)}
                  aria-label="关闭错误提示"
                  title="关闭"
                >
                  <X size={17} />
                </button>
              </div>
            ) : null}

            {restoring ? (
              <div className="restore-state" role="status">
                <RefreshCw className="spin" size={24} aria-hidden="true" />
                <span>正在恢复最近任务</span>
              </div>
            ) : workflow ? (
              <div className="workbench">
                <WorkflowProgress status={workflow.status} />
                <div className="workflow-surface">{renderWorkflow()}</div>
              </div>
            ) : (
              <div className="start-layout">{renderWorkflow()}</div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}


type AuthenticationState = "checking" | "anonymous" | "authenticated";

export default function App() {
  const [authenticationState, setAuthenticationState] =
    useState<AuthenticationState>("checking");
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);

  const logout = useCallback(() => {
    clearAccessToken();
    window.localStorage.removeItem(THREAD_STORAGE_KEY);
    setCurrentUser(null);
    setAuthenticationState("anonymous");
  }, []);

  useEffect(() => {
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, logout);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, logout);
  }, [logout]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      setAuthenticationState("anonymous");
      return;
    }

    let cancelled = false;
    getCurrentUser(token)
      .then((user) => {
        if (!cancelled) {
          setCurrentUser(user);
          setAuthenticationState("authenticated");
        }
      })
      .catch(() => {
        if (!cancelled) {
          logout();
        }
      });

    return () => {
      cancelled = true;
    };
  }, [logout]);

  function handleAuthenticated(token: string, user: AuthUser) {
    window.localStorage.removeItem(THREAD_STORAGE_KEY);
    setAccessToken(token);
    setCurrentUser(user);
    setAuthenticationState("authenticated");
  }

  if (authenticationState === "checking") {
    return (
      <main className="auth-page">
        <div className="auth-checking" role="status">
          <LoaderCircle className="spin" size={24} aria-hidden="true" />
          <span>正在验证登录状态</span>
        </div>
      </main>
    );
  }

  if (authenticationState === "anonymous" || currentUser === null) {
    return <AuthScreen onAuthenticated={handleAuthenticated} />;
  }

  return <Workspace user={currentUser} onLogout={logout} />;
}
