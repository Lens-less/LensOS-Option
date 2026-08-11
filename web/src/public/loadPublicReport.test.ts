import { afterEach, describe, expect, it, vi } from "vitest";

import { loadPublicReport } from "./loadPublicReport";
import { safeResearchReport } from "../report/testFixtures";

function publishedReport(
  releaseGates = [
    { name: "research_publication", status: "GO", satisfied: true },
    {
      name: "execution_authorization",
      status: "NO-GO",
      satisfied: false,
      configurable: false,
      evidence_class: "hard_coded_product_boundary",
      evidence_state: "product_boundary",
      execution_allowed: false,
    },
  ],
) {
  return {
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
      release_gates: releaseGates,
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("loadPublicReport", () => {
  it("loads the public summary change alongside the research report", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify(publishedReport()),
          {
            status: 200,
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            change: {
              current_observed_at: "2026-08-02T08:00:00Z",
              status: "available",
              vrp_percent_points_delta: 1.2,
            },
            captured_at: "2026-08-02T08:00:00Z",
            published_at: "2026-08-02T08:05:00Z",
            schema_version: "public_summary.v1",
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const loaded = await loadPublicReport();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "./research/report",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "./api/v1/summary.json",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(loaded.summary?.change?.vrp_percent_points_delta).toBe(1.2);
  });

  it("keeps the report available when the comparison summary is missing", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify(publishedReport()),
          {
            status: 200,
          },
        ),
      )
      .mockResolvedValueOnce(new Response("not found", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const loaded = await loadPublicReport();

    expect(loaded.report.schema_version).toBe("research_report.v1");
    expect(loaded.summary).toBeNull();
  });

  it("fails closed when a public report weakens research-only published invariants", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(
        JSON.stringify(
          publishedReport([
            { name: "research_publication", status: "GO", satisfied: true },
            {
              name: "execution_authorization",
              status: "GO",
              satisfied: true,
            },
          ]),
        ),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadPublicReport()).rejects.toThrow(/release gates.*fail-closed/i);
  });

  it("requires the complete blocked-output contract", async () => {
    const report = publishedReport();
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...report,
          blocked_outputs: [
            "trade_recommendation",
            "recommended_size",
            "order_instructions",
            "unrelated_output",
          ],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadPublicReport()).rejects.toThrow(/safety boundary/i);
  });

  it("requires a separate closed product-boundary gate", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(
        JSON.stringify(
          publishedReport([
            { name: "research_publication", status: "GO", satisfied: true },
          ]),
        ),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadPublicReport()).rejects.toThrow(/release gates.*fail-closed/i);
  });

  it("gives operators a concrete recovery action for an invalid report", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        new Response(JSON.stringify({ schema_version: "unexpected" }), {
          status: 200,
        }),
      ),
    );

    await expect(loadPublicReport()).rejects.toThrow(
      /rebuild and republish the public static bundle/i,
    );
  });

  it("drops the auxiliary summary when it does not match the published edition timestamps", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify(publishedReport()),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            change: {
              current_observed_at: "2026-08-02T08:00:00Z",
              status: "available",
              vrp_percent_points_delta: 1.2,
            },
            captured_at: "2026-08-01T08:00:00Z",
            published_at: "2026-08-02T08:05:00Z",
            schema_version: "public_summary.v1",
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const loaded = await loadPublicReport();

    expect(loaded.summary).toBeNull();
  });
});
