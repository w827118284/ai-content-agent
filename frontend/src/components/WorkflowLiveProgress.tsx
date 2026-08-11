import { Check, LoaderCircle } from "lucide-react";

import type { WorkflowProgressEvent } from "../types/workflow";

interface WorkflowLiveProgressProps {
  events: WorkflowProgressEvent[];
  active: boolean;
}

export function WorkflowLiveProgress({
  events,
  active,
}: WorkflowLiveProgressProps) {
  if (!active && events.length === 0) {
    return null;
  }

  return (
    <section className="live-progress" aria-live="polite" aria-label="实时执行进度">
      <div className="live-progress-heading">
        {active ? (
          <LoaderCircle className="spin" size={18} aria-hidden="true" />
        ) : (
          <Check size={18} aria-hidden="true" />
        )}
        <strong>{active ? "AI 正在处理" : "本轮执行已结束"}</strong>
      </div>
      {events.length > 0 ? (
        <ol className="live-progress-list">
          {events.map((event, index) => (
            <li key={`${event.node}-${index}`}>
              <Check size={15} aria-hidden="true" />
              <span>{event.message}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
