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
    expect(screen.getByText("BTC-30AUG26-125000-C")).toBeInTheDocument();
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

  it("copies only via the clipboard", () => {
    render(<StrategyBriefView brief={strategyBriefFixture} />);

    fireEvent.click(screen.getAllByRole("button", { name: "复制组合" })[0]!);

    expect(clipboardWriteText).toHaveBeenCalledTimes(1);
    expect(clipboardWriteText.mock.calls.at(0)?.at(0)).toContain(
      "RESEARCH_ONLY / MANUAL REVIEW REQUIRED",
    );
  });

  it("shows an honest unavailable shell when the brief is missing", () => {
    render(<StrategyBriefView brief={null} surface={staleSurface} />);

    expect(screen.getByText(/尚未提供 `strategy_brief\.v1`/)).toBeInTheDocument();
  });
});
