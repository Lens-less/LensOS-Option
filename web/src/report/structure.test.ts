import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { validateResearchReport } from "./runtime";
import { validateStrategyBrief } from "./strategyBrief";
import { safeResearchReport } from "./testFixtures";

function mutated(path: string, value: unknown): unknown {
  const report = structuredClone(safeResearchReport) as unknown as Record<string, unknown>;
  report.ev_candidate_scanner ??= { status: "validated" };
  const parts = path.split(".");
  let current = report;
  for (const [index, part] of parts.slice(0, -1).entries()) {
    if (!current[part] || typeof current[part] !== "object") {
      current[part] = /^\d+$/.test(parts[index + 1]) ? [] : {};
    }
    current = current[part] as Record<string, unknown>;
  }
  current[parts.at(-1)!] = value;
  return report;
}

describe("validateResearchReport structural boundary", () => {
  it.each([
    ["data_status", []],
    ["data_status.source", {}],
    ["data_status.validated", "true"],
    ["data_status.market_data_age_sec", Number.NaN],
    ["data_status.public_response_contract.endpoints.vol_index.volatility", "0.45"],
    ["data_trust.reason_codes", "MISSING_DATA"],
    ["vol_surface_status.expiries", {}],
    ["vol_surface_status.expiries.0.surface_points", [null]],
    ["vol_surface_status.expiries.0.expiry_date", "2026-02-30"],
    ["candidate_research.call_credit_spreads.eligible", "candidate"],
    ["candidate_research.call_credit_spreads.eligible.0.net_credit", true],
    ["ev_candidate_scanner.ranked_candidates", {}],
    ["ev_candidate_scanner.ranked_candidates.0", { candidate_id: "id", action: "BUY_NOW" }],
    ["ev_candidate_scanner.ranked_candidates.0", { candidate_id: "id", action: "REVIEW", ranking_score: Infinity }],
    ["ev_candidate_scanner.ranked_candidates.0", { candidate_id: "id", action: "REVIEW", structure_legs: [{ option_type: "call", quantity: 1, strike: "100" }] }],
    ["ev_candidate_scanner.ranked_candidates.0", { candidate_id: "id", action: "REVIEW", structure_legs: [{ option_type: "unknown", quantity: 1, strike: 100 }] }],
    ["strategy_research.pipeline", {}],
    ["strategy_research.playbook.entry_contract.conditions", {}],
    ["strategy_research.playbook.entry_contract.conditions.0.status", "ready"],
    ["strategy_research.decision.why_now", [17]],
    ["strategy_research.playbook.candidate.sell_leg", []],
    ["runtime_context.mode", "unknown"],
    ["runtime_context.replay", "false"],
    ["runtime_context.evaluation_clock", "2026-09-05T12:00:00"],
    ["runtime_context.evaluation_clock", "2026-02-30T12:00:00Z"],
    ["generated_at", "last week"],
    ["vrp_status.series", {}],
    ["full_system_surface.release_readiness.prerequisites", {}],
    ["full_system_surface.release_gates", [null]],
    ["backtest_status.artifact_id", { id: "bt-1" }],
    ["strategy_brief", ""],
    ["strategy_brief", 0],
    ["combination_risk.members", {}],
    ["combination_risk.book.greeks.by_expiry", []],
    ["unknown_extension.metric", -Infinity],
  ])("rejects malformed %s before a consumer reads it", (path, value) => {
    try {
      validateResearchReport(mutated(path, value));
      expect.fail("Malformed report reached its consumers");
    } catch (error) {
      expect(error).toMatchObject({ kind: "structure" });
      expect(String(error)).not.toContain("[object Object]");
    }
  });

  it("retains legal omitted and explicitly unavailable optional evidence", () => {
    const report = {
      ...safeResearchReport,
      data_status: { status: "missing", source: "not_configured", validated: false, market_data_age_sec: null },
      strategy_research: { schema_version: "strategy_research.v1", execution_allowed: false, playbook: null },
      candidate_research: { call_credit_spreads: { eligible: [], rejected: [], review: [] } },
      strategy_brief: undefined,
      runtime_context: undefined,
    };
    expect(validateResearchReport(report)).toBe(report);
  });

  it("identifies a structurally valid safety violation separately", () => {
    const report = mutated("mode_gate.trade_recommendation_allowed", true);
    expect(() => validateResearchReport(report)).toThrow(/safety boundary/i);
    try { validateResearchReport(report); } catch (error) {
      expect(error).toMatchObject({ kind: "safety" });
    }
  });
});

const sharedFixture = (name: string): Record<string, unknown> => JSON.parse(readFileSync(
  resolve(process.cwd(), "../tests/fixtures/public_contract", `${name}.json`), "utf8",
)) as Record<string, unknown>;

describe("Python and TypeScript shared report contract fixtures", () => {
  it.each(["ready", "missing", "degraded"])("accepts the real %s projection", (name) => {
    const fixture = sharedFixture(name);
    expect(() => validateResearchReport(fixture.ResearchReport)).not.toThrow();
    expect(() => validateStrategyBrief(fixture.StrategyBrief)).not.toThrow();
  });

  const mutations = JSON.parse(readFileSync(resolve(process.cwd(), "../tests/fixtures/public_contract/mutations.json"), "utf8")) as Array<{
    name: string; component: "ResearchReport" | "StrategyBrief"; scope: string;
    path: Array<string | number>; op: "set" | "delete"; value?: unknown;
  }>;
  it.each(mutations.filter((item) => item.scope === "common"))("rejects the shared $name boundary", (mutation) => {
    const payload = structuredClone(sharedFixture("ready")[mutation.component]);
    let current = payload as Record<string | number, unknown>;
    for (const key of mutation.path.slice(0, -1)) current = current[key] as Record<string | number, unknown>;
    const key = mutation.path.at(-1)!;
    if (mutation.op === "delete") delete current[key];
    else current[key] = mutation.value;
    expect(() => mutation.component === "ResearchReport" ? validateResearchReport(payload) : validateStrategyBrief(payload)).toThrow();
  });
});
