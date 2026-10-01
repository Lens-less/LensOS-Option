import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { safeResearchReport } from "../../report/testFixtures";
import { ResearchSourceBar } from "./ResearchSourceBar";

describe("declared research source", () => {
  it("separates historical rereading from public collection even if conflicting live metadata arrives", () => {
    const report = structuredClone(safeResearchReport);
    report.runtime_context = { ...report.runtime_context!, replay: true, mode: "replay", live_fetch_allowed: true };
    const refresh = vi.fn();
    render(<ResearchSourceBar report={report} refreshing={false} onRefresh={refresh} />);
    expect(screen.getByText("历史快照回放")).toBeVisible();
    expect(screen.getByText(/重新读取不会采集当前行情/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "更新公开行情" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新读取快照" }));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("declares cache reuse and prevents repeated collection clicks while awaiting a response", () => {
    const report = structuredClone(safeResearchReport);
    report.runtime_context = { ...report.runtime_context!, replay: false, mode: "live", live_fetch_allowed: true };
    const refresh = vi.fn();
    const { rerender } = render(<ResearchSourceBar report={report} refreshing={false} onRefresh={refresh} />);
    expect(screen.getByText(/有效快照会复用，过期后重新采集/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "更新公开行情" }));
    rerender(<ResearchSourceBar report={report} refreshing={true} onRefresh={refresh} />);
    expect(screen.getByRole("button", { name: "正在采集与核验…" })).toBeDisabled();
    expect(refresh).toHaveBeenCalledOnce();
    expect(screen.getByText("仅研究 · NO_TRADE")).toBeVisible();
  });
});
