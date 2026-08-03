import type { ResearchReport } from "../contracts";

export interface LoadedPublicReport {
  report: ResearchReport;
  receivedAtMs: number;
  summary: PublicReleaseSummary | null;
}

export interface PublicSummaryChange {
  band_changed?: boolean | null;
  current_observed_at?: string | null;
  percentile_delta?: number | null;
  prior_observed_at?: string | null;
  status?: string;
  vrp_percent_points_delta?: number | null;
}

export interface PublicReleaseSummary {
  change?: PublicSummaryChange;
  schema_version: "public_summary.v1";
  vrp?: {
    band?: string | null;
    percentile?: number | null;
    vrp_percent_points?: number | null;
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function loadPublicSummary(
  url: string,
): Promise<PublicReleaseSummary | null> {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
      },
    });
    if (!response.ok) {
      return null;
    }
    const payload: unknown = await response.json();
    if (!isRecord(payload) || payload.schema_version !== "public_summary.v1") {
      return null;
    }
    return payload as unknown as PublicReleaseSummary;
  } catch {
    return null;
  }
}

export async function loadPublicReport(
  url = "./research/report",
  summaryUrl = "./api/v1/summary.json",
): Promise<LoadedPublicReport> {
  const response = await fetch(url, {
    cache: "no-store",
    headers: {
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    throw new Error(`public report request failed with ${response.status}`);
  }

  const payload: unknown = await response.json();
  if (!isRecord(payload) || payload.schema_version !== "research_report.v1") {
    throw new Error("public report payload is invalid");
  }

  return {
    report: payload as unknown as ResearchReport,
    receivedAtMs: Date.now(),
    summary: await loadPublicSummary(summaryUrl),
  };
}
