import type { ResearchReport } from "../contracts";
import type { ReportFreshness } from "./selectors";

export type MarketDisplayState = "available" | "quality_blocked" | "stale";

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

export function humanize(value: string | null | undefined, fallback = "未提供"): string {
  if (!value) {
    return fallback;
  }
  return value.replaceAll("_", " ");
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

export function marketDisplayState(
  report: ResearchReport,
  freshness: ReportFreshness,
): MarketDisplayState {
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
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatDvol(value: number | null): string {
  if (value === null) {
    return "不可用";
  }
  // DVOL is quoted in volatility points, which are already percentage
  // points (a DVOL of 45.2 means 45.2% annualized).
  return `${value.toFixed(2)}%`;
}

// `formatPercent` and `formatFractionAsPercent` deliberately encode unit
// semantics instead of guessing from magnitude: every field that reaches
// them has a contract on whether it is already a percentage
// (`*_percent`, DVOL points) or a fraction (`*_ratio`, `*_fraction`,
// probabilities, NAV shares). A magnitude heuristic mis-scales low
// percentages (e.g. a 1.5% strike distance shown as 150%).
export function formatPercent(value: number | null, digits = 1): string {
  if (value === null) {
    return "—";
  }
  return `${value.toFixed(digits)}%`;
}

export function formatFractionAsPercent(
  value: number | null,
  digits = 1,
): string {
  if (value === null) {
    return "—";
  }
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatDecimal(
  value: number | null,
  digits: number,
  fallback = "—",
): string {
  return value === null ? fallback : value.toFixed(digits);
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
