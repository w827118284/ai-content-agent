import { Check, Circle, LoaderCircle } from "lucide-react";

import type { WorkflowStatus } from "../types/workflow";

const steps = [
  "生成选题",
  "人工选题",
  "生成文章",
  "人工审核",
  "提炼视觉点",
  "生成图片",
  "完成",
];

const activeStepByStatus: Record<WorkflowStatus, number> = {
  planning_topics: 0,
  waiting_topic_selection: 1,
  drafting: 2,
  waiting_article_review: 3,
  rewriting: 2,
  extracting_visuals: 4,
  generating_images: 5,
  completed: 6,
};

interface WorkflowProgressProps {
  status: WorkflowStatus;
}

export function WorkflowProgress({ status }: WorkflowProgressProps) {
  const activeStep = activeStepByStatus[status];

  return (
    <nav className="progress-panel" aria-label="工作流进度">
      <p className="progress-title">工作流进度</p>
      <ol className="progress-list">
        {steps.map((step, index) => {
          const completed = status === "completed" || index < activeStep;
          const active = !completed && index === activeStep;

          return (
            <li
              className={`progress-step${completed ? " is-complete" : ""}${
                active ? " is-active" : ""
              }`}
              key={step}
              aria-current={active ? "step" : undefined}
            >
              <span className="progress-marker" aria-hidden="true">
                {completed ? (
                  <Check size={15} />
                ) : active ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Circle size={12} />
                )}
              </span>
              <span>{step}</span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
