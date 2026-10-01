import { afterEach, describe, expect, it, vi } from "vitest";

import { compareDesk, validateDecisionDesk } from "./client";
import { observeComparisonFixture, observeDeskFixture } from "./observeFixtures";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("decision research boundary", () => {
  it("keeps frozen historical observations readable relative to their own evaluation clock", () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2025-01-01T00:00:00Z"));
    const saved = observeDeskFixture();
    vi.useRealTimers();
    expect(validateDecisionDesk(saved)).toBe(saved);
  });

  it.each(["old_quote", "expired_contract", "unsynchronized", "open_execution"])("rejects comparable data with %s", (fault) => {
    const desk = observeDeskFixture();
    const selected = desk.candidates[0];
    if (fault === "old_quote") selected.legs[0].quote_time = "2020-01-01T00:00:00Z";
    if (fault === "expired_contract") selected.expiration_timestamp = 100_000_000_000;
    if (fault === "unsynchronized") selected.legs[0].quote_time = new Date(Date.parse(desk.generated_at) - 4000).toISOString();
    if (fault === "open_execution") (desk.qualification as { execution_allowed: boolean }).execution_allowed = true;
    expect(() => validateDecisionDesk(desk)).toThrow("安全约束");
  });

  it("rejects an otherwise valid comparison response from a different frozen analysis", async () => {
    const desk = observeDeskFixture();
    const comparison = observeComparisonFixture(desk);
    comparison.analysis_id = "another-analysis";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(comparison), { status: 200 })));
    await expect(compareDesk(desk.snapshot_id, desk.candidates.map((c) => c.candidate_id), comparison.scenario, desk.analysis_id)).rejects.toThrow("安全约束");
  });
});
