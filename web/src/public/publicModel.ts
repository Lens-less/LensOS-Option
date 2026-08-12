import type { ResearchReport, VrpStatusPoint } from "../contracts";
import type { MarketFacts } from "../components/evidence/marketModel";
import {
  formatDecimal,
  formatDvol,
  formatExpiry,
  formatPercent,
  formatTimestamp,
  formatUsd,
  marketFacts as sharedMarketFacts,
  researchCandidates,
} from "../components/evidence/marketModel";
import {
  formatCutoffTime,
  friendlySource,
  marketDisplayState as publicMarketDisplayState,
} from "../report/display";
import { finiteNumber } from "../report/numbers";
import {
  selectReportFreshness as selectPublicFreshness,
  type ReportFreshness,
} from "../report/selectors";

export type PublicView = "evidence" | "series" | "signal";
export type FreshnessPhase = ReportFreshness["phase"];
export type PublicFreshness = ReportFreshness;
export type { CandidateRow } from "../components/evidence/marketModel";
export type PublicMarketFacts = Pick<
  MarketFacts,
  | "dvol"
  | "eligibleExpiries"
  | "evaluatedExpiries"
  | "nakedCandidates"
  | "source"
  | "spreadCandidates"
  | "totalQuotes"
  | "underlyingPrice"
  | "validQuotes"
>;

export {
  finiteNumber,
  formatCutoffTime,
  formatDecimal,
  formatDvol,
  formatExpiry,
  formatPercent,
  formatTimestamp,
  formatUsd,
  friendlySource,
  publicMarketDisplayState,
  researchCandidates,
  selectPublicFreshness,
};

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

export function marketFacts(report: ResearchReport): PublicMarketFacts {
  return sharedMarketFacts(report);
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
