import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ResearchReport } from "../contracts";
import type { ExtensionMessage } from "../extension/messages";
import { chromeSidePanelRuntime } from "../extension/runtime";
import { createExtensionWorkerController } from "../extension/service-worker";
import { projectResearchReportForSidePanel, validateResearchReport } from "../report";
import { safeResearchReport } from "../report/testFixtures";
import { validateStrategyBrief } from "../report/strategyBrief";
import { SidePanelApp } from "./SidePanelApp";

const golden = JSON.parse(readFileSync(resolve(process.cwd(),
  "../tests/fixtures/strategy_brief/golden_strategy_brief_v1.json"), "utf8")) as Record<string, unknown>;
const canonicalBrief = validateStrategyBrief(golden);
delete canonicalBrief.evidence_summary.surface;
const capturedAt = canonicalBrief.generated_at;
const capturedAtMs = Date.parse(capturedAt);
const origin = "http://127.0.0.1:8000";

function researchReport(mode: "live" | "replay" | "published" = "live"): ResearchReport {
  const brief = structuredClone(golden);
  brief.private_account_replay = { internal_payload: "PRIVATE_BRIEF_SENTINEL" };
  Object.assign(brief.market as object, { internal_diagnostics: "PRIVATE_MARKET_SENTINEL" });
  const report: ResearchReport = {
    ...structuredClone(safeResearchReport),
    generated_at: capturedAt,
    runtime_context: { mode, replay: mode === "replay", demo_mode: mode === "replay",
      evaluation_clock: capturedAt, snapshot_fixture: "C:/PRIVATE_SNAPSHOT_SENTINEL/account.json",
      notice: "PRIVATE_NOTICE_SENTINEL" },
    data_status: { status: "validated", source: "deribit_live:https://www.deribit.com",
      validated: true, market_data_age_sec: 0,
      quality_gate: { passed: true, thresholds: { market_data_max_age_sec: 60 } } },
    strategy_brief: brief,
  };
  Object.assign(report, {
    account_status: { source: "PRIVATE_ACCOUNT_SENTINEL" },
    evidence_lineage: { private_account_replay: "PRIVATE_LINEAGE_SENTINEL" },
  });
  if (mode === "published") {
    report.publish_edition = {
      cadence: "daily", captured_at: capturedAt, published_at: capturedAt,
      next_expected_at: new Date(capturedAtMs + 86_400_000).toISOString(),
      stale_after: new Date(capturedAtMs + 172_800_000).toISOString(),
    };
    report.full_system_surface!.release_gates = [
      { name: "research_publication", status: "GO", satisfied: true },
      { name: "execution_authorization", status: "NO-GO", satisfied: false },
      { name: "PRIVATE_GATE_SENTINEL", status: "NO-GO", satisfied: false },
    ];
  }
  return validateResearchReport(report);
}

function installWorker(report: ResearchReport) {
  const session = new Map<string, unknown>();
  const local = new Map<string, unknown>();
  const controller = createExtensionWorkerController({
    loadReport: async () => ({ report, receivedAtMs: capturedAtMs, analysisRunId: canonicalBrief.analysis_run_id }),
    readSession: async <T,>(key: string) => session.get(key) as T | undefined,
    writeSession: async (key, value) => { session.set(key, structuredClone(value)); },
    readLocal: async <T,>(key: string) => local.get(key) as T | undefined,
    writeLocal: async (key, value) => { local.set(key, structuredClone(value)); },
    setSidePanelOptions: async () => undefined,
  });
  // Only Chrome's transport/storage and the HTTP boundary are replaced. The
  // worker projection, response validator, runtime and UI are the real code.
  vi.stubGlobal("chrome", { runtime: { sendMessage: async (message: ExtensionMessage) =>
    JSON.parse(JSON.stringify(await controller.handleMessage(message))) as unknown } });
  return session;
}

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(capturedAtMs); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("actual worker to runtime to side panel contract", () => {
  it("does not disclose a custom source path or invent runtime provenance", () => {
    const report = researchReport();
    report.data_status!.source = "C:/PRIVATE_SOURCE_SENTINEL/snapshot.json";
    report.runtime_context = undefined;
    const projected = projectResearchReportForSidePanel(report);
    expect(projected.runtime_context).toBeUndefined();
    expect(projected.data_status?.source).toBe("其他研究数据源");
    expect(JSON.stringify(projected)).not.toContain("PRIVATE_");
    expect(() => validateResearchReport(projected)).not.toThrow();
  });

  it("renders a canonical brief after compact messaging and withdraws its current evidence on expiry", async () => {
    const session = installWorker(researchReport());
    await act(async () => { render(<SidePanelApp />); });
    expect(screen.getAllByRole("button", { name: "复制组合" })).toHaveLength(canonicalBrief.strategies.length);
    expect(screen.queryByText(/尚未提供 `strategy_brief/)).not.toBeInTheDocument();
    expect(screen.queryByText("当前研究证据不可用")).not.toBeInTheDocument();
    expect(screen.getByText("RESEARCH_ONLY")).toBeVisible();

    const cached = await chromeSidePanelRuntime.getCachedReport(origin);
    expect(cached?.report.generated_at).toBe(capturedAt);
    expect(cached?.report.runtime_context).toEqual({ mode: "live", replay: false, demo_mode: false, evaluation_clock: capturedAt });
    expect(cached?.report.data_status).toMatchObject({ validated: true, quality_gate: { passed: true } });
    expect(cached?.report.strategy_brief).toEqual(canonicalBrief);
    expect(JSON.stringify(session.get("panelReport"))).not.toContain("PRIVATE_");
    expect(JSON.stringify(cached)).not.toContain("PRIVATE_");

    await act(async () => { await vi.advanceTimersByTimeAsync(65_000); });
    expect(screen.getByText("当前研究证据已失效")).toBeVisible();
    expect(screen.queryByRole("button", { name: "复制组合" })).not.toBeInTheDocument();
  });

  it("keeps an explicit quality failure blocked through the same real worker path", async () => {
    const report = researchReport();
    report.data_status!.quality_gate!.passed = false;
    installWorker(report);
    await act(async () => { render(<SidePanelApp />); });
    expect(screen.getByText("当前研究证据不可用")).toBeVisible();
    expect(screen.queryByRole("button", { name: "复制组合" })).not.toBeInTheDocument();
    expect(screen.queryByText(/尚未提供 `strategy_brief/)).not.toBeInTheDocument();
    const cached = await chromeSidePanelRuntime.getCachedReport(origin);
    expect(cached?.report.data_status?.quality_gate?.passed).toBe(false);
    expect(cached?.report.strategy_brief).toEqual(canonicalBrief);
  });

  it("preserves publication and execution gates independently in a compact published report", async () => {
    const report = researchReport("published");
    installWorker(report);
    await act(async () => { render(<SidePanelApp />); });
    expect(screen.getAllByRole("button", { name: "复制组合" })).toHaveLength(canonicalBrief.strategies.length);
    const loaded = await chromeSidePanelRuntime.getReport(false, origin);
    expect(loaded.report.publish_edition).toEqual(report.publish_edition);
    expect(loaded.report.full_system_surface?.release_gates).toEqual(report.full_system_surface?.release_gates?.slice(0, 2));
    expect(() => validateResearchReport(loaded.report)).not.toThrow();
    const blocked = researchReport("published");
    blocked.full_system_surface!.release_gates![0] = { name: "research_publication", status: "NO-GO", satisfied: false };
    expect(projectResearchReportForSidePanel(blocked).full_system_surface?.release_gates?.[0]?.status).toBe("NO-GO");
    expect(JSON.stringify(loaded)).not.toContain("PRIVATE_");
  });

  it("retains declared replay provenance without promoting it into live data", async () => {
    installWorker(researchReport("replay"));
    await act(async () => { render(<SidePanelApp />); });
    const brief = within(screen.getByRole("region", { name: "策略简报" }));
    expect(brief.getByText("Demo snapshot")).toBeVisible();
    fireEvent.click(screen.getByText("查看依据"));
    const cached = await chromeSidePanelRuntime.getCachedReport(origin);
    expect(cached?.report.runtime_context?.mode).toBe("replay");
    expect(cached?.report.runtime_context?.demo_mode).toBe(true);
    expect(cached?.report.runtime_context?.snapshot_fixture).toBeUndefined();
  });
});
