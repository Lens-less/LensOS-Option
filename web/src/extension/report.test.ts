import { describe, expect, it } from "vitest";
import {
  selectSidePanelViewModel,
  validateResearchReport,
} from "../report";
import {
  buildLoadedReport,
  safeResearchReport,
} from "../report/testFixtures";

describe("shared report contracts reused by the extension", () => {
  it("accepts a fail-closed research-only report", () => {
    expect(validateResearchReport(safeResearchReport)).toBe(safeResearchReport);
  });

  it("projects the current Deribit contract through the shared side panel selector", () => {
    const loaded = buildLoadedReport({
      report: safeResearchReport,
      receivedAtMs: Date.parse("2026-07-24T10:25:04Z"),
      analysisRunId: "analysis-run-42",
      etag: "\"etag-1\"",
      cached: true,
    });

    const model = selectSidePanelViewModel(loaded, {
      nowMs: Date.parse("2026-07-24T10:25:24Z"),
      currentInstrumentName: "BTC-7AUG26-71000-C",
    });

    expect(model.sourceLabel).toContain("deribit");
    expect(model.contractMatch.status).toBe("sell_leg");
    expect(model.sellLeg).toBe("BTC-7AUG26-71000-C");
    expect(model.buyLeg).toBe("BTC-7AUG26-77000-C");
    expect(model.monitoring[0]?.metric).toBe("market_age_sec");
    expect(model.review.missingEvidence).toContain(
      "MISSING_ACCOUNT_API_SNAPSHOT",
    );
  });
});
