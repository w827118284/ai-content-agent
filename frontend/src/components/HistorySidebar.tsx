import {
  CheckCircle2,
  Clock3,
  History,
  LoaderCircle,
  Plus,
  RefreshCw,
} from "lucide-react";

import type { ContentProjectSummary } from "../types/workflow";

const statusLabels: Record<ContentProjectSummary["status"], string> = {
  starting: "正在启动",
  planning_topics: "正在生成选题",
  waiting_topic_selection: "等待选题",
  drafting: "正在生成文章",
  waiting_article_review: "等待审核",
  rewriting: "正在重写",
  extracting_visuals: "正在提炼视觉点",
  generating_images: "正在生成图片",
  failed: "生成失败",
  completed: "已完成",
};

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

interface HistorySidebarProps {
  projects: ContentProjectSummary[];
  total: number;
  activeThreadId: string | null;
  loading: boolean;
  error: string | null;
  switchingThreadId: string | null;
  onOpenProject: (project: ContentProjectSummary) => void;
  onNewTask: () => void;
  onRefresh: () => void;
}

function updatedAtLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date);
}

export function HistorySidebar({
  projects,
  total,
  activeThreadId,
  loading,
  error,
  switchingThreadId,
  onOpenProject,
  onNewTask,
  onRefresh,
}: HistorySidebarProps) {
  return (
    <aside className="history-sidebar" aria-label="历史任务">
      <div className="history-header">
        <div>
          <span className="history-title-icon" aria-hidden="true">
            <History size={17} />
          </span>
          <div>
            <h2>历史任务</h2>
            <p>{total > 0 ? `最近 ${projects.length} / ${total} 条` : "工作流索引"}</p>
          </div>
        </div>
        <button
          className="button button-secondary history-new-button"
          type="button"
          onClick={onNewTask}
        >
          <Plus size={15} aria-hidden="true" />
          新任务
        </button>
      </div>

      {error ? (
        <div className="history-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={onRefresh}>
            <RefreshCw size={14} aria-hidden="true" />
            重试
          </button>
        </div>
      ) : null}

      {loading && projects.length === 0 ? (
        <div className="history-empty" role="status">
          <LoaderCircle className="spin" size={20} aria-hidden="true" />
          <span>正在加载历史任务</span>
        </div>
      ) : projects.length === 0 ? (
        <div className="history-empty">
          <History size={21} aria-hidden="true" />
          <span>暂无历史任务</span>
        </div>
      ) : (
        <ul className="history-list">
          {projects.map((project) => {
            const isActive = project.thread_id === activeThreadId;
            const isSwitching = project.thread_id === switchingThreadId;
            return (
              <li key={project.id}>
                <button
                  className={`history-item${isActive ? " is-active" : ""}`}
                  type="button"
                  onClick={() => onOpenProject(project)}
                  disabled={switchingThreadId !== null}
                  aria-label={`打开历史任务：${project.topic_direction}`}
                >
                  <span className="history-item-heading">
                    <strong>{project.topic_direction}</strong>
                    {isSwitching ? (
                      <LoaderCircle
                        className="spin"
                        size={15}
                        aria-hidden="true"
                      />
                    ) : isActive ? (
                      <CheckCircle2 size={15} aria-hidden="true" />
                    ) : null}
                  </span>
                  {project.selected_topic_title ? (
                    <span className="history-topic">
                      {project.selected_topic_title}
                    </span>
                  ) : null}
                  <span className="history-meta">
                    <span>{statusLabels[project.status]}</span>
                    <span>{project.revision_count} 次修改</span>
                  </span>
                  <span className="history-time">
                    <Clock3 size={13} aria-hidden="true" />
                    {updatedAtLabel(project.updated_at)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
