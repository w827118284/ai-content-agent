import { LoaderCircle, Sparkles } from "lucide-react";
import { FormEvent, useState } from "react";

interface StartPanelProps {
  busy: boolean;
  onStart: (topicDirection: string) => Promise<void>;
}

export function StartPanel({ busy, onStart }: StartPanelProps) {
  const [topicDirection, setTopicDirection] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedDirection = topicDirection.trim();
    if (!normalizedDirection || busy) {
      return;
    }
    await onStart(normalizedDirection);
  }

  return (
    <section className="start-panel" aria-labelledby="start-title">
      <div className="section-heading">
        <span className="section-icon" aria-hidden="true">
          <Sparkles size={20} />
        </span>
        <div>
          <p className="eyebrow">新内容任务</p>
          <h2 id="start-title">创建今天的内容方向</h2>
        </div>
      </div>

      <form className="start-form" onSubmit={handleSubmit}>
        <label htmlFor="topic-direction">内容方向</label>
        <textarea
          id="topic-direction"
          value={topicDirection}
          onChange={(event) => setTopicDirection(event.target.value)}
          placeholder="请输入今天的技术内容方向"
          maxLength={200}
          rows={5}
          disabled={busy}
          required
        />
        <div className="form-footer">
          <span className="input-example">
            例如：LangGraph Human-in-the-loop 实战
          </span>
          <button
            className="button button-primary"
            type="submit"
            disabled={busy || !topicDirection.trim()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={18} aria-hidden="true" />
            ) : (
              <Sparkles size={18} aria-hidden="true" />
            )}
            {busy ? "正在生成" : "生成选题"}
          </button>
        </div>
      </form>
    </section>
  );
}
