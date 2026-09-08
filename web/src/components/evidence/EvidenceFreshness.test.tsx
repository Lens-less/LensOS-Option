import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ResearchReport } from "../../contracts";
import { EvidenceConsole } from "./EvidenceConsole";
import { strategyBriefFixture } from "../../report/strategyBriefFixtures";

const capturedAt = "2026-09-05T08:00:00Z";
const receivedAtMs = Date.parse(capturedAt);

function snapshot(mode: "live" | "replay" | "demo" | "published"): ResearchReport {
  return {
    schema_version: "research_report.v1",
    generated_at: capturedAt,
    action: "RESEARCH_ONLY",
    runtime_context: {
      mode: mode === "demo" ? "replay" : mode,
      replay: mode === "replay" || mode === "demo",
      demo_mode: mode === "demo",
      evaluation_clock: capturedAt,
    },
    publish_edition: mode === "published" ? {
      captured_at: capturedAt,
      published_at: capturedAt,
      stale_after: "2026-09-05T08:01:00Z",
    } : undefined,
    full_system_surface: mode === "published" ? {
      release_gates: [{ name: "research_publication", status: "GO", satisfied: true }],
    } : undefined,
    data_status: {
      status: "validated",
      validated: true,
      market_data_age_sec: 0,
      source: mode === "demo" ? "demo:test" : "fixture:test",
      feed_coverage: { feeds: { events: {
        status: "available", freshness_status: "fresh",
        scope: "exchange_native_only", source_endpoint: "public/status",
      } } },
    },
    data_trust: { verdict: "trusted" },
    vrp_status: {
      status: "validated", current_vrp_percent_points: 12.34,
      current_dvol_percent: 45.6, current_rv30_percent: 33.26,
    },
    vol_surface_status: {
      status: "validated",
      expiries: [{
        candidate_eligible: true, expiry_date: "2026-09-12", dte_days: 7,
        fit_quality_pass: true, no_arb_pass: true, fit_quality_score: 0.99,
        surface_points: [
          { strike_price: 70000, surface_fitted_iv: 40 },
          { strike_price: 75000, surface_fitted_iv: 42 },
        ],
      }],
    },
    candidate_research: {
      summary: { eligible_naked_short_calls: 1, eligible_call_credit_spreads: 0 },
      naked_short_calls: { eligible: [{
        candidate_id: "test-call", instrument_name: "BTC-12SEP26-75000-C",
        expiry_date: "2026-09-12", model_delta: 0.1, market_mid: 0.002,
        surface_quality: { fit_quality_score: 0.99, no_arb_pass: true },
      }] },
    },
    strategy_research: {
      schema_version: "strategy_research.v1", generated_at: capturedAt,
      advisory_only: true, execution_allowed: false,
      decision: { stance: "CONDITIONAL_RESEARCH", primary_structure: "CALL_CREDIT_SPREAD" },
      pipeline: [{ stage: "SELECT", status: "ready" }],
      analysis: { market: { event_score: 0 } },
      playbook: {
        entry_contract: { status: "blocked", conditions: [
          { id: "market_freshness", label: "Freshness", observed: 0, status: "pass" },
          { id: "candidate_eligibility", label: "Candidate", observed: "eligible", status: "pass" },
        ] },
      },
    },
  };
}

function expectCurrentNumbersWithdrawn() {
  expect(screen.queryByRole("region", { name: "条件式进场规则" })).not.toBeInTheDocument();
  expect(screen.queryByRole("img", { name: "BTC 波动率曲面" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "研究候选表格" })).not.toBeInTheDocument();
  expect(screen.queryByText(/个价差通过当前过滤/)).not.toBeInTheDocument();
  expect(screen.queryByText("12.3 pt")).not.toBeInTheDocument();
  expect(screen.queryByText("当前：0 秒")).not.toBeInTheDocument();
  expect(screen.queryByText("条件式研究")).not.toBeInTheDocument();
  const events = screen.getByRole("region", { name: "事件源与交易所锁定" });
  expect(within(events).queryByText("正常（无交易所锁定）")).not.toBeInTheDocument();
  const audit = screen.getByRole("region", { name: "从市场数据到组合仲裁" });
  expect(within(audit).getByText(/快照审计.*计算时刻/)).toBeInTheDocument();
  expect(audit).toHaveTextContent("2026年9月5日");
  expect(within(audit).queryByText("已验证")).not.toBeInTheDocument();
}

describe("EvidenceConsole current eligibility expires with the visible clock", () => {
  it.each(["published", "replay"] as const)("expires individual strategy evidence within a still-current %s market window", (mode) => {
    const report = snapshot(mode);
    const brief = structuredClone(strategyBriefFixture);
    const evaluationMs = Date.parse(brief.market.as_of);
    const receiptMs = mode === "replay" ? Date.parse("2026-09-08T00:00:00Z") : evaluationMs;
    report.strategy_brief = brief;
    report.generated_at = brief.generated_at;
    report.runtime_context!.evaluation_clock = brief.market.as_of;
    report.data_status!.quality_gate = { passed: true, thresholds: { market_data_max_age_sec: 1000 } };
    if (mode === "published") report.publish_edition = {
      captured_at: brief.market.as_of, published_at: brief.market.as_of,
      stale_after: new Date(evaluationMs + 48 * 60 * 60 * 1000).toISOString(),
    };
    const { rerender } = render(<EvidenceConsole report={report} receivedAtMs={receiptMs} nowMs={receiptMs} />);
    expect(screen.getByRole("button", { name: "复制组合" })).toBeInTheDocument();

    rerender(<EvidenceConsole report={report} receivedAtMs={receiptMs} nowMs={receiptMs + 300_000} />);
    expect(screen.getByRole("heading", { name: "策略简报已暂停" })).toBeInTheDocument();
    expect(screen.getByText("策略简报的有效期已过，等待重新计算。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "复制组合" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "发布已停摆" })).not.toBeInTheDocument();
  });

  it.each(["live", "replay", "demo", "published"] as const)(
    "withdraws current evidence in %s while retaining dated snapshot audit",
    (mode) => {
      const report = snapshot(mode);
      const { rerender } = render(<EvidenceConsole report={report} receivedAtMs={receivedAtMs} nowMs={receivedAtMs} />);
      fireEvent.click(screen.getByText("查看依据"));
      expect(screen.getByRole("region", { name: "条件式进场规则" })).toBeInTheDocument();
      expect(screen.getByRole("img", { name: "BTC 波动率曲面" })).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "研究候选表格" })).toBeInTheDocument();
      expect(screen.getByText("12.3 pt")).toBeInTheDocument();

      rerender(<EvidenceConsole report={report} receivedAtMs={receivedAtMs} nowMs={receivedAtMs + 61_000} />);
      expectCurrentNumbersWithdrawn();
      if (mode === "published") {
        expect(screen.getAllByText("发布已停摆").length).toBeGreaterThan(0);
      } else {
        expect(screen.queryByText("发布已停摆")).not.toBeInTheDocument();
      }

      const refreshed = snapshot(mode);
      refreshed.publish_edition = mode === "published" ? {
        captured_at: "2026-09-05T08:01:00Z",
        published_at: "2026-09-05T08:01:00Z",
        stale_after: "2026-09-05T08:02:00Z",
      } : undefined;
      rerender(<EvidenceConsole report={refreshed} receivedAtMs={receivedAtMs + 61_000} nowMs={receivedAtMs + 61_000} />);
      expect(screen.getByRole("region", { name: "研究候选表格" })).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "条件式进场规则" })).toBeInTheDocument();
    },
  );

  it.each(["missing_age", "quality_blocked"])("withdraws stale embedded passes when %s", (reason) => {
    const report = snapshot("live");
    report.data_status = {
      ...report.data_status,
      ...(reason === "missing_age" ? { market_data_age_sec: null } : { validated: false }),
    };
    render(<EvidenceConsole report={report} receivedAtMs={receivedAtMs} nowMs={receivedAtMs} />);
    fireEvent.click(screen.getByText("查看依据"));
    expectCurrentNumbersWithdrawn();
    expect(screen.queryByText("当前且可信")).not.toBeInTheDocument();
    const brief = screen.getByRole("region", { name: "策略简报" });
    expect(within(brief).getByText("UNAVAILABLE")).toBeInTheDocument();
  });

  it("shows elapsed freshness during the warning window instead of the old zero", () => {
    render(<EvidenceConsole report={snapshot("live")} receivedAtMs={receivedAtMs} nowMs={receivedAtMs + 45_000} />);
    fireEvent.click(screen.getByText("查看依据"));
    const conditions = screen.getByRole("region", { name: "条件式进场规则" });
    expect(within(conditions).getByText("当前：45 秒")).toBeInTheDocument();
    expect(within(conditions).queryByText("当前：0 秒")).not.toBeInTheDocument();
  });
});
