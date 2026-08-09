from app.graph.state import TopicOption


class MockLLMService:
    async def plan_topics(self, topic_direction: str) -> list[TopicOption]:
        direction = topic_direction.strip()
        titles = [
            f"{direction}：从零搭建可恢复工作流",
            f"{direction}：Human-in-the-loop 核心机制",
            f"{direction}：状态设计与节点职责拆解",
            f"{direction}：Reject 重写循环实战",
            f"{direction}：从 Mock 到可运行 Demo",
        ]
        return [
            {"id": f"topic_{index}", "title": title}
            for index, title in enumerate(titles, start=1)
        ]

    async def write_article(
        self,
        *,
        topic_direction: str,
        selected_topic: str,
        previous_article: str | None,
        feedback: str | None,
        revision_count: int,
    ) -> str:
        revision_prefix = ""
        revision_section = ""
        if feedback:
            revision_prefix = f"【根据修改意见重新生成：{feedback}】\n\n"
            revision_section = (
                "\n## 本轮修改落实\n\n"
                f"本次第 {revision_count} 次重写围绕“{feedback}”补充具体说明，"
                "并压缩重复的背景描述。\n"
            )

        previous_context = (
            "这是在上一版文章基础上的定向重写。"
            if previous_article
            else "这是围绕所选主题生成的第一版技术文章。"
        )

        return (
            f"{revision_prefix}# {selected_topic}\n\n"
            f"> 内容方向：{topic_direction}  \n"
            f"> 版本：{revision_count + 1}\n\n"
            "## 为什么需要工作流编排\n\n"
            "内容生产不是一次模型调用，而是选题、写作、审核、重写和视觉提炼组成的状态流程。"
            f"{previous_context}\n\n"
            "## 核心实现\n\n"
            "LangGraph 使用 StateGraph 注册节点，通过 Checkpointer 保存每一步状态。"
            "人工节点调用 `interrupt()` 暂停，服务收到用户决定后使用 "
            "`Command(resume=...)` 从同一个 thread 继续执行。\n\n"
            "```python\n"
            "result = await graph.ainvoke(\n"
            "    Command(resume={\"action\": \"approve\"}),\n"
            "    config={\"configurable\": {\"thread_id\": thread_id}},\n"
            ")\n"
            "```\n\n"
            "## Reject 如何形成闭环\n\n"
            "审核节点只写入 `review_status` 和修改意见。conditional edge 根据审核结果，"
            "将 rejected 路由回写作节点，将 approved 路由到视觉知识点提炼节点。"
            f"{revision_section}\n"
            "## 小结\n\n"
            "核心价值不是让模型自由行动，而是让每次人工决定都能被记录、恢复并进入确定的下一步。"
        )

    async def extract_visual_points(
        self,
        *,
        selected_topic: str,
        article_content: str,
    ) -> list[str]:
        article_length = len(article_content)
        return [
            f"{selected_topic} 的端到端状态流转",
            "interrupt 与 Command(resume=...) 的恢复机制",
            "thread_id 与 InMemorySaver 的 checkpoint 关系",
            "Reject conditional edge 与 revision_count 循环",
            f"最终技术文章结构概览（约 {article_length} 字符）",
        ]
