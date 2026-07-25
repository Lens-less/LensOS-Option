import React from "react";
import type { SidePanelViewModel } from "../report";

export function labelForTrust(verdict: string | null): string {
  switch ((verdict ?? "").toLowerCase()) {
    case "trusted":
      return "可信";
    case "untrusted":
      return "不可信";
    default:
      return "待核验";
  }
}

export function labelForFreshness(model: SidePanelViewModel): string {
  switch (model.freshness.phase) {
    case "current":
      return `当前 · ${model.freshness.ageSec ?? "?"} 秒`;
    case "warning":
      return `临近过期 · ${model.freshness.ageSec ?? "?"} 秒`;
    case "expired":
      return `已过期 · ${model.freshness.ageSec ?? "?"} 秒`;
    default:
      return "证据年龄不可用";
  }
}

export function labelForMatch(model: SidePanelViewModel): string {
  switch (model.contractMatch.status) {
    case "sell_leg":
      return "当前合约 = 卖腿";
    case "buy_leg":
      return "当前合约 = 买腿";
    case "strategy_candidate":
      return "当前选择 = 候选策略";
    case "mismatch":
      return "当前合约不匹配";
    default:
      return "等待 Deribit 合约";
  }
}

export function labelForStance(stance: string | null): string {
  switch (stance) {
    case "CONDITIONAL_RESEARCH":
      return "条件式研究";
    case "MONITOR_ONLY":
      return "仅监控";
    case "NO_RESEARCH_SETUP":
      return "暂无研究结构";
    default:
      return "等待研究结论";
  }
}

export function labelForStructure(structure: string | null): string {
  if (structure === "CALL_CREDIT_SPREAD") {
    return "看涨信用价差";
  }
  return "无结构";
}

export function labelForSource(sourceLabel: string): string {
  if (sourceLabel.toLowerCase().includes("deribit")) {
    return "Deribit 实时公开数据";
  }
  if (sourceLabel === "not_configured") {
    return "未配置";
  }
  return sourceLabel;
}

export function formatUsdShadow(value: number | null): string {
  if (value === null) {
    return "未计算";
  }
  return `${new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value)} 参考影子值`;
}

export function formatNavLimit(value: number | null): string {
  if (value === null) {
    return "未配置";
  }
  return `${(value * 100).toFixed(2)}% NAV`;
}

export function isOfflineError(message: string | null): boolean {
  return /failed to fetch|network(?: request)?(?: error)?|connection (?:refused|reset|timed out)|err_(?:connection|name_not_resolved)|fetch failed/i.test(
    message ?? "",
  );
}

export function sectionToneClass(
  tone: "neutral" | "safe" | "warning" | undefined,
): string {
  if (tone === "safe") {
    return "is-safe";
  }
  if (tone === "warning") {
    return "is-warning";
  }
  return "";
}

export function listOrFallback(
  items: React.JSX.Element[],
  fallback: string,
): React.JSX.Element[] {
  if (items.length > 0) {
    return items;
  }
  return [
    React.createElement(
      "li",
      {
        className: "panel-empty",
        key: "fallback",
      },
      fallback,
    ),
  ];
}
