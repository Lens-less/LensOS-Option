import type { LoadedReport } from "../transport";

export interface DeribitContext {
  href: string;
  route: string;
  source: "url" | "dom" | "manual" | "unknown";
  instrument: string | null;
  underlying: string | null;
  detectedAt: number;
}

export interface EngineConfig {
  origin: string;
}

export type ExtensionMessage =
  | { type: "REPORT_GET"; force?: boolean }
  | { type: "DERIBIT_CONTEXT_UPDATE"; context: DeribitContext }
  | { type: "CONTEXT_GET" }
  | { type: "ENGINE_CONFIG_GET" }
  | { type: "ENGINE_CONFIG_SET"; origin: string };

export type ExtensionResponse =
  | {
      ok: true;
      origin: string;
      loaded?: LoadedReport;
      fromCache?: boolean;
      context?: DeribitContext | null;
    }
  | {
      ok: true;
      origin?: string;
      context?: DeribitContext | null;
    }
  | { ok: false; error: string };
