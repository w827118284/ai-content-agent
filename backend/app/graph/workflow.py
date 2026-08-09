from typing import Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    extract_visuals,
    generate_images,
    human_review,
    human_select_topic,
    plan_topics,
    write_draft,
)
from app.graph.state import AgentState


def route_after_review(state: AgentState) -> Literal["rejected", "approved"]:
    review_status = state["review_status"]
    if review_status == "rejected":
        return "rejected"
    if review_status == "approved":
        return "approved"
    raise ValueError(f"human_review returned invalid review_status: {review_status!r}")


workflow_builder = StateGraph(AgentState)
workflow_builder.add_node("plan_topics", plan_topics)
workflow_builder.add_node("human_select_topic", human_select_topic)
workflow_builder.add_node("write_draft", write_draft)
workflow_builder.add_node("human_review", human_review)
workflow_builder.add_node("extract_visuals", extract_visuals)
workflow_builder.add_node("generate_images", generate_images)

workflow_builder.add_edge(START, "plan_topics")
workflow_builder.add_edge("plan_topics", "human_select_topic")
workflow_builder.add_edge("human_select_topic", "write_draft")
workflow_builder.add_edge("write_draft", "human_review")
workflow_builder.add_conditional_edges(
    "human_review",
    route_after_review,
    {
        "rejected": "write_draft",
        "approved": "extract_visuals",
    },
)
workflow_builder.add_edge("extract_visuals", "generate_images")
workflow_builder.add_edge("generate_images", END)

# These process-wide instances must be reused for every request in phase one.
checkpointer = InMemorySaver()
content_workflow = workflow_builder.compile(checkpointer=checkpointer)
