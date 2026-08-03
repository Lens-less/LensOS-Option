import type {
  CallCreditSpreadCandidate,
  ResearchReport,
  VrpStatusPoint,
} from "../contracts";
import type { NakedCallCandidate } from "../contracts";

export type PublicView = "evidence" | "series" | "signal";

export type FreshnessPhase = "current" | "warning" | "expired" | "unavailable";

export interface PublicFreshness {
  ageSec: number | null;
  capturedAt?: string | null;
  maxAgeSec: number;
  mode: string;
  phase: FreshnessPhase;
  publishedAt?: string | null;
  staleAfter?: string | null;
}

type CandidateKind = "naked" | "spread";

export interface CandidateRow {
  contract: string;
  delta: number | null;
  expiry: string | null;
  id: string;
  kind: CandidateKind;
  premium: number | null;
  quality: number | null;
  noArbPass: boolean | null;
}

export interface PublicMarketFacts {
  dvol: number | null;
  eligibleExpiries: number | null;
  evaluatedExpiries: number | null;
  nakedCandidates: number | null;
  source: string;
  spreadCandidates: number | null;
  totalQuotes: number | null;
  underlyingPrice: number | null;
  validQuotes: number | null;
}

export function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function selectPublicFreshness(
  report: ResearchReport,
  receivedAtMs: number,
  nowMs: number,
): PublicFreshness {
  if (
    report.runtime_context?.mode === "published" &&
    report.publish_edition?.captured_at
  ) {
    const capturedAtMs = Date.parse(report.publish_edition.captured_at);
    const staleAfterMs = report.publish_edition.stale_after
      ? Date.parse(report.publish_edition.stale_after)
      : Number.NaN;
    if (Number.isFinite(capturedAtMs)) {
      const ageSec = Math.max(0, Math.floor((nowMs - capturedAtMs) / 1_000));
      const maxAgeSec =
        Number.isFinite(staleAfterMs) && staleAfterMs > capturedAtMs
          ? Math.max(1, Math.floor((staleAfterMs - capturedAtMs) / 1_000))
          : 48 * 60 * 60;
      const warningAgeSec = Math.max(1, Math.floor(maxAgeSec * 0.75));
      return {
        ageSec,
        capturedAt: report.publish_edition.captured_at,
        maxAgeSec,
        mode: "published",
        phase:
          ageSec >= maxAgeSec
            ? "expired"
            : ageSec >= warningAgeSec
              ? "warning"
              : "current",
        publishedAt: report.publish_edition.published_at ?? null,
        staleAfter: report.publish_edition.stale_after ?? null,
      };
    }
  }

  const reportedAge = report.data_status?.market_data_age_sec;
  const configuredMaxAge =
    report.data_status?.quality_gate?.thresholds?.market_data_max_age_sec;
  const maxAgeSec =
    typeof configuredMaxAge === "number" &&
    Number.isFinite(configuredMaxAge) &&
    configuredMaxAge > 0
      ? configuredMaxAge
      : 60;

  if (
    typeof reportedAge !== "number" ||
    !Number.isFinite(reportedAge) ||
    reportedAge < 0
  ) {
    return {
      ageSec: null,
      maxAgeSec,
      mode: report.runtime_context?.mode ?? "live",
      phase: "unavailable",
    };
  }

  const elapsedSec = Math.max(0, nowMs - receivedAtMs) / 1_000;
  const ageSec = Math.floor(reportedAge + elapsedSec);
  const warningAgeSec = Math.min(45, maxAgeSec);

  return {
    ageSec,
    maxAgeSec,
    mode: report.runtime_context?.mode ?? "live",
    phase:
      ageSec >= maxAgeSec
        ? "expired"
        : ageSec >= warningAgeSec
          ? "warning"
          : "current",
  };
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "未提供生成时间";
  }
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "Asia/Shanghai",
  }).format(parsed);
}

export function formatCutoffTime(value: string | null | undefined): string {
  if (!value) {
    return "截止时间未提供";
  }
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(parsed);
}

export function formatPublishedAge(ageSec: number | null | undefined): string {
  if (ageSec === null || ageSec === undefined) {
    return "距今时间不可验证";
  }
  return `距今 ${formatDurationHours(ageSec)}`;
}

export function formatDurationHours(durationSec: number): string {
  if (!Number.isFinite(durationSec) || durationSec < 0) {
    return "时长不可验证";
  }
  if (durationSec < 3_600) {
    return "不足 1 小时";
  }
  const hours = durationSec / 3_600;
  const maximumFractionDigits = hours < 24 && !Number.isInteger(hours) ? 1 : 0;
  return `${hours.toLocaleString("zh-CN", { maximumFractionDigits })} 小时`;
}

export function formatExpiry(value: string | null): string {
  if (!value) {
    return "到期日未提供";
  }
  const parsed = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(parsed)) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}

export function formatUsd(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 0,
    style: "currency",
  }).format(value);
}

export function formatPercent(value: number | null, digits = 1): string {
  if (value === null) {
    return "—";
  }
  const percentage = Math.abs(value) <= 2 ? value * 100 : value;
  return `${percentage.toFixed(digits)}%`;
}

export function formatDecimal(
  value: number | null,
  digits: number,
  fallback = "—",
): string {
  return value === null ? fallback : value.toFixed(digits);
}

export function formatDvol(value: number | null): string {
  if (value === null) {
    return "不可用";
  }
  const percentage = Math.abs(value) <= 2 ? value * 100 : value;
  return `${percentage.toFixed(2)}%`;
}

export function friendlySource(value: string | null | undefined): string {
  if (!value || value === "not_configured") {
    return "市场来源未配置";
  }
  if (value.startsWith("deribit_live:")) {
    return "Deribit live";
  }
  if (value === "deribit_published_snapshot") {
    return "Deribit 日更快照";
  }
  if (value.startsWith("fixture:")) {
    return "验证回放数据";
  }
  return humanize(value);
}

export function humanize(value: string | null | undefined, fallback = "未提供"): string {
  if (!value) {
    return fallback;
  }
  return value.replaceAll("_", " ");
}

export function publicMarketDisplayState(
  report: ResearchReport,
  freshness: PublicFreshness,
): "available" | "quality_blocked" | "stale" {
  if (
    freshness.mode === "published" &&
    freshness.phase === "expired"
  ) {
    return "stale";
  }
  if (
    report.data_status?.validated !== true ||
    freshness.phase === "expired" ||
    freshness.phase === "unavailable"
  ) {
    return "quality_blocked";
  }
  return "available";
}

export function marketFacts(report: ResearchReport): PublicMarketFacts {
  const expiries = report.vol_surface_status?.expiries ?? [];
  const underlyingPrice =
    finiteNumber(report.strategy_research?.analysis?.market?.spot_usd) ??
    expiries
      .flatMap((expiry) => expiry.surface_points ?? [])
      .map((point) => finiteNumber(point.underlying_price))
      .find((value): value is number => value !== null) ??
    null;
  const qualitySummary = report.data_status?.quality_gate?.summary;
  const candidateSummary = report.candidate_research?.summary;
  return {
    dvol: finiteNumber(
      report.data_status?.public_response_contract?.endpoints?.vol_index
        ?.volatility ?? report.vrp_status?.current_dvol_percent,
    ),
    eligibleExpiries: finiteNumber(
      report.vol_surface_status?.summary?.eligible_expiries ??
        candidateSummary?.eligible_expiries,
    ),
    evaluatedExpiries: finiteNumber(
      report.vol_surface_status?.summary?.expiries_evaluated ??
        candidateSummary?.expiries_considered ??
        qualitySummary?.expiries_evaluated,
    ),
    nakedCandidates: finiteNumber(
      candidateSummary?.eligible_naked_short_calls,
    ),
    source: friendlySource(report.data_status?.source),
    spreadCandidates: finiteNumber(
      candidateSummary?.eligible_call_credit_spreads,
    ),
    totalQuotes: finiteNumber(qualitySummary?.total_quotes),
    underlyingPrice,
    validQuotes: finiteNumber(qualitySummary?.valid_quotes),
  };
}

function spreadToRow(candidate: CallCreditSpreadCandidate): CandidateRow {
  return {
    contract:
      candidate.sell_leg_instrument_name && candidate.buy_leg_instrument_name
        ? `${candidate.sell_leg_instrument_name} → ${candidate.buy_leg_instrument_name}`
        : candidate.candidate_id ?? "价差合约未提供",
    delta: finiteNumber(candidate.model_delta),
    expiry: candidate.expiry_date ?? null,
    id:
      candidate.candidate_id ??
      `spread:${candidate.sell_leg_instrument_name ?? "unknown"}:${candidate.buy_leg_instrument_name ?? "unknown"}:${candidate.expiry_date ?? "unknown"}`,
    kind: "spread",
    premium: finiteNumber(candidate.net_credit),
    quality: finiteNumber(candidate.surface_quality?.fit_quality_score),
    noArbPass:
      typeof candidate.surface_quality?.no_arb_pass === "boolean"
        ? candidate.surface_quality.no_arb_pass
        : null,
  };
}

function nakedToRow(candidate: NakedCallCandidate): CandidateRow {
  return {
    contract:
      candidate.instrument_name ??
      candidate.candidate_id ??
      "单腿合约未提供",
    delta: finiteNumber(candidate.model_delta),
    expiry: candidate.expiry_date ?? null,
    id:
      candidate.candidate_id ??
      `naked:${candidate.instrument_name ?? "unknown"}:${candidate.expiry_date ?? "unknown"}`,
    kind: "naked",
    premium: finiteNumber(candidate.market_mid),
    quality: finiteNumber(candidate.surface_quality?.fit_quality_score),
    noArbPass:
      typeof candidate.surface_quality?.no_arb_pass === "boolean"
        ? candidate.surface_quality.no_arb_pass
        : null,
  };
}

export function researchCandidates(report: ResearchReport): CandidateRow[] {
  const spreads =
    report.candidate_research?.call_credit_spreads?.eligible?.map(
      spreadToRow,
    ) ?? [];
  const naked =
    report.candidate_research?.naked_short_calls?.eligible?.map(nakedToRow) ??
    [];
  return [...spreads, ...naked];
}

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function publicVrpSeries(
  report: ResearchReport,
): {
  currentBand: string | null | undefined;
  currentDvol: number | null;
  currentRv30: number | null;
  currentVrp: number | null;
  minimumSampleCount: number | null | undefined;
  percentile: number | null;
  sampleCount: number | null | undefined;
  series: VrpStatusPoint[];
  unavailableCode: string;
  windowDays: number | null;
} {
  const vrp = report.vrp_status;
  const currentVrp = finite(vrp?.current_vrp_percent_points);
  const currentDvol = finite(vrp?.current_dvol_percent);
  const currentRv30 = finite(vrp?.current_rv30_percent);
  const percentile = finite(vrp?.percentile);
  const series = (vrp?.series ?? []).filter(
    (point) => finite(point.vrp_percent_points) !== null,
  );
  const isInsufficientHistory =
    vrp?.status === "insufficient_history" ||
    vrp?.reason_code === "INSUFFICIENT_VRP_HISTORY";
  return {
    currentBand: vrp?.band,
    currentDvol,
    currentRv30,
    currentVrp,
    minimumSampleCount: vrp?.minimum_series_sample_count,
    percentile,
    sampleCount: vrp?.sample_count,
    series,
    unavailableCode:
      vrp?.reason_code ??
      (isInsufficientHistory
        ? "INSUFFICIENT_VRP_HISTORY"
        : "MISSING_DVOL_HISTORY"),
    windowDays: finite(vrp?.window_days),
  };
}
