import { ArrowRight, ListChecks, LoaderCircle } from "lucide-react";

import type { TopicOption } from "../types/workflow";

interface TopicSelectionProps {
  topics: TopicOption[];
  busy: boolean;
  onSelect: (topicId: string) => Promise<void>;
}

export function TopicSelection({
  topics,
  busy,
  onSelect,
}: TopicSelectionProps) {
  return (
    <section aria-labelledby="topic-selection-title">
      <div className="section-heading section-heading-spaced">
        <span className="section-icon" aria-hidden="true">
          <ListChecks size={20} />
        </span>
        <div>
          <p className="eyebrow">人工选题</p>
          <h2 id="topic-selection-title">选择一个本次要创作的选题</h2>
        </div>
      </div>

      <div className="topic-grid">
        {topics.map((topic, index) => (
          <article className="topic-card" key={topic.id}>
            <span className="topic-number">
              {String(index + 1).padStart(2, "0")}
            </span>
            <h3>{topic.title}</h3>
            <button
              className="button button-secondary topic-action"
              type="button"
              disabled={busy}
              onClick={() => onSelect(topic.id)}
              aria-label={`选择选题：${topic.title}`}
            >
              {busy ? (
                <LoaderCircle className="spin" size={17} aria-hidden="true" />
              ) : (
                <ArrowRight size={17} aria-hidden="true" />
              )}
              选择
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}
