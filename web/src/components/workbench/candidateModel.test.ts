import { describe, expect, it } from "vitest";

import type { ResearchReport } from "../../contracts";
import {
  candidateById,
  candidateRows,
  dominanceExplanationFor,
  evCandidateScannerOf,
  parseCandidateLegs,
  scannerStatus,
  sortCandidateRows,
  structureTypeOptions,
} from "./candidateModel";

const baseReport: ResearchReport = {
  schema_version: "research_report.v1",
};

function reportWithScanner(scanner: unknown): ResearchReport {
  return { ...baseReport, ev_candidate_scanner: scanner };
}

const validatedScanner = {
  status: "validated",
  score_status: "UNCALIBRATED_RESEARCH_ONLY",
  reason_code: null,
  ranking_basis: {
    method: "dominance_frontier",
    tie_break_order: ["theta_efficiency", "liquidity_cost_ratio"],
    dominance_scope: "same_expiry_same_structure",
    absolute_ev_available: true,
  },
  dominated_explanations: [
    {
      candidate_id: "BTC-7AUG26-71000-C:naked",
      structure_type: "naked_short_call",
      dominated_by: "BTC-7AUG26-73000-C:naked",
      losing_axes: ["liquidity_cost_ratio", "theta_efficiency"],
    },
  ],
  ranked_candidates: [
    {
      candidate_id: "BTC-7AUG26-73000-C:naked",
      structure_type: "naked_short_call",
      action: "RESEARCH_ONLY",
      score_status: "UNCALIBRATED_RESEARCH_ONLY",
      ranking_score: 0.82,
      premium_usdc: 420,
      executable_credit_usdc: 400,
      fair_value_usdc: 410,
      ev_after_cost_usdc: 55.5,
      dte_days: 13.9,
      model_delta: -0.12,
      kill_conditions: [],
      reason_codes: [],
      dominated_by: null,
      losing_axes: [],
      edge_components: {
        theta_efficiency: { value: 1.2, unit: "usdc/day", status: "OK" },
      },
    },
    {
      candidate_id: "BTC-7AUG26-71000-C:naked",
      structure_type: "naked_short_call",
      action: "RESEARCH_ONLY",
      score_status: "UNCALIBRATED_RESEARCH_ONLY",
      ranking_score: 0.41,
      premium_usdc: 380,
      executable_credit_usdc: 360,
      fair_value_usdc: 370,
      ev_after_cost_usdc: null,
      dte_days: 13.9,
      model_delta: 0.087,
      kill_conditions: ["NO_VALIDATED_PATH_RISK"],
      reason_codes: [],
      dominated_by: "BTC-7AUG26-73000-C:naked",
      losing_axes: ["liquidity_cost_ratio"],
      edge_components: null,
    },
    {
      candidate_id:
        "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
      structure_type: "call_credit_spread",
      action: "REJECT",
      ranking_score: null,
      executable_credit_usdc: 162.65,
      ev_after_cost_usdc: null,
      dte_days: 13.9,
      model_delta: 0.087,
      kill_conditions: ["UNCALIBRATED_SCORE_MODEL"],
      reason_codes: [],
      dominated_by: null,
      losing_axes: [],
      edge_components: null,
    },
  ],
};

describe("scannerStatus / evCandidateScannerOf", () => {
  it("defaults to unavailable when the field is absent", () => {
    expect(scannerStatus(baseReport)).toBe("unavailable");
    expect(evCandidateScannerOf(baseReport)).toBeUndefined();
  });

  it("falls back to unavailable for malformed payloads instead of throwing", () => {
    expect(scannerStatus(reportWithScanner("not-an-object"))).toBe(
      "unavailable",
    );
    expect(scannerStatus(reportWithScanner({ status: "something-else" }))).toBe(
      "unavailable",
    );
  });

  it("reports the validated status and preserves ranking basis", () => {
    const report = reportWithScanner(validatedScanner);
    expect(scannerStatus(report)).toBe("validated");
    expect(evCandidateScannerOf(report)?.ranking_basis?.tie_break_order).toEqual([
      "theta_efficiency",
      "liquidity_cost_ratio",
    ]);
  });
});

describe("candidateRows", () => {
  const report = reportWithScanner(validatedScanner);
  const rows = candidateRows(report);

  it("drops malformed candidate entries but keeps well-formed ones", () => {
    expect(rows).toHaveLength(3);
  });

  it("never fabricates a numeric EV when the source is null", () => {
    const noPathRow = rows.find(
      (row) => row.id === "BTC-7AUG26-71000-C:naked",
    );
    expect(noPathRow?.evAfterCostUsdc).toBeNull();
    expect(noPathRow?.hasValidatedEv).toBe(false);
  });

  it("surfaces a real EV number when validated path evidence exists", () => {
    const validatedRow = rows.find(
      (row) => row.id === "BTC-7AUG26-73000-C:naked",
    );
    expect(validatedRow?.evAfterCostUsdc).toBe(55.5);
    expect(validatedRow?.hasValidatedEv).toBe(true);
  });

  it("takes the absolute value of delta for filtering purposes", () => {
    const row = rows.find((row) => row.id === "BTC-7AUG26-73000-C:naked");
    expect(row?.absDelta).toBeCloseTo(0.12);
  });

  it("preserves the server-assigned action verbatim, including REJECT", () => {
    const rejected = rows.find(
      (row) => row.id === "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
    );
    expect(rejected?.action).toBe("REJECT");
  });
});

describe("parseCandidateLegs", () => {
  it("extracts both strikes from a spread candidate id", () => {
    const legs = parseCandidateLegs(
      "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
    );
    expect(legs).toEqual({
      shortStrikeUsdc: 71_000,
      longStrikeUsdc: 77_000,
      kind: "spread",
    });
  });

  it("extracts a single strike from a naked candidate id", () => {
    const legs = parseCandidateLegs("BTC-7AUG26-71000-C:naked");
    expect(legs).toEqual({
      shortStrikeUsdc: 71_000,
      longStrikeUsdc: null,
      kind: "naked",
    });
  });

  it("returns an unknown shape for an unparseable id instead of guessing", () => {
    const legs = parseCandidateLegs("not-a-real-instrument");
    expect(legs.kind).toBe("unknown");
    expect(legs.shortStrikeUsdc).toBeNull();
  });
});

describe("dominanceExplanationFor", () => {
  it("finds the explanation for a dominated candidate", () => {
    const report = reportWithScanner(validatedScanner);
    const explanation = dominanceExplanationFor(
      report,
      "BTC-7AUG26-71000-C:naked",
    );
    expect(explanation?.dominated_by).toBe("BTC-7AUG26-73000-C:naked");
    expect(explanation?.losing_axes).toContain("liquidity_cost_ratio");
  });

  it("returns null for a frontier candidate with no explanation entry", () => {
    const report = reportWithScanner(validatedScanner);
    expect(
      dominanceExplanationFor(report, "BTC-7AUG26-73000-C:naked"),
    ).toBeNull();
  });
});

describe("structureTypeOptions / candidateById", () => {
  it("lists the distinct structure types present", () => {
    const rows = candidateRows(reportWithScanner(validatedScanner));
    expect(structureTypeOptions(rows)).toEqual([
      "call_credit_spread",
      "naked_short_call",
    ]);
  });

  it("looks a candidate up by id", () => {
    const report = reportWithScanner(validatedScanner);
    expect(candidateById(report, "BTC-7AUG26-73000-C:naked")?.id).toBe(
      "BTC-7AUG26-73000-C:naked",
    );
    expect(candidateById(report, "does-not-exist")).toBeNull();
  });
});

describe("sortCandidateRows", () => {
  const rows = candidateRows(reportWithScanner(validatedScanner));

  it("sorts ascending by ranking score, nulls last", () => {
    const sorted = sortCandidateRows(rows, {
      key: "rankingScore",
      direction: "asc",
    });
    expect(sorted.map((row) => row.rankingScore)).toEqual([0.41, 0.82, null]);
  });

  it("never mutates the input array or any row's action", () => {
    const before = rows.map((row) => row.action);
    sortCandidateRows(rows, { key: "evAfterCostUsdc", direction: "desc" });
    expect(rows.map((row) => row.action)).toEqual(before);
  });
});
