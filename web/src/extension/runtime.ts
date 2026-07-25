import { validateResearchReport } from "../report";
import type {
  DeribitContext,
  ExtensionMessage,
  ExtensionResponse,
} from "./messages";
import type { LoadedReport } from "../transport";
import { buildEvidenceUrl, normalizeEngineOrigin } from "./config";

export interface SidePanelRuntime {
  getEngineOrigin(): Promise<string>;
  setEngineOrigin(origin: string): Promise<string>;
  getContext(): Promise<DeribitContext | null>;
  getReport(force?: boolean): Promise<LoadedReport>;
  getEvidenceUrl(origin: string): string;
}

declare const chrome: Chrome;

async function sendMessage(
  message: ExtensionMessage,
): Promise<ExtensionResponse> {
  return chrome.runtime.sendMessage(message) as Promise<ExtensionResponse>;
}

function ensureSuccess(response: ExtensionResponse): asserts response is Extract<
  ExtensionResponse,
  { ok: true }
> {
  if (!response.ok) {
    throw new Error(response.error);
  }
}

export const chromeSidePanelRuntime: SidePanelRuntime = {
  async getEngineOrigin(): Promise<string> {
    const response = await sendMessage({ type: "ENGINE_CONFIG_GET" });
    ensureSuccess(response);
    if (!("origin" in response) || typeof response.origin !== "string") {
      throw new Error("worker returned no engine origin");
    }
    return response.origin;
  },

  async setEngineOrigin(origin: string): Promise<string> {
    const normalized = normalizeEngineOrigin(origin);
    const response = await sendMessage({
      type: "ENGINE_CONFIG_SET",
      origin: normalized,
    });
    ensureSuccess(response);
    return response.origin ?? normalized;
  },

  async getContext(): Promise<DeribitContext | null> {
    const response = await sendMessage({ type: "CONTEXT_GET" });
    ensureSuccess(response);
    return response.context ?? null;
  },

  async getReport(force = false): Promise<LoadedReport> {
    const response = await sendMessage({ type: "REPORT_GET", force });
    ensureSuccess(response);
    if (!("loaded" in response) || !response.loaded) {
      throw new Error("worker returned no report envelope");
    }
    if (!Number.isFinite(response.loaded.receivedAtMs)) {
      throw new Error("worker returned an invalid report receipt time");
    }
    return {
      ...response.loaded,
      report: validateResearchReport(response.loaded.report),
    };
  },

  getEvidenceUrl(origin: string): string {
    return buildEvidenceUrl(origin);
  },
};
