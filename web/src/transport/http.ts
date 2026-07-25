import type { ResearchReport } from "../contracts";
import { validateResearchReport } from "../report";

export interface LoadedReport {
  report: ResearchReport;
  receivedAtMs: number;
  etag?: string;
  analysisRunId?: string;
  cached?: boolean;
}

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function inferCached(response: Response): boolean | undefined {
  const ageHeader = response.headers.get("Age");
  if (ageHeader) {
    const ageSeconds = Number(ageHeader);
    if (Number.isFinite(ageSeconds)) {
      return ageSeconds > 0;
    }
  }

  const cacheSignal =
    response.headers.get("X-Cache") ??
    response.headers.get("CF-Cache-Status") ??
    response.headers.get("X-Served-By");
  if (cacheSignal) {
    return /hit|cached/i.test(cacheSignal);
  }

  const cacheControl = response.headers.get("Cache-Control");
  if (cacheControl && /no-store/i.test(cacheControl)) {
    return false;
  }

  return undefined;
}

export async function loadResearchReportHttp(options?: {
  fetchImpl?: FetchLike;
  url?: string;
  init?: RequestInit;
  receivedAtMs?: number;
}): Promise<LoadedReport> {
  const fetchImpl = options?.fetchImpl ?? globalThis.fetch;
  if (typeof fetchImpl !== "function") {
    throw new Error("fetch implementation is unavailable");
  }

  const { headers: initHeaders, ...init } = options?.init ?? {};
  const headers = new Headers(initHeaders);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  const response = await fetchImpl(options?.url ?? "/research/report", {
    ...init,
    method: "GET",
    body: undefined,
    cache: "no-store",
    headers,
  });

  if (!response.ok) {
    throw new Error(`report request failed with ${response.status}`);
  }

  const payload: unknown = await response.json();
  const report = validateResearchReport(payload);

  return {
    report,
    receivedAtMs: options?.receivedAtMs ?? Date.now(),
    etag: response.headers.get("ETag") ?? undefined,
    analysisRunId:
      response.headers.get("X-Analysis-Run-ID") ?? undefined,
    cached: inferCached(response),
  };
}
