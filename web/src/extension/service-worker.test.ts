import { describe, expect, it } from "vitest";
import type { ResearchReport } from "../contracts";
import type { ExtensionMessage } from "./messages";
import { createExtensionWorkerController } from "./service-worker";
import type { LoadedReport } from "../transport";

const safeReport: ResearchReport = {
  schema_version: "research_report.v1",
  action: "RESEARCH_ONLY",
  mode: "research_only",
  effective_mode: "research_only",
  blocked_outputs: [
    "trade_recommendation",
    "recommended_size",
    "order_instructions",
    "paper_manual_trade_candidates",
  ],
  mode_gate: {
    trade_recommendation_allowed: false,
    recommended_size_allowed: false,
    order_instructions_allowed: false,
    paper_manual_candidates_allowed: false,
  },
  full_system_surface: {
    release_readiness: {
      status: "NO-GO",
    },
  },
  strategy_research: {
    schema_version: "strategy_research.v1",
    execution_allowed: false,
    playbook: {
      risk_budget: {
        contracts: null,
      },
    },
  },
};

describe("createExtensionWorkerController", () => {
  it("fetches only the fixed report endpoint and caches the validated payload", async () => {
    const fetchCalls: string[] = [];
    const session = new Map<string, unknown>();
    const local = new Map<string, unknown>();

    const controller = createExtensionWorkerController({
      loadReport: async (origin) => {
        fetchCalls.push(origin);
        const loaded: LoadedReport = {
          report: {
            ...safeReport,
            evidence_lineage: {
              raw_payload: "must remain inside the worker HTTP boundary",
            },
          } as ResearchReport,
          receivedAtMs: 1721865600000,
          etag: "\"etag-1\"",
          analysisRunId: "analysis-1",
          cached: false,
        };
        return loaded;
      },
      readSession: async <T>(key: string) => session.get(key) as T | undefined,
      writeSession: async (key, value) => {
        session.set(key, value);
      },
      readLocal: async <T>(key: string) => local.get(key) as T | undefined,
      writeLocal: async (key, value) => {
        local.set(key, value);
      },
      setSidePanelOptions: async () => undefined,
    });

    const response = await controller.handleMessage({
      type: "REPORT_GET",
      force: true,
    });

    if (!response.ok || !("loaded" in response) || !response.loaded) {
      throw new Error("expected loaded report response");
    }
    expect(fetchCalls).toEqual(["http://127.0.0.1:8000"]);
    expect(response.loaded.report.schema_version).toBe("research_report.v1");
    expect("evidence_lineage" in response.loaded.report).toBe(false);
    expect(response.loaded.analysisRunId).toBe("analysis-1");
    expect(session.get("panelReport")).toMatchObject({
      origin: "http://127.0.0.1:8000",
      loaded: {
        analysisRunId: "analysis-1",
      },
    });
  });

  it("keeps Deribit context isolated by tab and resolves the active tab", async () => {
    const session = new Map<string, unknown>();
    let activeTabId = 101;
    const controller = createExtensionWorkerController({
      loadReport: async () => ({
        report: safeReport,
        receivedAtMs: 1721865600000,
      }),
      readSession: async <T>(key: string) =>
        session.get(key) as T | undefined,
      writeSession: async (key, value) => {
        session.set(key, value);
      },
      readLocal: async <T>() => undefined as T | undefined,
      writeLocal: async () => undefined,
      getActiveTabId: async () => activeTabId,
      setSidePanelOptions: async () => undefined,
    });
    const firstContext = {
      href: "https://www.deribit.com/options/BTC?instrument=BTC-7AUG26-71000-C",
      route: "/options/BTC",
      source: "url" as const,
      confidence: "url" as const,
      instrument: "BTC-7AUG26-71000-C",
      underlying: "BTC",
      detectedAt: 1,
    };
    const secondContext = {
      ...firstContext,
      href: "https://www.deribit.com/options/ETH?instrument=ETH-7AUG26-4000-C",
      instrument: "ETH-7AUG26-4000-C",
      underlying: "ETH",
      detectedAt: 2,
    };

    await controller.handleMessage(
      { type: "DERIBIT_CONTEXT_UPDATE", context: firstContext },
      { tab: { id: 101 } },
    );
    await controller.handleMessage(
      { type: "DERIBIT_CONTEXT_UPDATE", context: secondContext },
      { tab: { id: 202 } },
    );

    expect(await controller.handleMessage({ type: "CONTEXT_GET" })).toEqual({
      ok: true,
      context: firstContext,
    });
    activeTabId = 202;
    expect(await controller.handleMessage({ type: "CONTEXT_GET" })).toEqual({
      ok: true,
      context: secondContext,
    });
    expect(session.get("deribitContext:101")).toEqual(firstContext);
    expect(session.get("deribitContext:202")).toEqual(secondContext);
    expect(session.has("deribitContext")).toBe(false);
  });

  it("stores only validated loopback origins", async () => {
    const local = new Map<string, unknown>();
    const controller = createExtensionWorkerController({
      loadReport: async () => ({
        report: safeReport,
        receivedAtMs: 1721865600000,
      }),
      readSession: async () => undefined,
      writeSession: async () => undefined,
      readLocal: async <T>(key: string) => local.get(key) as T | undefined,
      writeLocal: async (key, value) => {
        local.set(key, value);
      },
      setSidePanelOptions: async () => undefined,
    });

    const good = await controller.handleMessage({
      type: "ENGINE_CONFIG_SET",
      origin: "http://localhost:8123/",
    });
    if (!good.ok || !("origin" in good) || typeof good.origin !== "string") {
      throw new Error("expected origin response");
    }
    expect(good.origin).toBe("http://localhost:8123");

    const bad = await controller.handleMessage({
      type: "ENGINE_CONFIG_SET",
      origin: "https://example.com",
    });
    if (bad.ok) {
      throw new Error("expected loopback validation failure");
    }
    expect(String(bad.error)).toMatch(/loopback/i);
  });

  it("rejects unknown messages at the finite boundary", async () => {
    const controller = createExtensionWorkerController({
      loadReport: async () => ({
        report: safeReport,
        receivedAtMs: 1721865600000,
      }),
      readSession: async () => undefined,
      writeSession: async () => undefined,
      readLocal: async <T>() => undefined as T | undefined,
      writeLocal: async () => undefined,
      setSidePanelOptions: async () => undefined,
    });

    const response = await controller.handleMessage({
      type: "NOT_ALLOWED",
    } as unknown as ExtensionMessage);

    if (response.ok) {
      throw new Error("expected unsupported message failure");
    }
    expect(String(response.error)).toMatch(/unsupported/i);
  });

  it("refuses to cache an unsafe loaded report envelope", async () => {
    const session = new Map<string, unknown>();
    const controller = createExtensionWorkerController({
      loadReport: async () => ({
        report: {
          ...safeReport,
          mode_gate: {
            ...safeReport.mode_gate,
            trade_recommendation_allowed: true,
          },
        },
        receivedAtMs: Number.NaN,
      }),
      readSession: async <T>() => undefined as T | undefined,
      writeSession: async (key, value) => {
        session.set(key, value);
      },
      readLocal: async <T>() => undefined as T | undefined,
      writeLocal: async () => undefined,
      setSidePanelOptions: async () => undefined,
    });

    const response = await controller.handleMessage({
      type: "REPORT_GET",
      force: true,
    });

    if (response.ok) {
      throw new Error("expected unsafe report rejection");
    }
    expect(String(response.error)).toMatch(/finite receivedAtMs|safety boundary/i);
    expect(session.has("panelReport")).toBe(false);
  });

  it("revalidates session cache before returning it", async () => {
    const session = new Map<string, unknown>([
      [
        "panelReport",
        {
          origin: "http://127.0.0.1:8000",
          loaded: {
            report: {
              ...safeReport,
              full_system_surface: {
                release_readiness: { status: "GO" },
              },
            },
            receivedAtMs: 1721865600000,
          },
        },
      ],
    ]);
    const controller = createExtensionWorkerController({
      loadReport: async () => {
        throw new Error("cache validation should happen before HTTP");
      },
      readSession: async <T>(key: string) =>
        session.get(key) as T | undefined,
      writeSession: async () => undefined,
      readLocal: async <T>() => undefined as T | undefined,
      writeLocal: async () => undefined,
      setSidePanelOptions: async () => undefined,
    });

    const response = await controller.handleMessage({ type: "REPORT_GET" });

    expect(response.ok).toBe(false);
    if (response.ok) {
      throw new Error("expected cached report validation failure");
    }
    expect(response.error).toMatch(/safety boundary/i);
  });

  it("serves the cached report without touching the network for REPORT_GET_CACHED_ONLY", async () => {
    const fetchCalls: string[] = [];
    const session = new Map<string, unknown>();
    const local = new Map<string, unknown>();
    const controller = createExtensionWorkerController({
      loadReport: async (origin) => {
        fetchCalls.push(origin);
        return { report: safeReport, receivedAtMs: 1721865600000 };
      },
      readSession: async <T>(key: string) => session.get(key) as T | undefined,
      writeSession: async (key, value) => {
        session.set(key, value);
      },
      readLocal: async <T>(key: string) => local.get(key) as T | undefined,
      writeLocal: async (key, value) => {
        local.set(key, value);
      },
      setSidePanelOptions: async () => undefined,
    });

    const miss = await controller.handleMessage({
      type: "REPORT_GET_CACHED_ONLY",
    });
    expect(miss).toEqual({ ok: true, origin: "http://127.0.0.1:8000" });
    expect(fetchCalls).toEqual([]);

    await controller.handleMessage({ type: "REPORT_GET" });
    expect(fetchCalls).toEqual(["http://127.0.0.1:8000"]);

    const hit = await controller.handleMessage({
      type: "REPORT_GET_CACHED_ONLY",
    });
    if (!hit.ok || !("loaded" in hit) || !hit.loaded) {
      throw new Error("expected a cached report hit");
    }
    expect(hit.loaded.report.schema_version).toBe("research_report.v1");
    expect(hit.fromCache).toBe(true);
    // Still no additional network access from the cached-only read path.
    expect(fetchCalls).toEqual(["http://127.0.0.1:8000"]);
  });

  it("never reuses a cached report after the engine origin changes", async () => {
    const fetchCalls: string[] = [];
    const session = new Map<string, unknown>();
    const local = new Map<string, unknown>();
    const controller = createExtensionWorkerController({
      loadReport: async (origin) => {
        fetchCalls.push(origin);
        return {
          report: safeReport,
          receivedAtMs: 1721865600000 + fetchCalls.length,
          analysisRunId: `analysis-${fetchCalls.length}`,
        };
      },
      readSession: async <T>(key: string) =>
        session.get(key) as T | undefined,
      writeSession: async (key, value) => {
        session.set(key, value);
      },
      readLocal: async <T>(key: string) => local.get(key) as T | undefined,
      writeLocal: async (key, value) => {
        local.set(key, value);
      },
      setSidePanelOptions: async () => undefined,
    });

    await controller.handleMessage({ type: "REPORT_GET" });
    await controller.handleMessage({
      type: "ENGINE_CONFIG_SET",
      origin: "http://localhost:8123",
    });
    const response = await controller.handleMessage({ type: "REPORT_GET" });

    expect(fetchCalls).toEqual([
      "http://127.0.0.1:8000",
      "http://localhost:8123",
    ]);
    expect(response).toMatchObject({
      ok: true,
      origin: "http://localhost:8123",
      loaded: {
        analysisRunId: "analysis-2",
        cached: false,
      },
      fromCache: false,
    });
  });
});
