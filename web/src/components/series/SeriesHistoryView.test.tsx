import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import demoSeries from "../../../../crypto_options_report/resources/demo-series-history.json";
import { SeriesHistoryView } from "./SeriesHistoryView";

describe("series evidence progress", () => {
  it("shows the bundled capture and its actual missing dates before a series is measurable", () => {
    render(<SeriesHistoryView artifact={demoSeries} />);

    const progress = screen.getByRole("region", { name: "序列验证进度" });
    expect(within(progress).getByRole("progressbar", { name: "有效采集日" })).toHaveAttribute("value", "1");
    expect(within(progress).getByRole("progressbar", { name: "有效采集日" })).toHaveAttribute("max", "3");
    expect(within(progress).getByText("2026-07-07")).toBeVisible();
    expect(within(progress).getByText(/还需 2 个有效采集日/)).toBeVisible();
    expect(within(progress).getByText(/继续采集同一合约/)).toBeVisible();
    expect(screen.queryByRole("img", { name: /残差/ })).not.toBeInTheDocument();
  });

  it("distinguishes an unavailable artifact from a measured shortage without inventing zero progress", () => {
    render(<SeriesHistoryView artifact={{ status: "not_configured", detail: "读取产物超时，已停止展示；请刷新后重试。" }} />);

    expect(screen.getByRole("heading", { name: "序列产物尚不可用" })).toBeVisible();
    expect(screen.getByText(/读取产物超时/)).toBeVisible();
    expect(screen.getByText(/重新读取当前报告/)).toBeVisible();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByText("序列还不够长")).not.toBeInTheDocument();
    expect(screen.queryByText(/已有采集，/)).not.toBeInTheDocument();
  });

  it("lets keyboard users choose a measured contract and read actual zero values without inventing missing dates", () => {
    render(<SeriesHistoryView artifact={{ status: "measured", capture_dates: ["2026-07-07", "2026-07-08"], capture_count: 2, instrument_count: 1,
      instruments: [{ instrument_name: "BTC-25JUL26-60000-C", points: [
        { date: "2026-07-07", present: true, residual_z: 0 },
        { date: "2026-07-08", present: false },
      ] }] }} />);
    const select = screen.getByRole("combobox", { name: "选择合约查看逐日读数" });
    select.focus();
    fireEvent.change(select, { target: { value: "BTC-25JUL26-60000-C" } });
    expect(select).toHaveFocus();
    expect(screen.getByRole("link", { name: "跳到该合约的逐日读数" })).toHaveAttribute("href", "#series-instrument-detail");
    const table = screen.getByRole("region", { name: "合约逐日读数" });
    expect(within(table).getByRole("cell", { name: "±0" })).toBeVisible();
    expect(within(table).queryByText("2026-07-08")).not.toBeInTheDocument();
  });
});
