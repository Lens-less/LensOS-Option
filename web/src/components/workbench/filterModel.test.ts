import { describe, expect, it } from "vitest";

import type { CandidateViewRow } from "./candidateModel";
import {
  ALL_ACTION_TIERS,
  DEFAULT_ACTION_TIERS,
  applyFilters,
  decodeFilters,
  defaultFilters,
  encodeFilters,
  isDefaultFilters,
} from "./filterModel";

function row(overrides: Partial<CandidateViewRow>): CandidateViewRow {
  return {
    id: "candidate-1",
    structureType: "naked_short_call",
    structureKind: "naked",
    action: "RESEARCH_ONLY",
    scoreStatus: "UNCALIBRATED_RESEARCH_ONLY",
    rankingScore: 0.5,
    premiumUsdc: 400,
    executableCreditUsdc: 380,
    fairValueUsdc: 390,
    evAfterCostUsdc: 40,
    hasValidatedEv: true,
    dteDays: 14,
    absDelta: 0.12,
    killConditions: [],
    reasonCodes: [],
    dominatedBy: null,
    losingAxes: [],
    legs: { shortStrikeUsdc: 71_000, longStrikeUsdc: null, kind: "naked" },
    raw: {
      candidate_id: "candidate-1",
      action: "RESEARCH_ONLY",
    },
    ...overrides,
  };
}

const rows: CandidateViewRow[] = [
  row({ id: "research-a", action: "RESEARCH_ONLY", dteDays: 10, absDelta: 0.1, executableCreditUsdc: 500, structureType: "naked_short_call" }),
  row({ id: "review-b", action: "REVIEW", dteDays: 20, absDelta: 0.3, executableCreditUsdc: 100, structureType: "call_credit_spread" }),
  row({ id: "reject-c", action: "REJECT", dteDays: 5, absDelta: 0.5, executableCreditUsdc: 900, structureType: "naked_short_call" }),
];

describe("defaultFilters / isDefaultFilters", () => {
  it("starts with the rejected tier hidden and nothing else narrowed", () => {
    // A live chain returns a few hundred rejected candidates against a handful
    // of research-grade ones. Showing them all by default buried the rows the
    // page exists for; they stay one checkbox away and the hidden count is
    // always displayed.
    const filters = defaultFilters();
    expect(filters.actionTiers).toEqual([...DEFAULT_ACTION_TIERS]);
    expect(filters.actionTiers).not.toContain("REJECT");
    expect(isDefaultFilters(filters)).toBe(true);
  });

  it("keeps the rejected tier reachable rather than removing it", () => {
    expect(ALL_ACTION_TIERS).toContain("REJECT");
    const widened = { ...defaultFilters(), actionTiers: [...ALL_ACTION_TIERS] };
    expect(isDefaultFilters(widened)).toBe(false);
  });

  it("is no longer the default once any field narrows the set", () => {
    expect(isDefaultFilters({ ...defaultFilters(), minCreditUsdc: 100 })).toBe(
      false,
    );
    expect(
      isDefaultFilters({ ...defaultFilters(), actionTiers: ["RESEARCH_ONLY"] }),
    ).toBe(false);
  });
});

describe("applyFilters purity", () => {
  it("does not mutate the input array or any row", () => {
    const snapshot = rows.map((item) => ({ ...item }));
    applyFilters(rows, { ...defaultFilters(), minCreditUsdc: 400 });
    expect(rows).toEqual(snapshot);
  });

  it("is a pure function: same inputs produce equal outputs", () => {
    const filters = { ...defaultFilters(), dteMin: 8, dteMax: 21 };
    const first = applyFilters(rows, filters);
    const second = applyFilters(rows, filters);
    expect(first).toEqual(second);
    expect(first).not.toBe(second);
  });

  it("narrows by structure type", () => {
    const result = applyFilters(rows, {
      ...defaultFilters(),
      structureTypes: ["call_credit_spread"],
    });
    expect(result.map((item) => item.id)).toEqual(["review-b"]);
  });

  it("narrows by DTE range", () => {
    const result = applyFilters(rows, {
      ...defaultFilters(),
      dteMin: 8,
      dteMax: 15,
    });
    expect(result.map((item) => item.id)).toEqual(["research-a"]);
  });

  it("narrows by absolute delta range", () => {
    // Tiers are widened explicitly: this case is about the numeric predicate,
    // and the default set hides the rejected tier.
    const result = applyFilters(rows, {
      ...defaultFilters(),
      actionTiers: [...ALL_ACTION_TIERS],
      absDeltaMin: 0.25,
    });
    expect(result.map((item) => item.id).sort()).toEqual([
      "reject-c",
      "review-b",
    ]);
  });

  it("narrows by minimum executable credit", () => {
    const result = applyFilters(rows, {
      ...defaultFilters(),
      actionTiers: [...ALL_ACTION_TIERS],
      minCreditUsdc: 450,
    });
    expect(result.map((item) => item.id).sort()).toEqual([
      "reject-c",
      "research-a",
    ]);
  });

  it("excludes rows whose numeric field is unavailable rather than treating it as passing", () => {
    const withMissingDte = [row({ id: "no-dte", dteDays: null })];
    const result = applyFilters(withMissingDte, {
      ...defaultFilters(),
      dteMin: 1,
    });
    expect(result).toHaveLength(0);
  });
});

describe("tier-promotion impossibility", () => {
  it("never returns a REJECT row when only RESEARCH_ONLY is selected", () => {
    const result = applyFilters(rows, {
      ...defaultFilters(),
      actionTiers: ["RESEARCH_ONLY"],
      // Loosen every other slider as far as possible to try to "smuggle"
      // the REJECT row through by matching its numeric shape.
      dteMin: 0,
      dteMax: 100,
      absDeltaMin: 0,
      absDeltaMax: 1,
      minCreditUsdc: 0,
    });
    expect(result.every((item) => item.action === "RESEARCH_ONLY")).toBe(true);
    expect(result.some((item) => item.id === "reject-c")).toBe(false);
  });

  it("preserves each returned row's original action label verbatim", () => {
    const result = applyFilters(rows, {
      ...defaultFilters(),
      actionTiers: [...ALL_ACTION_TIERS],
    });
    for (const filtered of result) {
      const original = rows.find((item) => item.id === filtered.id);
      expect(filtered.action).toBe(original?.action);
    }
  });

  it("cannot be coaxed into upgrading a REJECT row's action by any filter combination", () => {
    const rejectRow = rows.find((item) => item.id === "reject-c");
    const combinations = [
      { ...defaultFilters() },
      { ...defaultFilters(), minCreditUsdc: 0 },
      { ...defaultFilters(), dteMin: 0, dteMax: 1000 },
      { ...defaultFilters(), absDeltaMin: 0, absDeltaMax: 1 },
      { ...defaultFilters(), structureTypes: ["naked_short_call"] },
    ];
    for (const filters of combinations) {
      const result = applyFilters(rows, filters);
      const found = result.find((item) => item.id === "reject-c");
      if (found) {
        expect(found.action).toBe(rejectRow?.action);
        expect(found.action).toBe("REJECT");
      }
    }
  });
});

describe("URL codec", () => {
  it("round-trips a fully-populated filter set", () => {
    const filters = {
      structureTypes: ["naked_short_call", "call_credit_spread"],
      dteMin: 3,
      dteMax: 30,
      absDeltaMin: 0.05,
      absDeltaMax: 0.4,
      minCreditUsdc: 50,
      actionTiers: ["RESEARCH_ONLY", "REVIEW"] as const,
    };
    const params = encodeFilters({ ...filters, actionTiers: [...filters.actionTiers] });
    const decoded = decodeFilters(params);
    expect(decoded.structureTypes).toEqual(filters.structureTypes);
    expect(decoded.dteMin).toBe(3);
    expect(decoded.dteMax).toBe(30);
    expect(decoded.absDeltaMin).toBe(0.05);
    expect(decoded.absDeltaMax).toBe(0.4);
    expect(decoded.minCreditUsdc).toBe(50);
    expect(decoded.actionTiers).toEqual(["RESEARCH_ONLY", "REVIEW"]);
  });

  it("decodes an empty query string back to the defaults", () => {
    const decoded = decodeFilters(new URLSearchParams(""));
    expect(decoded).toEqual(defaultFilters());
  });

  it("ignores unknown tier tokens rather than crashing", () => {
    const decoded = decodeFilters(new URLSearchParams("tiers=RESEARCH_ONLY,BOGUS"));
    expect(decoded.actionTiers).toEqual(["RESEARCH_ONLY"]);
  });
});
