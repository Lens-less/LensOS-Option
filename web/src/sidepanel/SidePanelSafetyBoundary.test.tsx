import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SidePanelRuntime } from "../extension/runtime";
import { buildLoadedReport, safeResearchReport } from "../report/testFixtures";
import type { LoadedReport } from "../transport";
import { SidePanelApp } from "./SidePanelApp";

function buildRuntime(
  overrides: Partial<SidePanelRuntime> = {},
): SidePanelRuntime {
  return {
    getEngineOrigin: vi.fn().mockResolvedValue("http://127.0.0.1:8000"),
    setEngineOrigin: vi.fn().mockResolvedValue("http://127.0.0.1:8000"),
    getContext: vi.fn().mockResolvedValue(null),
    getReport: vi.fn().mockResolvedValue(
      buildLoadedReport({
        report: safeResearchReport,
        receivedAtMs: Date.parse("2026-07-25T08:00:10Z"),
      }),
    ),
    getCachedReport: vi.fn().mockResolvedValue(null),
    getEvidenceUrl: vi
      .fn()
      .mockImplementation((origin: string) => `${origin}/evidence/`),
    ...overrides,
  };
}

function expectSafetyBoundary(): void {
  expect(screen.getByText("RESEARCH_ONLY")).toBeInTheDocument();
  expect(screen.getByText("NO_TRADE")).toBeInTheDocument();
}

describe("SidePanelApp safety boundary", () => {
  it("keeps RESEARCH_ONLY and NO_TRADE visible while loading", () => {
    const getReport = vi
      .fn()
      .mockImplementation(() => new Promise<LoadedReport>(() => undefined));
    render(<SidePanelApp runtime={buildRuntime({ getReport })} />);

    expectSafetyBoundary();
  });

  it("keeps RESEARCH_ONLY and NO_TRADE visible with a ready report", async () => {
    render(<SidePanelApp runtime={buildRuntime()} />);

    await screen.findByText("完整两腿");
    expectSafetyBoundary();
    expect(screen.getByText(/风险与退出为未校准研究模板/)).toHaveTextContent(
      "NO_TRADE",
    );
  });

  it("keeps RESEARCH_ONLY and NO_TRADE visible after validation failure", async () => {
    const getReport = vi
      .fn()
      .mockRejectedValue(new Error("research report safety boundary rejected"));
    render(<SidePanelApp runtime={buildRuntime({ getReport })} />);

    await screen.findByText("报告校验失败");
    expectSafetyBoundary();
  });

  it("keeps RESEARCH_ONLY and NO_TRADE visible with stale cached evidence", async () => {
    const getReport = vi.fn().mockRejectedValue(new Error("Failed to fetch"));
    const getCachedReport = vi.fn().mockResolvedValue(
      buildLoadedReport({
        report: safeResearchReport,
        receivedAtMs: Date.parse("2026-07-25T08:00:10Z"),
        cached: true,
      }),
    );
    render(
      <SidePanelApp runtime={buildRuntime({ getCachedReport, getReport })} />,
    );

    await screen.findByText("本地引擎离线 · 显示上次结果");
    expectSafetyBoundary();
  });
});
