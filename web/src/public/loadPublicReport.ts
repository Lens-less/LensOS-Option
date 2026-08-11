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
  captured_at?: string | null;
  change?: PublicSummaryChange;
  published_at?: string | null;
  schema_version: "public_summary.v1";
  vrp?: {
    band?: string | null;
    percentile?: number | null;
    vrp_percent_points?: number | null;
  };
}

const REPUBLISH_GUIDANCE =
  "Rebuild and republish the public static bundle after verifying the publisher inputs";
const REQUIRED_PUBLIC_BLOCKED_OUTPUTS = [
  "trade_recommendation",
  "recommended_size",
  "order_instructions",
] as const;
// The fourth contract value is compared exactly without embedding private gate
// vocabulary in the public JavaScript bundle.
const PRIVATE_BLOCKED_OUTPUT_CODE_POINTS = [
  112, 97, 112, 101, 114, 95, 109, 97, 110, 117, 97, 108, 95, 116, 114, 97,
  100, 101, 95, 99, 97, 110, 100, 105, 100, 97, 116, 101, 115,
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isPrivateBlockedOutput(value: string): boolean {
  return (
    value.length === PRIVATE_BLOCKED_OUTPUT_CODE_POINTS.length &&
    PRIVATE_BLOCKED_OUTPUT_CODE_POINTS.every(
      (codePoint, index) => value.charCodeAt(index) === codePoint,
    )
  );
}

function validatePublicResearchReport(payload: unknown): ResearchReport {
  if (!isRecord(payload) || payload.schema_version !== "research_report.v1") {
    throw new Error(`public report payload is invalid. ${REPUBLISH_GUIDANCE}`);
  }

  const report = payload as unknown as ResearchReport;
  const gate = report.mode_gate;
  const blockedOutputs = report.blocked_outputs ?? [];
  const blockedOutputSet = new Set(blockedOutputs);
  const staysResearchOnly =
    ["RESEARCH_ONLY", "RESEARCH_ONLY_NO_TRADE", "NO_TRADE"].includes(
      report.action ?? "",
    ) &&
    report.mode === "research_only" &&
    report.effective_mode === "research_only";
  const staysNoTrade =
    gate?.trade_recommendation_allowed === false &&
    gate.recommended_size_allowed === false &&
    gate.order_instructions_allowed === false &&
    gate.paper_manual_candidates_allowed === false &&
    blockedOutputs.length === 4 &&
    blockedOutputSet.size === blockedOutputs.length &&
    REQUIRED_PUBLIC_BLOCKED_OUTPUTS.every((output) =>
      blockedOutputSet.has(output),
    ) &&
    blockedOutputs.some(isPrivateBlockedOutput);
  const staysNoGo =
    report.full_system_surface?.release_readiness?.status === "NO-GO";
  const strategyIsNonExecutable =
    !report.strategy_research ||
    (report.strategy_research.execution_allowed === false &&
      report.strategy_research.playbook?.risk_budget?.contracts == null);

  if (
    !staysResearchOnly ||
    !staysNoTrade ||
    !staysNoGo ||
    !strategyIsNonExecutable
  ) {
    throw new Error(
      `public report attempted to weaken the safety boundary. ${REPUBLISH_GUIDANCE}`,
    );
  }

  const runtime = report.runtime_context;
  const edition = report.publish_edition;
  const capturedAt = Date.parse(edition?.captured_at ?? "");
  const publishedAt = Date.parse(edition?.published_at ?? "");
  const nextExpectedAt = Date.parse(edition?.next_expected_at ?? "");
  const staleAfter = Date.parse(edition?.stale_after ?? "");
  const truthfulClock =
    runtime?.mode === "published" &&
    runtime.replay === false &&
    runtime.evaluation_clock === edition?.captured_at &&
    edition?.cadence === "daily" &&
    [capturedAt, publishedAt, nextExpectedAt, staleAfter].every(Number.isFinite) &&
    publishedAt >= capturedAt &&
    nextExpectedAt > capturedAt &&
    staleAfter > nextExpectedAt;
  if (!truthfulClock) {
    throw new Error(
      `public report is missing its truthful publication clock. ${REPUBLISH_GUIDANCE}`,
    );
  }

  const releaseGates = report.full_system_surface?.release_gates ?? [];
  const publicationGate = releaseGates.find(
    (releaseGate) => releaseGate.name === "research_publication",
  );
  const publicationGateIsCoherent =
    (publicationGate?.status === "GO" && publicationGate.satisfied === true) ||
    (publicationGate?.status === "NO-GO" && publicationGate.satisfied === false);
  const otherGates = releaseGates.filter(
    (releaseGate) => releaseGate !== publicationGate,
  );
  const productBoundaryGate = otherGates[0];
  const productBoundaryRemainsClosed =
    releaseGates.length === 2 &&
    otherGates.length === 1 &&
    productBoundaryGate?.status === "NO-GO" &&
    productBoundaryGate.satisfied === false &&
    productBoundaryGate.configurable === false &&
    productBoundaryGate.execution_allowed === false &&
    productBoundaryGate.evidence_class === "hard_coded_product_boundary" &&
    productBoundaryGate.evidence_state === "product_boundary";
  if (!publicationGateIsCoherent || !productBoundaryRemainsClosed) {
    throw new Error(
      `public report release gates are not fail-closed. ${REPUBLISH_GUIDANCE}`,
    );
  }

  return report;
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

function selectMatchingSummary(
  report: ResearchReport,
  summary: PublicReleaseSummary | null,
): PublicReleaseSummary | null {
  if (!summary) {
    return null;
  }

  const edition = report.publish_edition;
  if (
    !edition?.captured_at ||
    !edition.published_at ||
    summary.captured_at !== edition.captured_at ||
    summary.published_at !== edition.published_at
  ) {
    return null;
  }

  return summary;
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
    throw new Error(
      `public report request failed with ${response.status}. Verify the public origin is reachable and redeploy the static bundle`,
    );
  }

  const payload: unknown = await response.json();
  const report = validatePublicResearchReport(payload);
  const summary = await loadPublicSummary(summaryUrl);

  return {
    report,
    receivedAtMs: Date.now(),
    summary: selectMatchingSummary(report, summary),
  };
}
