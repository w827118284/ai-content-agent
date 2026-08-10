import {
  CheckCircle2,
  FileCheck2,
  ImageOff,
  RotateCcw,
} from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";

interface ResultViewProps {
  selectedTopic: string;
  articleContent: string;
  revisionCount: number;
  visualPoints: string[];
  imageUrls: string[];
  onNewTask: () => void;
}

interface VisualCardProps {
  point: string;
  imageUrl: string | undefined;
  index: number;
}

function VisualCard({ point, imageUrl, index }: VisualCardProps) {
  const [imageFailed, setImageFailed] = useState(false);

  return (
    <article className="visual-card">
      <div className="visual-media">
        {imageUrl && !imageFailed ? (
          <img
            src={imageUrl}
            alt={`知识卡片 ${index + 1}`}
            onError={() => setImageFailed(true)}
          />
        ) : (
          <div className="image-fallback">
            <ImageOff size={28} aria-hidden="true" />
            <span>Mock Image</span>
          </div>
        )}
      </div>
      <div className="visual-copy">
        <span>知识点 {String(index + 1).padStart(2, "0")}</span>
        <p>{point}</p>
      </div>
    </article>
  );
}

export function ResultView({
  selectedTopic,
  articleContent,
  revisionCount,
  visualPoints,
  imageUrls,
  onNewTask,
}: ResultViewProps) {
  return (
    <section aria-labelledby="result-title">
      <div className="result-header">
        <div className="section-heading">
          <span className="section-icon section-icon-success" aria-hidden="true">
            <FileCheck2 size={20} />
          </span>
          <div>
            <p className="eyebrow">任务完成</p>
            <h2 id="result-title">{selectedTopic}</h2>
          </div>
        </div>
        <div className="result-meta">
          <span>
            <CheckCircle2 size={16} aria-hidden="true" /> 已通过审核
          </span>
          <span>{revisionCount} 次修改</span>
        </div>
      </div>

      <article className="markdown-body result-article">
        <ReactMarkdown>{articleContent}</ReactMarkdown>
      </article>

      <section className="visual-section" aria-labelledby="visual-title">
        <div className="subsection-heading">
          <div>
            <p className="eyebrow">小红书知识卡片</p>
            <h3 id="visual-title">视觉知识点</h3>
          </div>
          <span>{visualPoints.length} 张</span>
        </div>
        <div className="visual-grid">
          {visualPoints.map((point, index) => (
            <VisualCard
              key={`${index}-${point}`}
              point={point}
              imageUrl={imageUrls[index]}
              index={index}
            />
          ))}
        </div>
      </section>

      <div className="new-task-row">
        <button
          className="button button-secondary"
          type="button"
          onClick={onNewTask}
        >
          <RotateCcw size={18} aria-hidden="true" />
          开始新任务
        </button>
      </div>
    </section>
  );
}
