import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  demoMasqueradingLiveSurface,
  staleSurface,
  strategyBriefFixture,
  watchOnlyBriefFixture,
} from "../../report/strategyBriefFixtures";
import { StrategyBriefView } from "./StrategyBriefView";

const clipboardWriteText = vi.fn((_: string) => Promise.resolve());

Object.defineProperty(globalThis.navigator, "clipboard", {
  configurable: true,
  value: {
    writeText: clipboardWriteText,
  },
});

afterEach(() => {
  clipboardWriteText.mockClear();
});

describe("StrategyBriefView", () => {
  it("renders the market headline and cards", () => {
    render(<StrategyBriefView brief={strategyBriefFixture} />);

    expect(screen.getByRole("heading", { name: /BTC: 震荡/ })).toBeInTheDocument();
    expect(screen.getByText(/Bear Call Credit Spread/)).toBeInTheDocument();
    expect(screen.getByText("BTC-25SEP26-125000-C")).toBeInTheDocument();
    expect(
      screen.getByText("历史：胜率 68% · 平均净 R 0.21 · 12 个到期 cohort"),
    ).toBeInTheDocument();
  });

  it("shows watch-only labels without inventing probabilities", () => {
    render(<StrategyBriefView brief={watchOnlyBriefFixture} />);

    expect(screen.getByText("历史：探索中")).toBeInTheDocument();
    expect(screen.getByText("预测：暂不可用")).toBeInTheDocument();
  });

  it("suppresses cards on stale or masquerading surfaces", () => {
    const { rerender } = render(
      <StrategyBriefView brief={strategyBriefFixture} surface={staleSurface} />,
    );

    expect(screen.getByLabelText("NO_TRADE")).toBeInTheDocument();
    rerender(
      <StrategyBriefView
        brief={strategyBriefFixture}
        surface={demoMasqueradingLiveSurface}
      />,
    );
    expect(screen.getByLabelText("NO_TRADE")).toBeInTheDocument();
  });

  it("describes a conservative brief pause without declaring all market evidence expired", () => {
    render(<StrategyBriefView brief={strategyBriefFixture} surface={staleSurface} />);

    expect(screen.getByRole("heading", { name: "策略简报已暂停" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "市场证据已失效" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "复制组合" })).not.toBeInTheDocument();
  });

  it("keeps brief expiry distinct from a still-current publication", () => {
    render(<StrategyBriefView brief={strategyBriefFixture} surface={{
      ...staleSurface,
      freshness_status: "CURRENT",
      source_kind: "published",
      presented_as: "published",
      now_ms: Date.parse(strategyBriefFixture.market.expires_at) + 1,
    }} />);

    expect(screen.getByRole("heading", { name: "策略简报已暂停" })).toBeVisible();
    expect(screen.getByText("策略简报的有效期已过，等待重新计算。")).toBeVisible();
    expect(screen.queryByText("行情已过期，等待刷新")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "市场证据不可用" })).not.toBeInTheDocument();
  });

  it.each([staleSurface, { ...staleSurface, freshness_status: "UNAVAILABLE" as const }])(
    "withdraws current market claims and counts along with suppressed cards: $freshness_status",
    (surface) => {
      render(<StrategyBriefView brief={strategyBriefFixture} surface={surface} />);

      expect(screen.queryByRole("heading", { name: /流动性可执行/ })).not.toBeInTheDocument();
      expect(screen.getByText(/当前展示 0 张卡/)).toBeVisible();
      expect(screen.queryByText(/当前展示 1 张卡/)).not.toBeInTheDocument();
      expect(screen.queryByText(/下次更新时间/)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "复制组合" })).not.toBeInTheDocument();
    },
  );

  it("copies only via the clipboard", () => {
    render(<StrategyBriefView brief={strategyBriefFixture} />);

    fireEvent.click(screen.getAllByRole("button", { name: "复制组合" })[0]!);

    expect(clipboardWriteText).toHaveBeenCalledTimes(1);
    expect(clipboardWriteText.mock.calls.at(0)?.at(0)).toContain(
      "RESEARCH_ONLY / MANUAL REVIEW REQUIRED",
    );
  });

  it("shows explicit frozen costs and distinguishes the model budget from an absolute loss bound", () => {
    render(<StrategyBriefView brief={strategyBriefFixture} />);
    expect(screen.getByText("模型损失上限")).toBeVisible();
    expect(screen.getByText(/未来交割费可能超出预算，实际损失可能更高/)).toBeVisible();
    expect(screen.queryByText("最大亏损")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("查看成本预算与模型风险"));
    expect(screen.getByText("结算费用准备")).toBeVisible();
    expect(screen.getByText("15 USD")).toBeVisible();
    expect(screen.getByText("125350 USD")).toBeVisible();
  });

  it("offers the complete research recipe when clipboard access is denied", async () => {
    clipboardWriteText.mockRejectedValueOnce(new Error("denied"));
    render(<StrategyBriefView brief={strategyBriefFixture} />);
    fireEvent.click(screen.getByRole("button", { name: "复制组合" }));
    expect(await screen.findByText("无法访问剪贴板，请选择下方组合文本手动复制。")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "研究组合文本" })).toHaveValue(strategyBriefFixture.strategies[0].copy_recipe);
    expect(screen.getByRole("textbox", { name: "研究组合文本" })).toHaveAttribute("readonly");
  });

  it("shows an honest unavailable shell when the brief is missing", () => {
    render(<StrategyBriefView brief={null} surface={staleSurface} />);

    expect(screen.getByText(/尚未提供 `strategy_brief\.v1`/)).toBeInTheDocument();
  });
});
