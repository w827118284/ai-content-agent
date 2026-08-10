export type WorkflowStatus =
  | "planning_topics"
  | "waiting_topic_selection"
  | "drafting"
  | "waiting_article_review"
  | "rewriting"
  | "extracting_visuals"
  | "generating_images"
  | "completed";

export type ReviewStatus = "pending" | "rejected" | "approved" | null;

export interface TopicOption {
  id: string;
  title: string;
}

export interface AgentState {
  topic_direction: string;
  generated_topics: TopicOption[];
  selected_topic: string | null;
  article_content: string | null;
  review_feedback: string | null;
  review_status: ReviewStatus;
  visual_points: string[];
  image_urls: string[];
  status: WorkflowStatus;
  revision_count: number;
}

export interface TopicSelectionInterrupt {
  type: "topic_selection";
  message: string;
  topics: TopicOption[];
}

export interface ArticleReviewInterrupt {
  type: "article_review";
  message: string;
  article_content: string | null;
  revision_count: number;
  actions: Array<"approve" | "reject">;
}

export type InterruptPayload =
  | TopicSelectionInterrupt
  | ArticleReviewInterrupt;

export interface WorkflowResponse {
  thread_id: string;
  status: WorkflowStatus;
  is_completed: boolean;
  interrupt: InterruptPayload | null;
  state: AgentState;
}

export interface ContentProjectSummary {
  id: string;
  thread_id: string;
  topic_direction: string;
  selected_topic_title: string | null;
  status: WorkflowStatus;
  revision_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectListResponse {
  items: ContentProjectSummary[];
  total: number;
  limit: number;
  offset: number;
}

export type WorkflowResumeRequest =
  | {
      action: "select_topic";
      data: { topic_id: string };
    }
  | {
      action: "reject";
      data: { feedback: string };
    }
  | {
      action: "approve";
    };
