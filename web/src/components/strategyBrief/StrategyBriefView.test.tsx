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
    expect(screen.getByText("Bid 1200 / Ask 1250 USD · quote_currency")).toBeVisible();
    expect(screen.getByText("查看报价时间与研究来源")).toBeVisible();
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
    expect(screen.queryByRole("button", { name: "复制研究复核" })).not.toBeInTheDocument();
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
      expect(screen.queryByRole("button", { name: "复制研究复核" })).not.toBeInTheDocument();
    },
  );

  it("copies a review record with exact quotes, source, clock and immutable identity", () => {
    render(<StrategyBriefView brief={strategyBriefFixture} />);

    fireEvent.click(screen.getAllByRole("button", { name: "复制研究复核" })[0]!);

    expect(clipboardWriteText).toHaveBeenCalledTimes(1);
    expect(clipboardWriteText.mock.calls.at(0)?.at(0)).toContain(
      "RESEARCH_ONLY / MANUAL REVIEW REQUIRED",
    );
    const copy = clipboardWriteText.mock.calls.at(0)?.at(0);
    for (const expected of [
      `BRIEF ID: ${strategyBriefFixture.brief_id}`,
      `RECOMMENDATION ID: ${strategyBriefFixture.strategies[0].recommendation_id}`,
      "ANALYSIS RUN: analysis:fixture",
      "SOURCE: Live API snapshot (live; live)",
      "EVALUATED AT: 2026-08-30T14:30:05+08:00",
      "CONTRACT EXPIRY: 2026-09-25",
      "BID 1200 / ASK 1250 / USD (quote_currency) / OBSERVED AT 2026-08-30T14:30:04+08:00",
      "BID 700 / ASK 800 / USD (quote_currency) / OBSERVED AT 2026-08-30T14:30:05+08:00",
      "VALID UNTIL:",
      "重新取得正的、同步的双边报价",
      "execution_allowed=false",
    ]) {
      expect(copy).toContain(expected);
    }
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
    fireEvent.click(screen.getByRole("button", { name: "复制研究复核" }));
    expect(await screen.findByText("无法访问剪贴板，请选择下方复核文本手动复制。")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "研究复核文本" })).toHaveValue(clipboardWriteText.mock.calls.at(0)?.at(0));
    expect(screen.getByRole("textbox", { name: "研究复核文本" })).toHaveAttribute("readonly");
  });

  it("copies the current rejection while withholding expired strategy legs", () => {
    render(<StrategyBriefView brief={strategyBriefFixture} surface={staleSurface} />);
    fireEvent.click(screen.getByRole("button", { name: "复制拒绝原因" }));
    const copy = clipboardWriteText.mock.calls.at(0)?.at(0);
    for (const expected of [
      "STATUS: NO_TRADE / execution_allowed=false",
      `BRIEF ID: ${strategyBriefFixture.brief_id}`,
      "ANALYSIS RUN: analysis:fixture",
      "SOURCE: Stale live snapshot (live; live)",
      "SOURCE FRESHNESS: STALE",
      `MARKET AS OF: ${strategyBriefFixture.market.as_of}`,
      `EVALUATED AT: ${strategyBriefFixture.generated_at}`,
      `SNAPSHOT EXPIRES AT: ${strategyBriefFixture.market.expires_at}`,
      "CURRENT QUALIFICATION: PAUSED",
      "快照判定仅作为历史记录",
      "策略简报的有效期已过，等待重新计算。",
      "RECHECK:",
    ]) expect(copy).toContain(expected);
    expect(copy).not.toContain("STATUS: WATCH");
    expect(copy).not.toContain("SELL");
    expect(copy).not.toContain("BUY");
    expect(copy).not.toContain("LEG QUOTE:");
    expect(copy).not.toContain("MIN NET CREDIT:");
    expect(screen.queryByRole("button", { name: "复制研究复核" })).not.toBeInTheDocument();
  });

  it("makes every displayed rejection available and retains fallback text", async () => {
    clipboardWriteText.mockRejectedValueOnce(new Error("denied"));
    render(<StrategyBriefView brief={strategyBriefFixture} surface={{
      ...demoMasqueradingLiveSurface,
      freshness_status: "STALE",
      now_ms: staleSurface.now_ms,
    }} />);
    const disclosure = screen.getByText("全部拒绝原因（3）");
    fireEvent.click(disclosure);
    expect(disclosure.closest("details")?.querySelectorAll("li")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "复制拒绝原因" }));
    expect(await screen.findByText("无法访问剪贴板，请选择下方复核文本手动复制。")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "研究复核文本" })).toHaveValue(clipboardWriteText.mock.calls.at(0)?.at(0));
    expect(screen.getByRole("textbox", { name: "研究复核文本" })).toHaveAttribute("readonly");
  });

  it("shows an honest unavailable shell when the brief is missing", () => {
    render(<StrategyBriefView brief={null} surface={staleSurface} />);

    expect(screen.getByText(/尚未提供 `strategy_brief\.v1`/)).toBeInTheDocument();
  });
});
