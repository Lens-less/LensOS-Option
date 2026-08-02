import { describe, expect, it } from "vitest";

import { safeResearchReport, strategyResearchFixture, buildLoadedReport } from "./testFixtures";
import {
  projectResearchReportForSidePanel,
  selectContractComparison,
  selectReportFreshness,
  selectSidePanelViewModel,
  validateResearchReport,
} from "./index";
import type { ResearchReport } from "../contracts";

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

  it("requires published editions to keep truthful clocks and a permanent execution NO-GO", () => {
    const publishedReport: ResearchReport = {
      ...safeResearchReport,
      runtime_context: {
        mode: "published",
        replay: false,
        evaluation_clock: "2026-08-02T08:00:00Z",
      },
      publish_edition: {
        captured_at: "2026-08-02T08:00:00Z",
        published_at: "2026-08-02T08:05:00Z",
        next_expected_at: "2026-08-03T08:00:00Z",
        stale_after: "2026-08-04T08:00:00Z",
        cadence: "daily",
      },
      full_system_surface: {
        ...safeResearchReport.full_system_surface,
        release_gates: [
          { name: "research_publication", status: "GO", satisfied: true },
          { name: "execution_authorization", status: "NO-GO", satisfied: false },
        ],
      },
    };

    expect(() => validateResearchReport(publishedReport)).not.toThrow();
    expect(() =>
      validateResearchReport({
        ...publishedReport,
        full_system_surface: {
          ...publishedReport.full_system_surface,
          release_gates: [
            {
              name: "research_publication",
              status: "NO-GO",
              satisfied: false,
            },
            {
              name: "execution_authorization",
              status: "NO-GO",
              satisfied: false,
            },
          ],
        },
      }),
    ).not.toThrow();
    expect(() =>
      validateResearchReport({
        ...publishedReport,
        publish_edition: undefined,
      }),
    ).toThrow(/published edition/i);
    expect(() =>
      validateResearchReport({
        ...publishedReport,
        full_system_surface: {
          ...publishedReport.full_system_surface,
          release_gates: [
            { name: "research_publication", status: "GO", satisfied: true },
            { name: "execution_authorization", status: "GO", satisfied: true },
          ],
        },
      }),
    ).toThrow(/execution authorization/i);
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

  it("widens per-candidate scalars (strikes, expiry, delta, credit, surface quality) and strategy_selection", () => {
    const payload = {
      ...safeResearchReport,
      candidate_research: {
        call_credit_spreads: {
          eligible: [
            {
              candidate_id: "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
              sell_leg_instrument_name: "BTC-7AUG26-71000-C",
              buy_leg_instrument_name: "BTC-7AUG26-77000-C",
              sell_leg_strike_price: 71_000,
              buy_leg_strike_price: 77_000,
              expiry_date: "2026-08-07",
              dte_days: 13.9,
              model_delta: 0.087,
              net_credit: 720,
              spread_width: 6_000,
              premium_currency: "USDC",
              surface_quality: {
                fit_quality_score: 0.9687,
                no_arb_pass: true,
                no_arb_error: 0.0001,
              },
              // Not requested for the panel; must not leak through.
              filter_reason_codes: ["SHOULD_NOT_APPEAR"],
            },
          ],
          review: [],
          rejected: [],
        },
      },
      strategy_research: {
        ...strategyResearchFixture,
        strategy_selection: {
          selection_method: "pareto_frontier_then_lexicographic",
          eligible_spread_count: 5,
          ranked_candidate_ids: ["a", "b"],
          ranking_dimensions: ["relative_value", "path_risk"],
        },
      },
    };

    const projected = projectResearchReportForSidePanel(payload);
    const spread = projected.candidate_research?.call_credit_spreads?.eligible?.[0];

    expect(spread?.sell_leg_strike_price).toBe(71_000);
    expect(spread?.buy_leg_strike_price).toBe(77_000);
    expect(spread?.expiry_date).toBe("2026-08-07");
    expect(spread?.dte_days).toBe(13.9);
    expect(spread?.model_delta).toBe(0.087);
    expect(spread?.net_credit).toBe(720);
    expect(spread?.spread_width).toBe(6_000);
    expect(spread?.premium_currency).toBe("USDC");
    expect(spread?.surface_quality?.fit_quality_score).toBe(0.9687);
    expect(spread?.surface_quality?.no_arb_pass).toBe(true);
    expect("filter_reason_codes" in (spread ?? {})).toBe(false);

    expect(projected.strategy_research?.strategy_selection).toEqual({
      selection_method: "pareto_frontier_then_lexicographic",
      eligible_spread_count: 5,
      ranked_candidate_ids: ["a", "b"],
      ranking_dimensions: ["relative_value", "path_risk"],
    });
  });

  it("trims ev_candidate_scanner to scalars, dropping dense evidence blobs and collapsing REJECT rows to a count", () => {
    const rejectedRows = Array.from({ length: 200 }, (_, index) => ({
      candidate_id: `rejected-${index}`,
      structure_type: "call_credit_spread",
      action: "REJECT",
      ranking_score: null,
      ev_after_cost_usdc: null,
      executable_credit_usdc: null,
      path_risk: { status: "unavailable" },
      kill_conditions: [],
      reason_codes: ["SOME_REASON_CODE_" + "x".repeat(64)],
      edge_components: { smile_residual_richness: { value: 1, unit: "iv_points" } },
      dominated_by: null,
      losing_axes: [],
    }));

    const payload = {
      ...safeResearchReport,
      ev_candidate_scanner: {
        status: "validated",
        score_status: "UNCALIBRATED_RESEARCH_ONLY",
        path_risk_evidence: { dense: "x".repeat(4096) },
        ranking_basis: {
          method: "pareto_frontier_then_lexicographic",
          tie_break_order: ["relative_value", "path_risk"],
          absolute_ev_available: true,
        },
        dominated_explanations: [{ dense: "x".repeat(4096) }],
        ranked_candidates: [
          {
            candidate_id: "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
            structure_type: "call_credit_spread",
            action: "RESEARCH_ONLY",
            ranking_score: 3.2,
            ev_after_cost_usdc: 12.5,
            executable_credit_usdc: 720,
            fair_value_usdc: 700,
            path_risk: {
              status: "validated_historical",
              p_touch: 0.2,
              p_itm: 0.1,
              cvar_95_usdc: -400,
              authoritative_sample_size: 37,
              sample_size_basis: "independent_windows",
            },
            kill_conditions: [],
            edge_components: { dense: "x".repeat(4096) },
            margin_snapshot: { dense: "x".repeat(4096) },
            fair_iv_diagnostics: { dense: "x".repeat(4096) },
            dominated_by: null,
            losing_axes: [],
          },
          ...rejectedRows,
        ],
      },
    };

    const projected = projectResearchReportForSidePanel(payload) as ResearchReport & {
      ev_candidate_scanner?: {
        status?: string;
        ranked_candidates: Array<Record<string, unknown>>;
        rejected_count: number;
      };
    };

    const scanner = projected.ev_candidate_scanner;
    expect(scanner?.status).toBe("validated");
    expect(scanner?.ranked_candidates).toHaveLength(1);
    expect(scanner?.rejected_count).toBe(200);
    const row = scanner?.ranked_candidates[0];
    expect(row?.candidate_id).toBe(
      "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
    );
    expect(row?.ev_after_cost_usdc).toBe(12.5);
    expect(
      (row?.path_risk as Record<string, unknown>)?.authoritative_sample_size,
    ).toBe(37);
    expect("edge_components" in (row ?? {})).toBe(false);
    expect("fair_iv_diagnostics" in (row ?? {})).toBe(false);
    expect("margin_snapshot" in (row ?? {})).toBe(false);
    expect("path_risk_evidence" in (scanner ?? {})).toBe(false);
    expect("dominated_explanations" in (scanner ?? {})).toBe(false);

    expect(JSON.stringify(projected).length).toBeLessThan(
      JSON.stringify(payload).length / 4,
    );
    expect(() => validateResearchReport(projected)).not.toThrow();
  });
});

describe("selectContractComparison", () => {
  const comparisonReport: ResearchReport = {
    ...safeResearchReport,
    strategy_research: {
      ...strategyResearchFixture,
      strategy_selection: {
        selection_method: "pareto_frontier_then_lexicographic",
        eligible_spread_count: 2,
        ranked_candidate_ids: ["spread-a", "spread-b"],
        ranking_dimensions: ["relative_value", "path_risk"],
      },
    },
    candidate_research: {
      call_credit_spreads: {
        eligible: [
          {
            candidate_id: "spread-a",
            sell_leg_instrument_name: "BTC-7AUG26-71000-C",
            buy_leg_instrument_name: "BTC-7AUG26-77000-C",
          },
          {
            candidate_id: "spread-b",
            sell_leg_instrument_name: "BTC-7AUG26-73000-C",
            buy_leg_instrument_name: "BTC-7AUG26-79000-C",
          },
        ],
        review: [],
        rejected: [],
      },
    },
    ev_candidate_scanner: {
      status: "validated",
      score_status: "UNCALIBRATED_RESEARCH_ONLY",
      ranking_basis: {
        method: "pareto_frontier_then_lexicographic",
        tie_break_order: ["relative_value", "path_risk"],
        absolute_ev_available: true,
      },
      ranked_candidates: [
        {
          candidate_id: "spread-b",
          structure_type: "call_credit_spread",
          action: "RESEARCH_ONLY",
          ranking_score: 5.1,
          ev_after_cost_usdc: 40,
          executable_credit_usdc: 900,
          path_risk: { status: "validated_historical" },
          kill_conditions: [],
          dominated_by: null,
          losing_axes: [],
        },
        {
          candidate_id: "spread-a",
          structure_type: "call_credit_spread",
          action: "REVIEW",
          ranking_score: 3.2,
          ev_after_cost_usdc: 12.5,
          executable_credit_usdc: 720,
          path_risk: { status: "validated_historical" },
          kill_conditions: [],
          dominated_by: null,
          losing_axes: [],
        },
      ],
      rejected_count: 0,
    },
  } as unknown as ResearchReport;

  it("locates the current contract's rank and computes signed deltas against it", () => {
    const comparison = selectContractComparison(
      comparisonReport,
      "BTC-7AUG26-71000-C",
    );

    expect(comparison.totalRanked).toBe(2);
    expect(comparison.currentRank).toBe(2);
    expect(comparison.absoluteEvAvailable).toBe(true);
    expect(comparison.rankingDimensions).toEqual([
      "relative_value",
      "path_risk",
    ]);

    const current = comparison.rows.find((row) => row.isCurrent);
    expect(current?.candidateId).toBe("spread-a");
    expect(current?.deltaVsCurrent).toBe(0);

    const alternative = comparison.rows.find((row) => row.rank === 1);
    expect(alternative?.candidateId).toBe("spread-b");
    expect(alternative?.deltaVsCurrent).toBe(27.5);
    expect(alternative?.isCurrent).toBe(false);
  });

  it("reports no current rank when the instrument in view is not on the ranked chain", () => {
    const comparison = selectContractComparison(
      comparisonReport,
      "BTC-7AUG26-99000-C",
    );

    expect(comparison.currentRank).toBeNull();
    expect(comparison.rows.every((row) => !row.isCurrent)).toBe(true);
    expect(comparison.rows.every((row) => row.deltaVsCurrent === null)).toBe(
      true,
    );
  });

  it("returns an empty comparison when the scanner has not produced ranked candidates", () => {
    const comparison = selectContractComparison(safeResearchReport, null);

    expect(comparison.totalRanked).toBe(0);
    expect(comparison.currentRank).toBeNull();
    expect(comparison.rows).toEqual([]);
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
