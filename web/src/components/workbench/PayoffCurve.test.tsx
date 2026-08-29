import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PayoffCurve } from "./PayoffCurve";

describe("PayoffCurve", () => {
  it("shows an explicit unavailable state instead of guessing geometry", () => {
    render(
      <PayoffCurve
        creditUsdc={null}
        longStrikeUsdc={null}
        shortStrikeUsdc={null}
        spotUsdc={65_000}
        structureKind="naked"
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "缺少行权价或实得信用数据",
    );
  });

  it("withholds the curve when the strike order implies a negative width", () => {
    render(
      <PayoffCurve
        creditUsdc={400}
        longStrikeUsdc={66_000}
        shortStrikeUsdc={71_000}
        spotUsdc={65_000}
        structureKind="spread"
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "无法用两腿上行结构表达",
    );
  });

  it("draws a naked short call with an honest unbounded loss tail", () => {
    render(
      <PayoffCurve
        creditUsdc={400}
        longStrikeUsdc={null}
        shortStrikeUsdc={71_000}
        spotUsdc={65_000}
        structureKind="naked"
      />,
    );
    expect(screen.getByText("亏损无上限（标的继续上涨）")).toBeInTheDocument();
    expect(screen.getByText("无上限")).toBeInTheDocument();
    // A short call's breakeven is strike + credit.
    expect(screen.getByText("$71,400")).toBeInTheDocument();
    expect(screen.getByText("$400")).toBeInTheDocument();
  });

  it("draws a call credit spread with a finite, capped maximum loss", () => {
    render(
      <PayoffCurve
        creditUsdc={162.65}
        longStrikeUsdc={77_000}
        shortStrikeUsdc={71_000}
        spotUsdc={65_000}
        structureKind="spread"
      />,
    );
    expect(
      screen.queryByText("亏损无上限（标的继续上涨）"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("无上限")).not.toBeInTheDocument();
    // max loss = width (6000) - credit (162.65) = 5837.35, shown negative.
    expect(screen.getByText("-$5,837")).toBeInTheDocument();
  });

  it("marks the current spot price when it falls inside the chart domain", () => {
    render(
      <PayoffCurve
        creditUsdc={400}
        longStrikeUsdc={null}
        shortStrikeUsdc={71_000}
        spotUsdc={70_000}
        structureKind="naked"
      />,
    );
    expect(screen.getByText("现价")).toBeInTheDocument();
    // "盈亏平衡" appears twice: once as the chart's inline marker label, and
    // once as the summary table's row label.
    expect(screen.getAllByText("盈亏平衡").length).toBeGreaterThanOrEqual(2);
  });

  it("omits the spot marker when no spot price is available", () => {
    render(
      <PayoffCurve
        creditUsdc={400}
        longStrikeUsdc={null}
        shortStrikeUsdc={71_000}
        spotUsdc={null}
        structureKind="naked"
      />,
    );
    expect(screen.queryByText("现价")).not.toBeInTheDocument();
  });
});
