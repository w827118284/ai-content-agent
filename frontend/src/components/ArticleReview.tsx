import {
  CheckCircle2,
  FileText,
  LoaderCircle,
  MessageSquareText,
  Send,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";

interface ArticleReviewProps {
  selectedTopic: string;
  articleContent: string;
  revisionCount: number;
  busy: boolean;
  onApprove: () => Promise<void>;
  onReject: (feedback: string) => Promise<void>;
}

export function ArticleReview({
  selectedTopic,
  articleContent,
  revisionCount,
  busy,
  onApprove,
  onReject,
}: ArticleReviewProps) {
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  useEffect(() => {
    setShowFeedback(false);
    setFeedback("");
    setFeedbackError(null);
  }, [revisionCount]);

  async function handleReject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedFeedback = feedback.trim();
    if (!normalizedFeedback) {
      setFeedbackError("请填写修改意见。");
      return;
    }
    setFeedbackError(null);
    await onReject(normalizedFeedback);
  }

  return (
    <section aria-labelledby="article-review-title">
      <div className="review-header">
        <div className="section-heading">
          <span className="section-icon" aria-hidden="true">
            <FileText size={20} />
          </span>
          <div>
            <p className="eyebrow">文章审核</p>
            <h2 id="article-review-title">{selectedTopic}</h2>
          </div>
        </div>
        <span className="revision-badge">第 {revisionCount} 次修改</span>
      </div>

      <article className="markdown-body">
        <ReactMarkdown>{articleContent}</ReactMarkdown>
      </article>

      <div className="review-actions">
        <button
          className="button button-success"
          type="button"
          disabled={busy}
          onClick={onApprove}
        >
          {busy ? (
            <LoaderCircle className="spin" size={18} aria-hidden="true" />
          ) : (
            <CheckCircle2 size={18} aria-hidden="true" />
          )}
          通过
        </button>
        <button
          className="button button-secondary"
          type="button"
          disabled={busy}
          onClick={() => {
            setShowFeedback((visible) => !visible);
            setFeedbackError(null);
          }}
        >
          {showFeedback ? (
            <X size={18} aria-hidden="true" />
          ) : (
            <MessageSquareText size={18} aria-hidden="true" />
          )}
          {showFeedback ? "取消修改" : "要求修改"}
        </button>
      </div>

      {showFeedback ? (
        <form className="feedback-form" onSubmit={handleReject}>
          <label htmlFor="review-feedback">修改意见</label>
          <textarea
            id="review-feedback"
            value={feedback}
            onChange={(event) => {
              setFeedback(event.target.value);
              if (feedbackError) {
                setFeedbackError(null);
              }
            }}
            placeholder="增加实际代码示例，减少背景介绍"
            rows={4}
            disabled={busy}
            aria-describedby={feedbackError ? "feedback-error" : undefined}
          />
          {feedbackError ? (
            <p className="field-error" id="feedback-error" role="alert">
              {feedbackError}
            </p>
          ) : null}
          <div className="feedback-submit-row">
            <button
              className="button button-primary"
              type="submit"
              disabled={busy || !feedback.trim()}
            >
              {busy ? (
                <LoaderCircle className="spin" size={18} aria-hidden="true" />
              ) : (
                <Send size={18} aria-hidden="true" />
              )}
              提交修改意见
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
