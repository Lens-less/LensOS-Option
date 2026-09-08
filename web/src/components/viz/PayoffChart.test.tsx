import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PayoffChart, type PayoffSeries } from "./PayoffChart";

const context: PayoffSeries[] = [
  { key: "a", label: "第一到期日", emphasis: "context", points: [{ spot: 90, pnl: -10 }, { spot: 110, pnl: 10 }] },
  { key: "b", label: "第二到期日", emphasis: "context", points: [{ spot: 90, pnl: 5 }, { spot: 110, pnl: -5 }] },
];

describe("payoff chart evidence labels", () => {
  it("does not claim a combined curve or a combined hover readout for separate expiry members", () => {
    render(<PayoffChart ariaLabel="各成员损益" series={context} formatMoney={String} />);
    expect(screen.getByRole("img", { name: "各成员损益" })).toBeVisible();
    expect(screen.queryByText("组合")).not.toBeInTheDocument();
    expect(screen.queryByText(/在图上移动/)).not.toBeInTheDocument();
    expect(screen.getByText("单个成员")).toBeVisible();
  });
});
