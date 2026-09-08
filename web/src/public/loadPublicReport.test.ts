import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

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
    data_status: {
      ...safeResearchReport.data_status,
      source: "deribit_published_snapshot",
    },
    data_trust: {
      ...safeResearchReport.data_trust,
      source_class: "published_snapshot",
    },
    strategy_research: {
      ...safeResearchReport.strategy_research!,
      collection: {
        ...safeResearchReport.strategy_research?.collection,
        source: "deribit_published_snapshot",
      },
    },
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
  vi.useRealTimers();
});

describe("loadPublicReport", () => {
  it.each(["ready", "missing", "degraded"])("accepts shared %s evidence under a valid publication clock", async (state) => {
    const fixture = JSON.parse(readFileSync(resolve(process.cwd(), "../tests/fixtures/public_contract", `${state}.json`), "utf8"));
    // Missing/degraded fixtures describe projection shape without a publication
    // clock. Attach a valid edition to test their nullable evidence branches.
    const envelope = publishedReport();
    const report = {
      ...fixture.ResearchReport,
      runtime_context: envelope.runtime_context,
      publish_edition: envelope.publish_edition,
    };
    const summary = { ...fixture.Summary, captured_at: envelope.publish_edition.captured_at, published_at: envelope.publish_edition.published_at };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(report)))
      .mockResolvedValueOnce(new Response(JSON.stringify(summary))));
    const loaded = await loadPublicReport();
    expect(loaded.report.schema_version).toBe("research_report.v1");
    expect(loaded.summary).not.toBeNull();
  });

  it.each([
    ["source object", { data_status: { source: {} } }],
    ["live source", { data_status: { source: "deribit_live:https://www.deribit.com", validated: true } }],
    ["false source classification", { data_trust: { source_class: "validated" } }],
    ["surface object", { vol_surface_status: { expiries: {} } }],
    ["surface null row", { vol_surface_status: { expiries: [null] } }],
    ["surface points object", { vol_surface_status: { expiries: [{ surface_points: {} }] } }],
    ["candidate object", { candidate_research: { call_credit_spreads: { eligible: {} } } }],
    ["candidate child object", { candidate_research: { naked_short_calls: { eligible: [{ instrument_name: {} }] } } }],
    ["candidate count object", { candidate_research: { summary: { eligible_naked_short_calls: {} } } }],
    ["negative count", { candidate_research: { summary: { eligible_naked_short_calls: -1 } } }],
    ["reason-code object", { reason_codes: [{}] }],
    ["vrp series object", { vrp_status: { series: {} } }],
    ["vrp null point", { vrp_status: { series: [null] } }],
    ["vrp band object", { vrp_status: { status: "validated", band: {} } }],
    ["vrp percentile out of range", { vrp_status: { percentile: 1.1 } }],
    ["vrp string number", { vrp_status: { current_vrp_percent_points: "10" } }],
    ["invalid leap day", { vrp_status: { series: [{ observed_at: "2026-02-29T08:00:00Z" }] } }],
    ["generated date without zone", { generated_at: "2026-08-02T08:00:00" }],
    ["object in place of section", { event_status: [] }],
  ])("rejects malformed published consumer data: %s", async (_label, override) => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ ...publishedReport(), ...override })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadPublicReport()).rejects.toMatchObject({ kind: "invalid" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["non-calendar date", "2026-02-30T08:00:00Z", "2026-03-03T08:00:00Z", "2026-03-04T08:00:00Z"],
    ["unqualified date", "2026-08-02 08:00:00", "2026-08-03T08:00:00Z", "2026-08-04T08:00:00Z"],
    ["future date", "9999-08-02T08:00:00Z", "9999-08-03T08:00:00Z", "9999-08-04T08:00:00Z"],
  ])("rejects a publication clock with %s", async (_label, captured, expected, stale) => {
    const report = publishedReport();
    report.runtime_context.evaluation_clock = captured;
    report.publish_edition = {
      ...report.publish_edition, captured_at: captured, published_at: captured,
      next_expected_at: expected, stale_after: stale,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(report))));
    await expect(loadPublicReport()).rejects.toMatchObject({ kind: "invalid" });
  });

  it("rejects non-finite JSON numbers instead of treating the payload as current evidence", async () => {
    const body = JSON.stringify({ ...publishedReport(), vrp_status: { current_vrp_percent_points: "overflow" } })
      .replace('"overflow"', "1e999");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(body)));
    await expect(loadPublicReport()).rejects.toMatchObject({ kind: "invalid" });
  });

  it.each([
    { change: [] },
    { change: { status: "available", band_changed: "false", vrp_percent_points_delta: 1.2 } },
    { change: { current_observed_at: {} } },
    { change: { prior_observed_at: "2026-02-30T08:00:00Z" } },
    { change: { vrp_percent_points_delta: "1.2" } },
    { vrp: { band: {} } },
    { vrp: { percentile: 5 } },
  ])("drops malformed auxiliary summary without losing valid report: %j", async (override) => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(publishedReport())))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        schema_version: "public_summary.v1",
        captured_at: "2026-08-02T08:00:00Z",
        published_at: "2026-08-02T08:05:00Z",
        ...override,
      }))));
    const loaded = await loadPublicReport();
    expect(loaded.report.schema_version).toBe("research_report.v1");
    expect(loaded.summary).toBeNull();
  });

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

    await expect(loadPublicReport()).rejects.toMatchObject({ kind: "invalid" });
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

    await expect(loadPublicReport()).rejects.toMatchObject({ kind: "invalid" });
  });

  it("classifies invalid public reports for safe recovery guidance in the page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        new Response(JSON.stringify({ schema_version: "unexpected" }), {
          status: 200,
        }),
      ),
    );

    await expect(loadPublicReport()).rejects.toMatchObject({ kind: "invalid" });
  });

  it("times out a public report whose body never completes", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: () => new Promise(() => undefined),
    }));
    const pending = loadPublicReport(undefined, undefined, { timeoutMs: 100 });
    const rejected = expect(pending).rejects.toMatchObject({ kind: "timeout" });
    await vi.advanceTimersByTimeAsync(100);
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("returns verified evidence when its optional summary stalls without resetting report age", async () => {
    vi.useFakeTimers();
    const receivedAtMs = Date.now();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(publishedReport())))
      .mockResolvedValueOnce({ ok: true, json: () => new Promise(() => undefined) }));
    const pending = loadPublicReport(undefined, undefined, { timeoutMs: 100 });
    await vi.advanceTimersByTimeAsync(101);
    const loaded = await pending;
    expect(loaded.summary).toBeNull();
    expect(loaded.receivedAtMs).toBe(receivedAtMs);
    expect(vi.getTimerCount()).toBe(0);
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
