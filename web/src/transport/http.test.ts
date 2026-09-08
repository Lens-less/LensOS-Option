import { afterEach, describe, expect, it, vi } from "vitest";

import { safeResearchReport } from "../report/testFixtures";
import { loadResearchReportHttp } from "./http";

describe("loadResearchReportHttp", () => {
  afterEach(() => vi.useRealTimers());

  it.each(["fetch", "body"])("bounds the entire %s wait and aborts its request", async (phase) => {
    vi.useFakeTimers();
    const never = new Promise<Response>(() => undefined);
    const fetchImpl = vi.fn().mockImplementation(() => phase === "fetch"
      ? never
      : Promise.resolve({ ok: true, json: () => never }));
    const pending = loadResearchReportHttp({ fetchImpl, timeoutMs: 100 });
    const rejected = expect(pending).rejects.toMatchObject({ kind: "timeout" });

    await vi.advanceTimersByTimeAsync(100);
    await rejected;
    expect(fetchImpl.mock.calls[0][1].signal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("honors cancellation during response reading even when the fetch implementation ignores it", async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: () => new Promise(() => undefined),
    });
    const pending = loadResearchReportHttp({ fetchImpl, init: { signal: controller.signal } });
    const rejected = expect(pending).rejects.toMatchObject({ kind: "aborted" });
    controller.abort(new Error("private credential must not appear"));
    await rejected;
    expect(fetchImpl.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it("does not start a cancelled request", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchImpl = vi.fn();
    await expect(loadResearchReportHttp({ fetchImpl, init: { signal: controller.signal } }))
      .rejects.toMatchObject({ kind: "aborted" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("classifies network failures without exposing exception details", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("private credential must not appear"));
    const error = await loadResearchReportHttp({ fetchImpl }).catch((failure: unknown) => failure);
    expect(error).toMatchObject({ kind: "network" });
    expect(String(error)).not.toContain("private credential");
  });

  it("classifies non-JSON responses as invalid reports without exposing response content", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response("private response content"));
    const error = await loadResearchReportHttp({ fetchImpl }).catch((failure: unknown) => failure);
    expect(error).toMatchObject({ kind: "invalid" });
    expect(String(error)).not.toContain("private response");
  });

  it("does not follow report redirects or accept an already redirected response", async () => {
    const json = vi.fn().mockResolvedValue(safeResearchReport);
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, redirected: true, json });
    await expect(loadResearchReportHttp({ fetchImpl, init: { redirect: "follow" } }))
      .rejects.toMatchObject({ kind: "invalid" });
    expect(fetchImpl.mock.calls[0][1].redirect).toBe("error");
    expect(json).not.toHaveBeenCalled();
  });

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
