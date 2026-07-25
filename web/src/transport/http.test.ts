import { describe, expect, it, vi } from "vitest";

import { safeResearchReport } from "../report/testFixtures";
import { loadResearchReportHttp } from "./http";

describe("loadResearchReportHttp", () => {
  it("loads and envelopes a validated report with transport metadata", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(safeResearchReport), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "ETag": "\"hash-1\"",
          "X-Analysis-Run-ID": "analysis:123",
          "Cache-Control": "no-store, max-age=0",
        },
      }),
    );

    const loaded = await loadResearchReportHttp({
      fetchImpl,
      url: "http://127.0.0.1:8000/research/report",
      receivedAtMs: 1_234,
      init: {
        method: "POST",
        cache: "force-cache",
        headers: { "X-Trace": "research-test" },
      },
    });

    const [url, requestInit] = fetchImpl.mock.calls[0] as [
      string,
      RequestInit,
    ];
    const requestHeaders = new Headers(requestInit.headers);
    expect(url).toBe("http://127.0.0.1:8000/research/report");
    expect(requestInit.method).toBe("GET");
    expect(requestInit.body).toBeUndefined();
    expect(requestInit.cache).toBe("no-store");
    expect(requestHeaders.get("Accept")).toBe("application/json");
    expect(requestHeaders.get("X-Trace")).toBe("research-test");
    expect(loaded.report.schema_version).toBe("research_report.v1");
    expect(loaded.receivedAtMs).toBe(1_234);
    expect(loaded.etag).toBe("\"hash-1\"");
    expect(loaded.analysisRunId).toBe("analysis:123");
    expect(loaded.cached).toBe(false);
  });

  it("fails closed on a weakened payload", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...safeResearchReport,
          mode_gate: {
            ...safeResearchReport.mode_gate,
            trade_recommendation_allowed: true,
          },
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    await expect(
      loadResearchReportHttp({ fetchImpl }),
    ).rejects.toThrow(/safety boundary/i);
  });
});
