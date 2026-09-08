import { describe, expect, it } from "vitest";
import type { ResearchReport } from "../contracts";

import {
  formatDvol,
  formatFractionAsPercent,
  formatPercent,
  friendlySource,
  marketDisplayState,
} from "./display";

// The two percent formatters exist so unit semantics are carried by the call
// site instead of guessed from magnitude. These tests pin the regression that
// motivated the split: a 1.5% strike distance must never render as "150.00%".
describe("percent formatting carries unit semantics", () => {
  it("renders already-percent values without rescaling", () => {
    expect(formatPercent(1.5, 2)).toBe("1.50%");
    expect(formatPercent(45.2, 1)).toBe("45.2%");
    expect(formatPercent(null)).toBe("—");
  });

  it("rescales fraction values exactly once", () => {
    expect(formatFractionAsPercent(0.015, 2)).toBe("1.50%");
    expect(formatFractionAsPercent(0.13, 1)).toBe("13.0%");
    expect(formatFractionAsPercent(null)).toBe("—");
  });

  it("renders DVOL points as percentages without rescaling", () => {
    expect(formatDvol(45.23)).toBe("45.23%");
    expect(formatDvol(0.85)).toBe("0.85%");
    expect(formatDvol(null)).toBe("不可用");
  });

  it("labels demo sources explicitly", () => {
    expect(friendlySource("demo:bundled-option-chain")).toBe("演示数据");
    expect(friendlySource("fixture:deribit-btc-option-chain")).toBe(
      "验证回放数据",
    );
  });
});

describe("market display eligibility", () => {
  const report: ResearchReport = {
    schema_version: "research_report.v1",
    data_status: { validated: true },
  };

  it.each(["live", "replay", "published"] as const)("expires %s without depending on validation cached in the snapshot", (mode) => {
    expect(marketDisplayState(report, { mode, phase: "expired", ageSec: 60, maxAgeSec: 60 })).toBe("stale");
  });

  it("requires both a verifiable age and a validated market snapshot", () => {
    expect(marketDisplayState(report, { phase: "unavailable", ageSec: null, maxAgeSec: 60 })).toBe("quality_blocked");
    expect(marketDisplayState({ ...report, data_status: { validated: false } }, { phase: "current", ageSec: 0, maxAgeSec: 60 })).toBe("quality_blocked");
    expect(marketDisplayState(report, { phase: "warning", ageSec: 45, maxAgeSec: 60 })).toBe("available");
  });

  it("withdraws a contradictory failed quality gate even if validated is true", () => {
    expect(marketDisplayState({ ...report, data_status: {
      validated: true, quality_gate: { passed: false },
    } }, { phase: "current", ageSec: 0, maxAgeSec: 60 })).toBe("quality_blocked");
  });

  it("requires publication authorization only for a published surface, independently of execution", () => {
    const freshness = { phase: "current" as const, ageSec: 0, maxAgeSec: 60 };
    const published: ResearchReport = {
      ...report,
      runtime_context: { mode: "published", replay: false },
      full_system_surface: { release_gates: [
        { name: "research_publication", status: "NO-GO", satisfied: false },
        { name: "execution_authorization", status: "NO-GO", satisfied: false },
      ] },
    };
    expect(marketDisplayState(published, freshness)).toBe("quality_blocked");
    expect(marketDisplayState({ ...published, runtime_context: { mode: "live", replay: false } }, freshness)).toBe("available");
    published.full_system_surface!.release_gates![0] = { name: "research_publication", status: "GO", satisfied: true };
    expect(marketDisplayState(published, freshness)).toBe("available");
    published.full_system_surface!.release_gates = [];
    expect(marketDisplayState(published, freshness)).toBe("quality_blocked");
  });
});
