import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DemoGuide } from "./DemoGuide";

describe("offline learning guide", () => {
  it("lets a newcomer learn a structure, explore loss and inspect evidence without authorizing research", () => {
    render(<DemoGuide />);

    expect(screen.getByRole("heading", { name: "离线学习导览" })).toBeVisible();
    expect(screen.getByText(/教学示例，不是当前行情/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /铁鹰双边价差/ }));
    fireEvent.click(screen.getByRole("button", { name: "查看风险与收益" }));

    const risk = screen.getByTestId("demo-risk-step");
    expect(within(risk).getByText("87 / 113")).toBeVisible();
    fireEvent.change(screen.getByRole("slider", { name: "示例到期价格" }), {
      target: { value: "60" },
    });
    expect(screen.getByLabelText("示例到期损益")).toHaveTextContent("−7 点");
    fireEvent.change(screen.getByRole("slider", { name: "示例到期价格" }), {
      target: { value: "100" },
    });
    expect(screen.getByLabelText("示例到期损益")).toHaveTextContent("+3 点");

    fireEvent.click(screen.getByRole("button", { name: "查看证据与限制" }));
    const evidence = screen.getByTestId("demo-evidence-step");
    expect(within(evidence).getByText("胜率仍然未知")).toBeVisible();
    expect(within(evidence).getByText(/费用、滑点和提前平仓/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "完成导览" }));
    expect(screen.getByRole("heading", { name: "你已完成导览" })).toBeVisible();
    expect(screen.getByRole("link", { name: "查看真实快照" })).toHaveAttribute("href", "./index.html");
    expect(screen.queryByRole("button", { name: /复制组合|提交订单/ })).not.toBeInTheDocument();
  });

  it.each([
    [/牛市看跌价差/, "60", "−8 点", "140", "+2 点"],
    [/熊市看涨价差/, "60", "+2.5 点", "140", "−7.5 点"],
  ])("shows bounded terminal payoff for %s", (name, firstPrice, firstPayoff, secondPrice, secondPayoff) => {
    render(<DemoGuide />);
    fireEvent.click(screen.getByRole("button", { name }));
    fireEvent.click(screen.getByRole("button", { name: "查看风险与收益" }));
    const slider = screen.getByRole("slider", { name: "示例到期价格" });
    fireEvent.change(slider, { target: { value: firstPrice } });
    expect(screen.getByLabelText("示例到期损益")).toHaveTextContent(firstPayoff);
    fireEvent.change(slider, { target: { value: secondPrice } });
    expect(screen.getByLabelText("示例到期损益")).toHaveTextContent(secondPayoff);
  });
});
