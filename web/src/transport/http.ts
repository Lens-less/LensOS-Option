import type { ResearchReport } from "../contracts";
import { validateResearchReport } from "../report";
import { ReportLoadError, requestJson, type FetchLike } from "./requestJson";

export type { FetchLike } from "./requestJson";

export interface LoadedReport {
  report: ResearchReport;
  receivedAtMs: number;
  etag?: string;
  analysisRunId?: string;
  cached?: boolean;
}

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
  timeoutMs?: number;
}): Promise<LoadedReport> {
  const { response, payload } = await requestJson(options?.url ?? "/research/report", options);
  let report: ResearchReport;
  try {
    report = validateResearchReport(payload);
  } catch {
    throw new ReportLoadError("invalid");
  }

  return {
    report,
    receivedAtMs: options?.receivedAtMs ?? Date.now(),
    etag: response.headers.get("ETag") ?? undefined,
    analysisRunId:
      response.headers.get("X-Analysis-Run-ID") ?? undefined,
    cached: inferCached(response),
  };
}
