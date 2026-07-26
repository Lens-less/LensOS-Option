import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ContractComparison } from "../report";
import { SidePanelComparisonSection } from "./SidePanelComparisonSection";

function buildComparison(
  overrides?: Partial<ContractComparison>,
): ContractComparison {
  return {
    currentRank: 2,
    totalRanked: 2,
    rankingDimensions: ["relative_value", "path_risk"],
    absoluteEvAvailable: true,
    rows: [
      {
        candidateId: "spread-b",
        label: "卖 BTC-7AUG26-73000-C / 买 BTC-7AUG26-79000-C",
        rank: 1,
        action: "RESEARCH_ONLY",
        ev: 40,
        executableCreditUsdc: 900,
        rankingScore: 5.1,
        deltaVsCurrent: 27.5,
        isCurrent: false,
        primaryInstrument: "BTC-7AUG26-73000-C",
      },
      {
        candidateId: "spread-a",
        label: "卖 BTC-7AUG26-71000-C / 买 BTC-7AUG26-77000-C",
        rank: 2,
        action: "REVIEW",
        ev: 12.5,
        executableCreditUsdc: 720,
        rankingScore: 3.2,
        deltaVsCurrent: 0,
        isCurrent: true,
        primaryInstrument: "BTC-7AUG26-71000-C",
      },
    ],
    ...overrides,
  };
}

describe("SidePanelComparisonSection", () => {
  it("renders nothing when there is no comparison data", () => {
    const { container } = render(
      <SidePanelComparisonSection
        comparison={null}
        onSelectInstrument={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the current rank line, live-region, and signed deltas for the top alternative", () => {
    render(
      <SidePanelComparisonSection
        comparison={buildComparison()}
        onSelectInstrument={vi.fn()}
      />,
    );

    const rankLine = screen.getByText("当前合约排名 第 2 / 2");
    expect(rankLine).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("相对价值 +1.9 IV pts")).toBeInTheDocument();
    expect(screen.getByText("税费后期望值 +27.5 USDC")).toBeInTheDocument();
    expect(screen.getByText("参考信用 +180.0 USDC")).toBeInTheDocument();
  });

  it("re-targets the panel at a candidate's primary instrument on click, never an order", () => {
    const onSelectInstrument = vi.fn();
    render(
      <SidePanelComparisonSection
        comparison={buildComparison()}
        onSelectInstrument={onSelectInstrument}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /BTC-7AUG26-73000-C/ }));
    expect(onSelectInstrument).toHaveBeenCalledWith("BTC-7AUG26-73000-C");
  });

  it("promotes the ranked shortlist as primary content when no current contract is selected", () => {
    render(
      <SidePanelComparisonSection
        comparison={buildComparison({
          currentRank: null,
          rows: buildComparison().rows.map((row) => ({
            ...row,
            isCurrent: false,
            deltaVsCurrent: null,
          })),
        })}
        onSelectInstrument={vi.fn()}
      />,
    );

    expect(
      screen.getByText("尚未定位当前合约 · 本链共 2 个候选"),
    ).toBeInTheDocument();
    const summary = screen.getByText(
      "查看全部 2 个候选（研究排名，非下单指令）",
    );
    expect(summary.closest("details")).toHaveAttribute("open");
  });

  it("carries no order, quantity, or execution semantics", () => {
    const { container } = render(
      <SidePanelComparisonSection
        comparison={buildComparison()}
        onSelectInstrument={vi.fn()}
      />,
    );

    // Every interactive control is a plain research-navigation button, never
    // a form that could submit an order.
    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(container.querySelector("form")).toBeNull();
    for (const button of Array.from(container.querySelectorAll("button"))) {
      expect(button).toHaveAttribute("type", "button");
    }

    const text = container.textContent ?? "";
    for (const forbidden of [
      "点击下单",
      "提交订单",
      "委托",
      "购买",
      "出售",
      "执行交易",
      "数量",
      "手数",
      "Place order",
      "Submit order",
    ]) {
      expect(text).not.toContain(forbidden);
    }
    // The disclaimer explicitly denies order semantics; it must never read
    // as an instruction to place one.
    expect(text).toContain("非下单指令");
  });
});
