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
  const percentage = Math.abs(value) <= 2 ? value * 100 : value;
  return `${percentage.toFixed(2)}%`;
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
