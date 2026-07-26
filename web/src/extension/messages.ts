import type { LoadedReport } from "../transport";

export interface DeribitContext {
  href: string;
  route: string;
  source: "url" | "dom" | "manual" | "unknown";
  /**
   * Independent trust signal alongside `source`. `url` is strongest (an
   * explicit instrument query/hash/path token); `dom_structural` comes from
   * selectors Deribit marks as instrument-identifying; `dom_heuristic` comes
   * from a generic heading/body-text scan; `none` means no instrument was
   * detected, or a DOM-derived guess disagreed with the URL's own underlying
   * and was dropped.
   */
  confidence: "url" | "dom_structural" | "dom_heuristic" | "none";
  instrument: string | null;
  underlying: string | null;
  detectedAt: number;
}

export interface EngineConfig {
  origin: string;
}

export type ExtensionMessage =
  | { type: "REPORT_GET"; force?: boolean }
  | { type: "REPORT_GET_CACHED_ONLY" }
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
