import React from "react";
import type { DeribitContext } from "../extension/messages";
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

const SYMBOL_PATTERN = /^[A-Z]{2,6}$/;

/**
 * The panel has no field for "which underlying the local engine covers" -
 * `api.py`'s `PRODUCTION_ALLOWED_QUERY_KEYS = {"mode"}` fixes it at engine
 * startup and the report never restates it. Read it off the one structure
 * the report does carry (a leg's own symbol prefix); fall back to BTC, the
 * only underlying this research report has ever produced.
 */
export function coveredUnderlyingFromModel(
  model: SidePanelViewModel | null,
): string {
  const leg = model?.sellLeg ?? model?.buyLeg ?? null;
  const prefix = leg?.split("-")[0]?.toUpperCase();
  return prefix && SYMBOL_PATTERN.test(prefix) ? prefix : "BTC";
}

export interface ContextEntryPointNotice {
  text: string;
  isWarning: boolean;
}

/**
 * Turns an unmatched detection state into an honest next step instead of a
 * dead end: not a Deribit options page, a covered-vs-detected underlying
 * mismatch the panel cannot resolve by itself, or a known underlying with no
 * contract selected yet.
 */
export function contextEntryPointNotice(
  context: DeribitContext | null,
  coveredUnderlying: string,
): ContextEntryPointNotice | null {
  if (!context) {
    return null;
  }

  if (!context.underlying) {
    return {
      isWarning: false,
      text: "当前页面不是 Deribit 期权详情页；可在下方手动输入完整合约名开始研究。",
    };
  }

  if (context.underlying !== coveredUnderlying) {
    return {
      isWarning: true,
      text: `本地引擎当前只研究 ${coveredUnderlying}；无法为 ${context.underlying} 提供研究（引擎标的在启动时通过 mode 参数固定，侧栏无法请求切换）。`,
    };
  }

  if (!context.instrument) {
    return {
      isWarning: false,
      text: `已识别 ${context.underlying} 期权页面，但尚未选中具体合约；下方“同链排名对比”已展开当前候选榜，可直接选择查看。`,
    };
  }

  return null;
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
