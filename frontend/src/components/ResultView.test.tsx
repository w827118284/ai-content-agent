import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ResultView } from "./ResultView";


describe("ResultView images", () => {
  it("shows a loading state and reveals a loaded real image", () => {
    render(
      <ResultView
        selectedTopic="LangGraph 图片工作流"
        articleContent="# 已审核文章"
        revisionCount={0}
        visualPoints={["知识点一"]}
        imageUrls={["https://images.example.test/one.jpeg"]}
        onNewTask={vi.fn()}
      />,
    );

    const card = screen.getByText("知识点一").closest("article");
    expect(card).not.toBeNull();
    expect(within(card!).getByText("图片加载中")).toBeInTheDocument();

    const image = within(card!).getByRole("img", { name: "知识卡片 1" });
    fireEvent.load(image);

    expect(within(card!).queryByText("图片加载中")).not.toBeInTheDocument();
    expect(image).not.toHaveClass("is-loading");
  });

  it("shows a safe fallback when a real image cannot load", () => {
    render(
      <ResultView
        selectedTopic="LangGraph 图片工作流"
        articleContent="# 已审核文章"
        revisionCount={0}
        visualPoints={["知识点一"]}
        imageUrls={["https://images.example.test/broken.jpeg"]}
        onNewTask={vi.fn()}
      />,
    );

    fireEvent.error(screen.getByRole("img", { name: "知识卡片 1" }));

    expect(screen.getByText("图片暂不可用")).toBeInTheDocument();
  });
});
