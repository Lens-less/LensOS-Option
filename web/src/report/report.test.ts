import { describe, expect, it } from "vitest";

import { safeResearchReport, strategyResearchFixture, buildLoadedReport } from "./testFixtures";
import {
  projectResearchReportForSidePanel,
  selectReportFreshness,
  selectSidePanelViewModel,
  validateResearchReport,
} from "./index";

describe("validateResearchReport", () => {
  it("accepts a fail-closed research report", () => {
    const report = validateResearchReport(safeResearchReport);
    expect(report.schema_version).toBe("research_report.v1");
    expect(report.strategy_research?.execution_allowed).toBe(false);
    expect(report.strategy_research?.playbook?.risk_budget?.contracts).toBeNull();
  });

  it("rejects reports that weaken strategy execution safety", () => {
    expect(() =>
      validateResearchReport({
        ...safeResearchReport,
        strategy_research: {
          ...strategyResearchFixture,
          execution_allowed: true,
        },
      }),
    ).toThrow(/allow execution/i);

    expect(() =>
      validateResearchReport({
        ...safeResearchReport,
        strategy_research: {
          ...strategyResearchFixture,
          playbook: {
            ...strategyResearchFixture.playbook,
            risk_budget: {
              ...strategyResearchFixture.playbook?.risk_budget,
              contracts: 1,
            },
          },
        },
      }),
    ).toThrow(/contract count/i);
  });

  it("rejects reports that drop required blocked outputs", () => {
    expect(() =>
      validateResearchReport({
        ...safeResearchReport,
        blocked_outputs: ["trade_recommendation"],
      }),
    ).toThrow(/safety boundary/i);
  });
});

describe("projectResearchReportForSidePanel", () => {
  it("drops dense console-only evidence while preserving fail-closed fields", () => {
    const fullPayload = {
      ...safeResearchReport,
      evidence_lineage: {
        snapshots: Array.from({ length: 200 }, (_, index) => ({
          id: `snapshot-${index}`,
          raw_payload: "x".repeat(128),
        })),
      },
      vol_surface_status: {
        status: "available",
        expiries: Array.from({ length: 40 }, (_, index) => ({
          expiry_date: `2026-09-${String(index + 1).padStart(2, "0")}`,
          surface_points: Array.from({ length: 20 }, () => ({
            market_mark_iv: 0.5,
          })),
        })),
      },
    };

    const projected = projectResearchReportForSidePanel(fullPayload);

    expect(projected).toMatchObject({
      schema_version: "research_report.v1",
      action: "RESEARCH_ONLY",
      full_system_surface: {
        release_readiness: { status: "NO-GO" },
      },
      strategy_research: {
        execution_allowed: false,
      },
    });
    expect("evidence_lineage" in projected).toBe(false);
    expect(projected.vol_surface_status).toBeUndefined();
    expect(
      "contracts" in
        (projected.strategy_research?.playbook?.risk_budget ?? {}),
    ).toBe(false);
    expect(JSON.stringify(projected).length).toBeLessThan(
      JSON.stringify(fullPayload).length / 4,
    );
    expect(() => validateResearchReport(projected)).not.toThrow();
  });
});

describe("report selectors", () => {
  it("marks warning and expired freshness from report age plus receipt age", () => {
    const warning = selectReportFreshness(
      safeResearchReport,
      Date.parse("2026-07-24T10:25:04Z"),
      Date.parse("2026-07-24T10:25:48Z"),
    );
    expect(warning.phase).toBe("warning");
    expect(warning.ageSec).toBe(48);

    const expired = selectReportFreshness(
      safeResearchReport,
      Date.parse("2026-07-24T10:25:04Z"),
      Date.parse("2026-07-24T10:26:10Z"),
    );
    expect(expired.phase).toBe("expired");
    expect(expired.ageSec).toBe(70);
  });

  it("keeps full contract names and the complete decision loop in the side-panel view model", () => {
    const longSellLeg = "BTC-28SEP26-123456789-C-LONG-CONTRACT-WITH-NO-TRUNCATION";
    const longBuyLeg = "BTC-28SEP26-223456789-C-LONG-CONTRACT-WITH-NO-TRUNCATION";
    const loaded = buildLoadedReport({
      report: {
        ...safeResearchReport,
        strategy_research: {
          ...strategyResearchFixture,
          playbook: {
            ...strategyResearchFixture.playbook,
            candidate: {
              ...strategyResearchFixture.playbook?.candidate,
              candidate_id: `${longSellLeg}->${longBuyLeg}:spread`,
              sell_leg: longSellLeg,
              buy_leg: longBuyLeg,
            },
          },
        },
      },
      analysisRunId: "analysis:test",
      etag: "\"abc123\"",
      cached: false,
    });

    const model = selectSidePanelViewModel(loaded, {
      nowMs: Date.parse("2026-07-24T10:25:08Z"),
      currentInstrumentName: "BTC-28SEP26-999999-C",
    });

    expect(model.sellLeg).toBe(longSellLeg);
    expect(model.buyLeg).toBe(longBuyLeg);
    expect(model.contractMatch.status).toBe("mismatch");
    expect(model.contractMatch.message).toContain(
      "不要把全局 BTC 结论当作该合约的专属进场信号",
    );
    expect(model.entryConditions).toHaveLength(2);
    expect(model.referenceMaxLossUsdShadow).toBe(3_280);
    expect(model.maxSingleSpreadLossNav).toBe(0.005);
    expect(model.exitProfitCapture).toHaveLength(1);
    expect(model.exitPositionStates[0]?.state).toBe("review");
    expect(model.exitTimeManagement.reviewBelowDteDays).toBe(7);
    expect(model.exitTimeManagement.lossDeferralAloneIsForbidden).toBe(true);
    expect(model.exitKillSwitches).toContain("market data age > 60 sec");
    expect(model.monitoring).toHaveLength(1);
    expect(model.review.missingEvidence).toContain("CALIBRATION_NOT_IMPLEMENTED");
    expect(model.analysisRunId).toBe("analysis:test");
    expect(model.etag).toBe("\"abc123\"");
    expect(model.cached).toBe(false);
  });

  it("distinguishes a covered comparison candidate from the primary playbook", () => {
    const comparisonInstrument = "BTC-28SEP26-135000-C";
    const loaded = buildLoadedReport({
      report: {
        ...safeResearchReport,
        candidate_research: {
          naked_short_calls: {
            rejected: [
              {
                candidate_id: "naked-comparison-1",
                instrument_name: comparisonInstrument,
                decision: "rejected",
              },
            ],
          },
        },
      },
    });

    const model = selectSidePanelViewModel(loaded, {
      currentInstrumentName: comparisonInstrument,
    });

    expect(model.contractMatch.status).toBe("strategy_candidate");
    expect(model.contractMatch.candidateId).toBe("naked-comparison-1");
    expect(model.contractMatch.message).toContain(
      "裸卖看涨仍是被拒绝的研究备选",
    );
  });
});
