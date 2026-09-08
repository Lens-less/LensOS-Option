import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildLoadedReport, safeResearchReport } from "../report/testFixtures";
import type { SidePanelRuntime } from "../extension/runtime";
import { SidePanelApp } from "./SidePanelApp";
import { isOfflineError } from "./sidepanelFormatters";
import type { LoadedReport } from "../transport";

function buildRuntime(): SidePanelRuntime {
  return {
    getEngineOrigin: vi.fn().mockResolvedValue("http://127.0.0.1:8000"),
    setEngineOrigin: vi.fn().mockResolvedValue("http://127.0.0.1:8000"),
    getContext: vi.fn().mockResolvedValue({
      href: "https://www.deribit.com/options/BTC?instrument=BTC-7AUG26-71000-C",
      route: "/options/BTC",
      source: "url",
      confidence: "url",
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
    getCachedReport: vi.fn().mockResolvedValue(null),
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
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-07-25T08:00:10Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("withdraws current rankings and readiness conditions as a valid report expires", async () => {
    vi.useFakeTimers();
    await act(async () => { render(<SidePanelApp runtime={buildRuntime()} />); });
    expect(screen.getByText("完整两腿")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(61_000); });
    expect(screen.queryByText("完整两腿")).not.toBeInTheDocument();
    expect(screen.queryByText("为什么现在关注")).not.toBeInTheDocument();
    expect(screen.getByText("当前研究证据已失效")).toBeInTheDocument();
    expect(screen.getByText("当前研究证据已失效").closest("details")).toBeNull();
  });

  it("withdraws current research and marks a quality-rejected brief unavailable", async () => {
    const runtime = buildRuntime();
    vi.mocked(runtime.getReport).mockResolvedValue(buildLoadedReport({
      receivedAtMs: Date.now(),
      report: {
        ...safeResearchReport,
        runtime_context: { mode: "live", replay: false, evaluation_clock: "2026-07-25T08:00:10Z" },
        data_status: { ...safeResearchReport.data_status, validated: false },
      },
    }));
    render(<SidePanelApp runtime={runtime} />);
    expect(await screen.findByText("当前研究证据不可用")).toBeInTheDocument();
    expect(screen.queryByText("完整两腿")).not.toBeInTheDocument();
    const brief = within(screen.getByRole("region", { name: "策略简报" }));
    expect(brief.getByRole("status", { name: "NO_TRADE" })).toBeInTheDocument();
    expect(brief.queryByRole("button", { name: /复制/ })).not.toBeInTheDocument();
  });

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

  it("shows a first-run setup checklist when the engine has never been reached", async () => {
    const runtime = buildRuntime();
    vi.mocked(runtime.getReport).mockRejectedValue(new Error("Failed to fetch"));
    vi.mocked(runtime.getCachedReport).mockResolvedValue(null);

    render(<SidePanelApp runtime={runtime} />);

    expect(
      await screen.findByText("本地引擎离线 · 首次设置"),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert").closest("details")).toBeNull();
    expect(screen.getByRole("button", { name: "保存地址" })).toBeVisible();
    expect(
      screen.getByText(
        "python -m crypto_options_report.api --host 127.0.0.1 --port 8000",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "打开完整证据" }),
    ).toHaveAttribute("href", "http://127.0.0.1:8000/evidence/");
  });

  it("shows a persistent stale banner with the last cached report when the engine drops after connecting", async () => {
    const runtime = buildRuntime();
    vi.mocked(runtime.getReport).mockRejectedValue(new Error("Failed to fetch"));
    vi.mocked(runtime.getCachedReport).mockResolvedValue(
      buildLoadedReport({
        report: safeResearchReport,
        receivedAtMs: Date.parse("2026-07-25T08:00:10Z"),
        cached: true,
      }),
    );

    render(<SidePanelApp runtime={runtime} />);

    expect(
      await screen.findByText("本地引擎离线 · 显示上次结果"),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert").closest("details")).toBeNull();
    // Cached provenance remains inspectable; current strategy evidence is withdrawn.
    expect(screen.queryByText("完整两腿")).not.toBeInTheDocument();
    expect(screen.getAllByText("BTC-7AUG26-71000-C").length).toBeGreaterThan(0);
  });

  it("labels unsafe reports as validation failures rather than network outages", async () => {
    const runtime = buildRuntime();
    vi.mocked(runtime.getReport).mockRejectedValue(
      new Error("research report attempted to weaken the safety boundary"),
    );

    render(<SidePanelApp runtime={runtime} />);

    expect(await screen.findByText("报告校验失败")).toBeInTheDocument();
    expect(screen.getByRole("alert").closest("details")).toBeNull();
    expect(screen.getByRole("alert")).not.toHaveTextContent("attempted to weaken");
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
      expect(runtime.getReport).toHaveBeenCalledWith(true, "http://127.0.0.1:8000");
    });

    fireEvent.click(screen.getByRole("button", { name: "引擎设置" }));
    fireEvent.change(
      screen.getByDisplayValue("http://127.0.0.1:8000"),
      { target: { value: "https://example.com" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "保存地址" }));

    expect(
      await screen.findByText(
        /引擎地址保存失败。请使用包含端口的本机 HTTP 地址/,
      ),
    ).toBeInTheDocument();
  });

  it("withdraws the old engine result immediately and ignores its delayed response after an origin change", async () => {
    const runtime = buildRuntime();
    let origin = "http://127.0.0.1:8000";
    let finishOld!: (loaded: LoadedReport) => void;
    vi.mocked(runtime.getEngineOrigin).mockImplementation(async () => origin);
    vi.mocked(runtime.setEngineOrigin).mockImplementation(async (value) => {
      origin = value;
      return origin;
    });
    vi.mocked(runtime.getReport)
      .mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }))
      .mockResolvedValueOnce(buildLoadedReport({ receivedAtMs: Date.now(), analysisRunId: "new-engine-run" }));

    render(<SidePanelApp runtime={runtime} />);
    await waitFor(() => expect(runtime.getReport).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "引擎设置" }));
    fireEvent.change(screen.getByDisplayValue(origin), { target: { value: "http://localhost:8123" } });
    fireEvent.click(screen.getByRole("button", { name: "保存地址" }));
    expect(await screen.findByText("new-engine-run")).toBeInTheDocument();

    await act(async () => { finishOld(buildLoadedReport({ receivedAtMs: Date.now(), analysisRunId: "old-engine-run" })); });
    expect(screen.queryByText("old-engine-run")).not.toBeInTheDocument();
    expect(screen.getByText("new-engine-run")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "打开完整 Evidence Console" }))
      .toHaveAttribute("href", "http://localhost:8123/evidence/");
    expect(runtime.getReport).toHaveBeenLastCalledWith(true, "http://localhost:8123");
  });

  it("clears current rankings while an engine-origin change is still saving", async () => {
    const runtime = buildRuntime();
    vi.mocked(runtime.setEngineOrigin).mockReturnValue(new Promise(() => undefined));
    render(<SidePanelApp runtime={runtime} />);
    expect(await screen.findByText("完整两腿")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "引擎设置" }));
    fireEvent.change(screen.getByDisplayValue("http://127.0.0.1:8000"), { target: { value: "http://localhost:8123" } });
    fireEvent.click(screen.getByRole("button", { name: "保存地址" }));
    expect(screen.queryByText("完整两腿")).not.toBeInTheDocument();
    expect(screen.queryByText("run-123")).not.toBeInTheDocument();
  });
});
