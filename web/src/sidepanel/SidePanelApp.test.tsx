import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildLoadedReport, safeResearchReport } from "../report/testFixtures";
import type { SidePanelRuntime } from "../extension/runtime";
import { SidePanelApp } from "./SidePanelApp";
import { isOfflineError } from "./sidepanelFormatters";

function buildRuntime(): SidePanelRuntime {
  return {
    getEngineOrigin: vi.fn().mockResolvedValue("http://127.0.0.1:8000"),
    setEngineOrigin: vi.fn().mockResolvedValue("http://127.0.0.1:8000"),
    getContext: vi.fn().mockResolvedValue({
      href: "https://www.deribit.com/options/BTC?instrument=BTC-7AUG26-71000-C",
      route: "/options/BTC",
      source: "url",
      instrument: "BTC-7AUG26-71000-C",
      underlying: "BTC",
      detectedAt: Date.parse("2026-07-25T08:00:00Z"),
    }),
    getReport: vi.fn().mockResolvedValue(
      buildLoadedReport({
        report: safeResearchReport,
        receivedAtMs: Date.parse("2026-07-25T08:00:10Z"),
        etag: "\"etag-1\"",
        analysisRunId: "run-123",
        cached: true,
      }),
    ),
    getEvidenceUrl: vi
      .fn()
      .mockImplementation((origin: string) => `${origin}/evidence/`),
  };
}

function expectBefore(first: Element, second: Element): void {
  expect(
    first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).not.toBe(0);
}

describe("SidePanelApp", () => {
  it("renders the read-only side panel composition from shared report data", async () => {
    render(<SidePanelApp runtime={buildRuntime()} />);

    await screen.findByText("期权研究伴侣");
    await screen.findByText("READ-ONLY");
    expect(screen.getByText("完整两腿")).toBeInTheDocument();
    expect(screen.getAllByText("BTC-7AUG26-71000-C").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BTC-7AUG26-77000-C").length).toBeGreaterThan(0);
    expect(screen.getByText("Deribit 实时公开数据")).toBeInTheDocument();
    expect(screen.getByText("run-123")).toBeInTheDocument();
    expect(screen.getByText("低于此 DTE 复核")).toBeInTheDocument();
    expect(screen.getByText("$3,280 参考影子值")).toBeInTheDocument();
    expect(
      screen.getByText(/风险与退出为未校准研究模板/),
    ).toBeInTheDocument();

    const contextHeading = screen.getByText("当前合约与数据可信度");
    const source = screen.getByText("Deribit 实时公开数据");
    const decisionLoop = screen.getByText("完整两腿");
    const review = screen.getByText("持仓监控与复盘缺口");
    const settings = screen.getByRole("button", { name: "引擎设置" });
    expectBefore(contextHeading, source);
    expectBefore(source, decisionLoop);
    expectBefore(decisionLoop, review);
    expectBefore(review, settings);
  });

  it("lets the operator override the current contract locally", async () => {
    render(<SidePanelApp runtime={buildRuntime()} />);
    const input = await screen.findByPlaceholderText("BTC-7AUG26-71000-C");

    fireEvent.change(input, {
      target: {
        value: "BTC-7AUG26-77000-C",
      },
    });

    await waitFor(() => {
      expect(screen.getByDisplayValue("BTC-7AUG26-77000-C")).toBeInTheDocument();
      expect(screen.getAllByText("当前合约 = 买腿").length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByRole("button", { name: "同步当前合约" }));
    await waitFor(() => {
      expect(screen.getByDisplayValue("")).toBeInTheDocument();
      expect(screen.getAllByText("当前合约 = 卖腿").length).toBeGreaterThan(0);
    });
  });

  it("distinguishes transport failures from report validation failures", () => {
    expect(isOfflineError("Failed to fetch")).toBe(true);
    expect(isOfflineError("network request error")).toBe(true);
    expect(isOfflineError("loaded report safety boundary rejected")).toBe(
      false,
    );
  });

  it("shows a recoverable offline state when the local engine cannot be reached", async () => {
    const runtime = buildRuntime();
    vi.mocked(runtime.getReport).mockRejectedValue(new Error("Failed to fetch"));

    render(<SidePanelApp runtime={runtime} />);

    expect(await screen.findByText("本地引擎离线")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "打开完整证据" }),
    ).toHaveAttribute("href", "http://127.0.0.1:8000/evidence/");
  });

  it("labels unsafe reports as validation failures rather than network outages", async () => {
    const runtime = buildRuntime();
    vi.mocked(runtime.getReport).mockRejectedValue(
      new Error("research report attempted to weaken the safety boundary"),
    );

    render(<SidePanelApp runtime={runtime} />);

    expect(await screen.findByText("报告校验失败")).toBeInTheDocument();
    expect(screen.queryByText("本地引擎离线")).not.toBeInTheDocument();
  });

  it("supports force refresh and surfaces rejected loopback settings", async () => {
    const runtime = buildRuntime();
    vi.mocked(runtime.setEngineOrigin).mockRejectedValue(
      new Error("Engine origin must stay on a loopback http origin"),
    );
    render(<SidePanelApp runtime={runtime} />);
    await screen.findByText("期权研究伴侣");

    fireEvent.click(screen.getByRole("button", { name: "刷新研究" }));
    await waitFor(() => {
      expect(runtime.getReport).toHaveBeenCalledWith(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "引擎设置" }));
    fireEvent.change(
      screen.getByDisplayValue("http://127.0.0.1:8000"),
      { target: { value: "https://example.com" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "保存地址" }));

    expect(
      await screen.findByText(
        "Engine origin must stay on a loopback http origin",
      ),
    ).toBeInTheDocument();
  });
});
