import { afterEach, describe, expect, it, vi } from "vitest";
import { buildLoadedReport } from "../report/testFixtures";
import { chromeSidePanelRuntime } from "./runtime";

afterEach(() => vi.unstubAllGlobals());

describe("side panel runtime origin binding", () => {
  it("rejects a response whose origin differs from the requested engine", async () => {
    const sendMessage = vi.fn().mockResolvedValue({
      ok: true, origin: "http://localhost:8123", loaded: buildLoadedReport(),
    });
    vi.stubGlobal("chrome", { runtime: { sendMessage } });
    await expect(chromeSidePanelRuntime.getReport(true, "http://127.0.0.1:8000"))
      .rejects.toMatchObject({ kind: "aborted" });
    expect(sendMessage).toHaveBeenCalledWith({
      type: "REPORT_GET", force: true, expectedOrigin: "http://127.0.0.1:8000",
    });
    expect(await chromeSidePanelRuntime.getCachedReport("http://127.0.0.1:8000")).toBeNull();
  });

  it("rejects a non-loopback origin before it can become a panel link", async () => {
    vi.stubGlobal("chrome", { runtime: { sendMessage: vi.fn().mockResolvedValue({
      ok: true, origin: "https://example.com:8123",
    }) } });
    await expect(chromeSidePanelRuntime.getEngineOrigin()).rejects.toThrow(/loopback/);
  });
});
