import { useCallback, useEffect, useRef, useState } from "react";

import type {
  CallCreditSpreadCandidate,
  NakedCallCandidate,
  ReleasePrerequisite,
  ResearchReport,
  SurfaceExpiry,
  SurfacePoint,
} from "./contracts";

type Queue = "operator" | "system";
type Tone = "danger" | "muted" | "safe" | "warning";
type FreshnessPhase = "current" | "warning" | "expired" | "unavailable";
type CandidateKind = "naked" | "spread";

const REASON_COPY: Record<
  string,
  { label: string; action: string; ownerLabel: string; queue: Queue }
> = {
  BACKTEST_NOT_RUN: {
    label: "Backtest 尚未运行",
    action: "系统在历史数据就绪后运行有限边界 Backtest。",
    ownerLabel: "系统负责",
    queue: "system",
  },
  CALIBRATION_NOT_IMPLEMENTED: {
    label: "校准能力尚未就绪",
    action: "系统需要实现并复核校准能力；在此之前保持零仓位。",
    ownerLabel: "系统负责",
    queue: "system",
  },
  EXTERNAL_APPROVAL_PENDING: {
    label: "外部人工审批尚未记录",
    action: "完成独立复核，并把批准证据记录到版本化 runbook。",
    ownerLabel: "需要外部复核",
    queue: "operator",
  },
  EXTERNAL_RELEASE_AUTHORIZATION_REQUIRED: {
    label: "缺少外部发布授权",
    action: "由独立责任人完成发布复核；本研究运行时不能自行授权。",
    ownerLabel: "需要外部复核",
    queue: "operator",
  },
  MISSING_30_60_DAY_RECONCILIATION: {
    label: "缺少 30–60 天 Paper 对账",
    action: "系统持续累计观察，并生成可复核的对账证据。",
    ownerLabel: "系统持续观察",
    queue: "system",
  },
  MISSING_ACCOUNT_API_SNAPSHOT: {
    label: "缺少账户 API 快照",
    action: "在本机配置只读账户凭证或脱敏快照；系统随后重算风险。",
    ownerLabel: "需要你提供",
    queue: "operator",
  },
  MISSING_BACKTEST_ALIGNMENT: {
    label: "缺少 Backtest 对齐",
    action: "系统在历史数据就绪后完成基线与策略窗口对齐。",
    ownerLabel: "系统负责",
    queue: "system",
  },
  MISSING_CALIBRATED_MODEL: {
    label: "缺少已校准模型",
    action: "系统继续校准；在提升评审完成前保持研究只读。",
    ownerLabel: "系统负责",
    queue: "system",
  },
  MISSING_EXTERNAL_PROMOTION_REVIEW: {
    label: "缺少模型提升复核",
    action: "审阅校准证据，并记录明确的模型提升决定。",
    ownerLabel: "需要外部复核",
    queue: "operator",
  },
  MISSING_OUT_OF_SAMPLE_EVIDENCE: {
    label: "缺少样本外验证证据",
    action: "系统继续执行 Walk-forward 样本外验证。",
    ownerLabel: "系统负责",
    queue: "system",
  },
  MISSING_PAPER_RECONCILIATION: {
    label: "缺少 Paper 对账证据",
    action: "系统持续累计 Paper 观察并生成对账记录。",
    ownerLabel: "系统持续观察",
    queue: "system",
  },
  MISSING_VALIDATED_MARKET_DATA: {
    label: "缺少已验证市场数据",
    action: "系统继续采集并等待连续通过的可信市场快照。",
    ownerLabel: "系统负责",
    queue: "system",
  },
  MISSING_VALIDATED_PATH_RISK: {
    label: "缺少已验证路径风险",
    action: "系统继续计算路径风险；未通过前保持 NO_TRADE。",
    ownerLabel: "系统负责",
    queue: "system",
  },
  MISSING_VENDOR_HISTORY_PROVENANCE: {
    label: "缺少历史数据来源证明",
    action: "配置获授权、可追溯的历史数据源。",
    ownerLabel: "需要你提供",
    queue: "operator",
  },
  REGIME_MIN_OBSERVATIONS_NOT_MET: {
    label: "Regime 最少观察数未达到",
    action: "系统继续累计实时 Regime 观察样本。",
    ownerLabel: "系统持续观察",
    queue: "system",
  },
  REGIME_ROLLING_FIELDS_INCOMPLETE: {
    label: "Regime 滚动字段未完整",
    action: "系统继续补全滚动字段与时间窗口。",
    ownerLabel: "系统负责",
    queue: "system",
  },
  REGIME_ROLLING_HISTORY_INSUFFICIENT: {
    label: "Regime 实时历史仍不足",
    action: "系统继续累计实时 Regime 观察样本。",
    ownerLabel: "系统持续观察",
    queue: "system",
  },
  REGIME_TRUST_EVIDENCE_NOT_PROMOTED: {
    label: "Regime 可信证据尚未提升",
    action: "系统继续累计并复核 Regime 可信观察。",
    ownerLabel: "系统持续观察",
    queue: "system",
  },
  SIMULATION_NOT_REQUESTED: {
    label: "保证金模拟尚未请求",
    action: "账户证据就绪后，系统发起只读组合模拟。",
    ownerLabel: "系统负责",
    queue: "system",
  },
  TRUST_EVIDENCE_NOT_OBSERVED: {
    label: "市场可信观察尚未完成",
    action: "系统继续累计连续市场观察；不需要操作员补录数据。",
    ownerLabel: "系统持续观察",
    queue: "system",
  },
};

const ACTION_TRANSLATIONS: Record<string, string> = {
  "Obtain separately authorized manual/external release evidence; this research runtime cannot grant it.":
    "由独立责任人完成发布复核；本研究运行时不能自行授权。",
  "Obtain separately authorized manual/external release evidence.":
    "由独立责任人完成发布复核；本研究运行时不能自行授权。",
};

const DETAIL_TRANSLATIONS: Record<string, string> = {
  "Account state is missing, stale, auth-failed, or otherwise halted.":
    "账户状态缺失、过期、认证失败或已进入 HALT。",
  "Validated market data is missing.": "缺少已验证市场数据。",
};

const STATUS_LABELS: Record<string, string> = {
  allow: "允许",
  available: "可用",
  blocked: "已阻断",
  collecting: "采集中",
  failed: "失败",
  halt: "HALT",
  halt_system: "系统 HALT",
  missing: "缺失",
  not_run: "未运行",
  pass: "通过",
  pending: "待处理",
  trusted: "可信",
  unavailable: "不可用",
  untrusted: "不可信",
  validated: "已验证",
};

const INFORMATIONAL_REASONS = new Set([
  "ACCOUNT_MARGIN_GREEN",
  "DATA_TRUST_OBSERVATION_COLLECTING",
  "EVENT_CLEAR",
  "EXCHANGE_ONLINE",
  "LIQUIDITY_NORMAL",
  "MDD_CLEAR",
  "NO_OPEN_POSITIONS",
  "POSITION_NORMAL",
]);

const OUTPUT_LABELS: Record<string, string> = {
  order_instructions: "订单指令",
  paper_manual_trade_candidates: "Paper 手工候选",
  recommended_size: "推荐仓位",
  trade_recommendation: "交易建议",
};

const REQUIRED_BLOCKED_OUTPUTS = [
  "trade_recommendation",
  "recommended_size",
  "order_instructions",
  "paper_manual_trade_candidates",
] as const;

const SAFE_RESEARCH_ACTIONS = new Set([
  "RESEARCH_ONLY",
  "RESEARCH_ONLY_NO_TRADE",
  "NO_TRADE",
]);

interface Blocker {
  action: string;
  code: string;
  label: string;
  ownerLabel: string;
  queue: Queue;
}

interface Freshness {
  ageSec: number | null;
  maxAgeSec: number;
  phase: FreshnessPhase;
}

interface EvidenceItem {
  detail: string;
  label: string;
  status: string;
  tone: Tone;
}

interface MarketFacts {
  dvol: number | null;
  eligibleExpiries: number | null;
  evaluatedExpiries: number | null;
  coverageRatio: number | null;
  nakedCandidates: number | null;
  selectedInstruments: number | null;
  source: string;
  spreadCandidates: number | null;
  upstreamInstruments: number | null;
  volIndexAgeSec: number | null;
  volIndexName: string | null;
  volIndexStatus: string | null;
  totalQuotes: number | null;
  underlyingPrice: number | null;
  validQuotes: number | null;
}

interface CandidateRow {
  contract: string;
  delta: number | null;
  expiry: string | null;
  id: string;
  kind: CandidateKind;
  premium: number | null;
  quality: number | null;
  noArbPass: boolean | null;
}

interface EvidenceConsoleProps {
  nowMs: number;
  onRefresh?: () => void;
  receivedAtMs: number;
  refreshing?: boolean;
  report: ResearchReport;
}

const FRESHNESS_LABELS: Record<FreshnessPhase, string> = {
  current: "当前",
  warning: "预警",
  expired: "已失效",
  unavailable: "不可用",
};

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function humanize(value: string | null | undefined, fallback = "未提供"): string {
  if (!value) {
    return fallback;
  }
  return value.replaceAll("_", " ");
}

function displayStatus(
  value: string | null | undefined,
  fallback = "未提供",
): string {
  if (!value) {
    return fallback;
  }
  return STATUS_LABELS[value.toLowerCase()] ?? humanize(value, fallback);
}

function displaySource(
  value: string | null | undefined,
  fallback: string,
): string {
  if (!value || value === "not_configured") {
    return fallback;
  }
  return value;
}

function friendlySource(value: string | null | undefined): string {
  if (!value || value === "not_configured") {
    return "市场来源未配置";
  }
  if (value.startsWith("deribit_live:")) {
    return "Deribit live";
  }
  if (value.startsWith("fixture:")) {
    return "验证回放数据";
  }
  return humanize(value);
}

function statusTone(status: string | null | undefined): Tone {
  const normalized = (status ?? "").toLowerCase();
  if (
    [
      "blocked",
      "expired",
      "failed",
      "halt",
      "missing",
      "no-go",
      "no_trade",
      "not_run",
      "stale",
      "unavailable",
      "untrusted",
    ].some((token) => normalized.includes(token))
  ) {
    return "danger";
  }
  if (
    [
      "allow",
      "available",
      "clear",
      "current",
      "green",
      "online",
      "pass",
      "ready",
      "trusted",
      "validated",
    ].some((token) => normalized.includes(token))
  ) {
    return "safe";
  }
  if (
    ["collecting", "partial", "pending", "warning"].some((token) =>
      normalized.includes(token),
    )
  ) {
    return "warning";
  }
  return "muted";
}

function isInformationalReason(code: string): boolean {
  return (
    INFORMATIONAL_REASONS.has(code) ||
    code.startsWith("PRIMARY_REGIME_") ||
    code.endsWith("_PERMISSION_ACTIVE")
  );
}

function labelForReason(code: string): string {
  return REASON_COPY[code]?.label ?? humanize(code);
}

interface Ownership {
  ownerLabel: string;
  queue: Queue;
}

function ownershipForReason(code: string, report: ResearchReport): Ownership {
  if (
    code === "MISSING_VALIDATED_MARKET_DATA" &&
    (!report.data_status?.source ||
      report.data_status.source === "not_configured")
  ) {
    return {
      ownerLabel: "需要你提供",
      queue: "operator",
    };
  }

  const configured = REASON_COPY[code];
  if (!configured) {
    return {
      ownerLabel: "责任未声明",
      queue: "operator",
    };
  }

  return {
    ownerLabel: configured.ownerLabel,
    queue: configured.queue,
  };
}

function fallbackAction(ownership: Ownership): string {
  if (ownership.ownerLabel === "责任未声明") {
    return "报告未声明责任人与下一步；请人工核对原始原因码。";
  }
  return ownership.queue === "operator"
    ? "提供外部证据后，系统自动重新计算。"
    : "系统继续采集、校验或计算。";
}

function blockerFromReason(code: string, report: ResearchReport): Blocker {
  const ownership = ownershipForReason(code, report);
  const missingConfiguredMarketSource =
    code === "MISSING_VALIDATED_MARKET_DATA" &&
    (!report.data_status?.source ||
      report.data_status.source === "not_configured");
  return {
    action:
      (missingConfiguredMarketSource
        ? "配置获授权的市场数据源；系统随后校验新的市场快照。"
        : REASON_COPY[code]?.action) ?? fallbackAction(ownership),
    code,
    label: labelForReason(code),
    ownerLabel: ownership.ownerLabel,
    queue: ownership.queue,
  };
}

function blockerFromPrerequisite(
  item: ReleasePrerequisite,
  report: ResearchReport,
): Blocker | null {
  if (item.satisfied) {
    return null;
  }
  const code = item.reason_codes?.[0] ?? item.reason_code ?? item.name;
  const owner = (item.owner ?? "").toLowerCase();
  const ownership: Ownership =
    owner === "external_operator" ||
    owner === "operator" ||
    owner === "reviewer"
      ? {
          ownerLabel: owner === "external_operator" ? "需要外部复核" : "需要你提供",
          queue: "operator",
        }
      : owner === "system" || owner === "runtime" || owner === "scheduler"
        ? {
            ownerLabel: "系统负责",
            queue: "system",
          }
        : ownershipForReason(code, report);
  const rawAction = item.next_action ?? item.action;
  return {
    action:
      (rawAction ? ACTION_TRANSLATIONS[rawAction] : undefined) ??
      REASON_COPY[code]?.action ??
      fallbackAction(ownership),
    code,
    label: labelForReason(code),
    ownerLabel: ownership.ownerLabel,
    queue: ownership.queue,
  };
}

function reportBlockers(report: ResearchReport): Blocker[] {
  const byCode = new Map<string, Blocker>();
  for (const prerequisite of
    report.full_system_surface?.release_readiness?.prerequisites ?? []) {
    const blocker = blockerFromPrerequisite(prerequisite, report);
    if (blocker) {
      byCode.set(blocker.code, blocker);
    }
  }
  const reasons = [
    ...(report.reason_codes ?? []),
    ...(report.mode_gate?.reason_codes ?? []),
    ...(report.data_trust?.reason_codes ?? []),
    ...(report.data_status?.reason_code ? [report.data_status.reason_code] : []),
    ...(report.account_status?.reason_code
      ? [report.account_status.reason_code]
      : []),
  ];
  for (const code of reasons) {
    if (!isInformationalReason(code) && !byCode.has(code)) {
      byCode.set(code, blockerFromReason(code, report));
    }
  }
  return [...byCode.values()];
}

function reportFreshness(
  report: ResearchReport,
  receivedAtMs: number,
  nowMs: number,
): Freshness {
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
    return { ageSec: null, maxAgeSec, phase: "unavailable" };
  }
  const elapsedSec = Math.max(0, nowMs - receivedAtMs) / 1_000;
  const ageSec = Math.floor(reportedAge + elapsedSec);
  const warningAgeSec = Math.min(45, maxAgeSec);
  const phase: FreshnessPhase =
    ageSec >= maxAgeSec
      ? "expired"
      : ageSec >= warningAgeSec
        ? "warning"
        : "current";
  return { ageSec, maxAgeSec, phase };
}

function evidenceItems(report: ResearchReport): EvidenceItem[] {
  const data = report.data_status;
  const account = report.account_status;
  const calibration = report.calibration_status;
  const backtest = report.backtest_status;
  const portfolio = report.portfolio_risk;
  return [
    {
      detail: displaySource(data?.source, data?.reason_code ?? "未配置来源"),
      label: "市场数据",
      status: displayStatus(data?.status),
      tone: statusTone(data?.status),
    },
    {
      detail:
        account?.source === "not_configured"
          ? "只读账户源未配置"
          : humanize(account?.trade_gate, account?.reason_code ?? "未配置"),
      label: "账户与保证金",
      status: displayStatus(account?.status),
      tone: statusTone(account?.status ?? account?.trade_gate),
    },
    {
      detail:
        report.data_trust?.source_class === "missing"
          ? "来源缺失"
          : humanize(report.data_trust?.source_class, "无可信来源"),
      label: "数据可信度",
      status: displayStatus(report.data_trust?.verdict),
      tone: statusTone(report.data_trust?.verdict),
    },
    {
      detail:
        report.vol_surface_status?.fit_model ??
        report.vol_surface_status?.reason_code ??
        "无曲面模型",
      label: "波动率曲面",
      status: displayStatus(report.vol_surface_status?.status),
      tone: statusTone(report.vol_surface_status?.status),
    },
    {
      detail:
        calibration?.model_version ??
        calibration?.reason_code ??
        "无模型版本",
      label: "模型校准",
      status: displayStatus(calibration?.status),
      tone: statusTone(calibration?.status),
    },
    {
      detail: backtest?.reason_code ?? "无 Backtest 证据",
      label: "Backtest",
      status: displayStatus(backtest?.status),
      tone: statusTone(backtest?.status),
    },
    {
      detail: portfolio?.final_signal?.reason
        ? (DETAIL_TRANSLATIONS[portfolio.final_signal.reason] ??
          portfolio.final_signal.reason)
        : "无可执行组合结论",
      label: "组合仲裁",
      status: displayStatus(
        portfolio?.final_action,
        displayStatus(report.risk_state, "HALT"),
      ),
      tone: statusTone(portfolio?.final_action ?? report.risk_state),
    },
  ];
}

function formatTimestamp(value: string | null | undefined): string {
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

function formatExpiry(value: string | null): string {
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

function formatUsd(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatDvol(value: number | null): string {
  if (value === null) {
    return "不可用";
  }
  const percentage = Math.abs(value) <= 2 ? value * 100 : value;
  return `${percentage.toFixed(2)}%`;
}

function formatPercent(value: number | null, digits = 1): string {
  if (value === null) {
    return "—";
  }
  const percentage = Math.abs(value) <= 2 ? value * 100 : value;
  return `${percentage.toFixed(digits)}%`;
}

function formatDecimal(
  value: number | null,
  digits: number,
  fallback = "—",
): string {
  return value === null ? fallback : value.toFixed(digits);
}

function marketFacts(report: ResearchReport): MarketFacts {
  const expiries = report.vol_surface_status?.expiries ?? [];
  const collectionScope = report.data_status?.collection_scope;
  const volIndex =
    report.data_status?.public_response_contract?.endpoints?.vol_index;
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
        ?.volatility,
    ),
    coverageRatio: finiteNumber(collectionScope?.coverage_ratio),
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
    selectedInstruments: finiteNumber(
      collectionScope?.selected_instrument_count,
    ),
    source: friendlySource(report.data_status?.source),
    spreadCandidates: finiteNumber(
      candidateSummary?.eligible_call_credit_spreads,
    ),
    upstreamInstruments: finiteNumber(
      collectionScope?.upstream_instrument_count,
    ),
    volIndexAgeSec: finiteNumber(volIndex?.age_sec),
    volIndexName: volIndex?.index_name ?? null,
    volIndexStatus: volIndex?.status ?? null,
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

function researchCandidates(report: ResearchReport): CandidateRow[] {
  const spreads =
    report.candidate_research?.call_credit_spreads?.eligible?.map(
      spreadToRow,
    ) ?? [];
  const naked =
    report.candidate_research?.naked_short_calls?.eligible?.map(nakedToRow) ??
    [];
  return [...spreads, ...naked];
}

function Masthead({
  freshness,
  onRefresh,
  refreshing,
  source,
}: {
  freshness?: Freshness;
  onRefresh?: () => void;
  refreshing: boolean;
  source?: string;
}): React.JSX.Element {
  const age =
    freshness?.ageSec === null || freshness?.ageSec === undefined
      ? null
      : `${freshness.ageSec.toLocaleString("zh-CN")} 秒`;
  return (
    <header className="masthead">
      <a className="brand" href="/evidence" aria-label="LensOS 期权研究台首页">
        <span className="brand-mark" aria-hidden="true">
          LO
        </span>
        <span>
          <strong>LensOS Option</strong>
          <small>Research brief</small>
        </span>
      </a>
      <nav className="masthead-actions" aria-label="期权研究台操作">
        {freshness ? (
          <span
            className="source-indicator"
            data-state={freshness.phase}
            aria-label={`市场来源 ${source ?? "未提供"}，数据年龄 ${age ?? "不可用"}`}
          >
            <span aria-hidden="true" />
            {source}
            {age ? ` · ${age}` : ""}
          </span>
        ) : null}
        <span className="read-only-indicator">READ-ONLY</span>
        <a
          className="text-link"
          href="/research/report"
          rel="noreferrer"
          target="_blank"
        >
          原始 JSON
        </a>
        {onRefresh ? (
          <button
            className="refresh-button"
            aria-busy={refreshing}
            disabled={refreshing}
            type="button"
            onClick={onRefresh}
          >
            {refreshing ? "刷新中…" : "刷新数据"}
          </button>
        ) : null}
      </nav>
    </header>
  );
}

const SECTION_LINKS = [
  { id: "brief", label: "市场简报" },
  { id: "framework", label: "策略闭环" },
  { id: "surface", label: "曲面" },
  { id: "candidates", label: "候选" },
  { id: "limitations", label: "边界" },
  { id: "evidence-chain", label: "证据" },
] as const;

type SectionId = (typeof SECTION_LINKS)[number]["id"];

function SectionNavigation(): React.JSX.Element {
  const [activeSection, setActiveSection] = useState<SectionId>("brief");

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") {
      return;
    }
    const targets = SECTION_LINKS.map(({ id }) =>
      document.getElementById(id),
    ).filter((target): target is HTMLElement => target !== null);
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort(
            (left, right) =>
              Math.abs(left.boundingClientRect.top) -
              Math.abs(right.boundingClientRect.top),
          )[0];
        if (visible) {
          setActiveSection(visible.target.id as SectionId);
        }
      },
      {
        rootMargin: "-118px 0px -62% 0px",
        threshold: [0, 0.25, 0.6],
      },
    );
    targets.forEach((target) => {
      observer.observe(target);
    });
    return () => {
      observer.disconnect();
    };
  }, []);

  return (
    <nav className="section-navigation" aria-label="页面章节">
      {SECTION_LINKS.map(({ id, label }) => (
        <a
          aria-current={activeSection === id ? "location" : undefined}
          href={`#${id}`}
          key={id}
          onClick={() => {
            setActiveSection(id);
          }}
        >
          {label}
        </a>
      ))}
    </nav>
  );
}

function FreshnessStatus({
  freshness,
  report,
}: {
  freshness: Freshness;
  report: ResearchReport;
}): React.JSX.Element {
  const age =
    freshness.ageSec === null
      ? "无可验证年龄"
      : `${freshness.ageSec.toLocaleString("zh-CN")} 秒`;
  return (
    <section
      className="freshness-status"
      data-state={freshness.phase}
      aria-label="市场证据新鲜度"
      aria-live="polite"
    >
      <span className="freshness-dot" aria-hidden="true" />
      <div>
        <span>市场证据</span>
        <strong>{FRESHNESS_LABELS[freshness.phase]}</strong>
      </div>
      <div>
        <span>数据年龄</span>
        <strong>{age}</strong>
      </div>
      <div>
        <span>失效上限</span>
        <strong>{freshness.maxAgeSec} 秒</strong>
      </div>
      <div className="freshness-source">
        <span>来源</span>
        <strong>{friendlySource(report.data_status?.source)}</strong>
      </div>
    </section>
  );
}

function MarketMetric({
  label,
  value,
  tone = "muted",
}: {
  label: string;
  value: string;
  tone?: Tone;
}): React.JSX.Element {
  return (
    <div className="market-metric" data-tone={tone}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function CandidateBriefRow({
  candidate,
}: {
  candidate: CandidateRow;
}): React.JSX.Element {
  const metric =
    candidate.kind === "spread"
      ? `${formatDecimal(candidate.premium, 4)} BTC`
      : `Δ ${formatDecimal(candidate.delta, 3)}`;
  return (
    <li className="brief-candidate">
      <div>
        <span>{candidate.kind === "spread" ? "CALL 价差" : "单腿 CALL"}</span>
        <strong>{candidate.contract}</strong>
      </div>
      <div>
        <span>{formatExpiry(candidate.expiry)}</span>
        <strong>{metric}</strong>
      </div>
    </li>
  );
}

function MarketBrief({
  candidates,
  facts,
  freshness,
  report,
}: {
  candidates: CandidateRow[];
  facts: MarketFacts;
  freshness: Freshness;
  report: ResearchReport;
}): React.JSX.Element {
  const hasMarketEvidence =
    report.data_status?.validated === true &&
    facts.underlyingPrice !== null &&
    freshness.phase !== "expired" &&
    freshness.phase !== "unavailable";
  const candidateTotal =
    (facts.nakedCandidates ?? 0) + (facts.spreadCandidates ?? 0);
  const narrative = !hasMarketEvidence
    ? "当前没有可验证的市场快照；价格、DVOL、曲面与候选不会被估算或补齐。"
    : `${facts.validQuotes ?? "—"} 条报价通过质量门；${
        facts.eligibleExpiries ?? "—"
      } 个到期曲面可进入候选研究。`;
  const visibleCandidates = hasMarketEvidence ? candidates.slice(0, 4) : [];

  return (
    <section
      id="brief"
      className="market-brief"
      aria-label="实时研究摘要"
    >
      <div className="market-pulse">
        <header className="report-folio">
          <p>BTC options / Deribit research sample</p>
          <dl>
            <div>
              <dt>报告</dt>
              <dd>{report.schema_version}</dd>
            </div>
            <div>
              <dt>生成</dt>
              <dd>{formatTimestamp(report.generated_at)}</dd>
            </div>
          </dl>
        </header>
        <div className="market-lockup">
          <p className="section-kicker">Market pulse / 市场脉搏</p>
          <h1>BTC 市场脉搏</h1>
          <div className="underlying-price" data-available={hasMarketEvidence}>
            {hasMarketEvidence ? formatUsd(facts.underlyingPrice) : "—"}
          </div>
          <div className="dvol-line">
            <span>BTC DVOL</span>
            <strong>{hasMarketEvidence ? formatDvol(facts.dvol) : "不可用"}</strong>
          </div>
          <p className="market-narrative">{narrative}</p>
        </div>
        <FreshnessStatus freshness={freshness} report={report} />
        <div className="market-metrics" aria-label="实时研究指标">
          <MarketMetric
            label="报价质量"
            value={
              hasMarketEvidence &&
              facts.validQuotes !== null &&
              facts.totalQuotes !== null
                ? `${facts.validQuotes} / ${facts.totalQuotes} 条有效报价`
                : "无可验证报价"
            }
            tone={hasMarketEvidence ? "safe" : "danger"}
          />
          <MarketMetric
            label="曲面覆盖"
            value={
              hasMarketEvidence &&
              facts.eligibleExpiries !== null &&
              facts.evaluatedExpiries !== null
                ? `${facts.eligibleExpiries} / ${facts.evaluatedExpiries} 个到期可用`
                : "无可用曲面"
            }
            tone={
              hasMarketEvidence && (facts.eligibleExpiries ?? 0) > 0
                ? "safe"
                : "warning"
            }
          />
          <MarketMetric
            label="单腿研究"
            value={
              hasMarketEvidence && facts.nakedCandidates !== null
                ? `${facts.nakedCandidates} 个单腿候选`
                : "无候选"
            }
          />
          <MarketMetric
            label="价差研究"
            value={
              hasMarketEvidence && facts.spreadCandidates !== null
                ? `${facts.spreadCandidates} 个价差候选`
                : "无候选"
            }
          />
        </div>
      </div>

      <aside className="candidate-sheet" aria-label="今日研究候选">
        <div className="candidate-sheet-heading">
          <div>
            <p className="section-kicker">Research candidates</p>
            <h2>今日研究候选</h2>
          </div>
          <span>{hasMarketEvidence ? `${candidateTotal} 个通过筛选` : "数据不可用"}</span>
        </div>
        {visibleCandidates.length > 0 ? (
          <ol className="brief-candidate-list">
            {visibleCandidates.map((candidate) => (
              <CandidateBriefRow candidate={candidate} key={candidate.id} />
            ))}
          </ol>
        ) : (
          <div className="brief-empty">
            <strong>没有可展示的研究候选</strong>
            <p>只有在当前市场证据与曲面质量均可验证时，候选才会出现在这里。</p>
          </div>
        )}
        <div className="candidate-boundary">
          <span>仅表示通过研究筛选</span>
          <strong>NO-GO · NO_TRADE</strong>
        </div>
      </aside>
    </section>
  );
}

function surfaceSeries(expiry: SurfaceExpiry): SurfacePoint[] {
  return (expiry.surface_points ?? []).filter(
    (point) =>
      finiteNumber(point.strike_price) !== null &&
      finiteNumber(point.surface_fitted_iv) !== null,
  );
}

function SurfaceChart({
  expiries,
}: {
  expiries: SurfaceExpiry[];
}): React.JSX.Element | null {
  const series = expiries
    .map((expiry) => ({ expiry, points: surfaceSeries(expiry) }))
    .filter(({ points }) => points.length >= 2);
  const allPoints = series.flatMap(({ points }) => points);
  if (allPoints.length < 2) {
    return null;
  }
  const strikes = allPoints
    .map((point) => finiteNumber(point.strike_price))
    .filter((value): value is number => value !== null);
  const ivs = allPoints
    .map((point) => finiteNumber(point.surface_fitted_iv))
    .filter((value): value is number => value !== null);
  const minStrike = Math.min(...strikes);
  const maxStrike = Math.max(...strikes);
  const minIv = Math.min(...ivs);
  const maxIv = Math.max(...ivs);
  const strikeSpan = Math.max(maxStrike - minStrike, 1);
  const ivSpan = Math.max(maxIv - minIv, 1);
  const x = (strike: number) => 64 + ((strike - minStrike) / strikeSpan) * 616;
  const y = (iv: number) => 244 - ((iv - minIv) / ivSpan) * 188;
  const colors = ["#0f62fe", "#8e5b00", "#198038", "#da1e28"];

  return (
    <div className="surface-chart-scroll" aria-label="波动率曲面图区域">
      <svg
        className="surface-chart"
        viewBox="0 0 744 292"
        role="img"
        aria-label="BTC 波动率曲面"
      >
        <title>BTC 波动率曲面</title>
        <desc>按到期日展示执行价与拟合隐含波动率的关系。</desc>
        <defs>
          <pattern
            id="surface-grid"
            width="77"
            height="47"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 77 0 L 0 0 0 47"
              fill="none"
              stroke="#e0e0e0"
              strokeWidth="1"
            />
          </pattern>
        </defs>
        <rect x="64" y="56" width="616" height="188" fill="url(#surface-grid)" />
        <line x1="64" y1="244" x2="680" y2="244" stroke="#8d8d8d" />
        <line x1="64" y1="56" x2="64" y2="244" stroke="#8d8d8d" />
        <text x="64" y="269" className="chart-axis-label">
          {Math.round(minStrike / 1_000)}K
        </text>
        <text x="646" y="269" className="chart-axis-label">
          {Math.round(maxStrike / 1_000)}K
        </text>
        <text x="18" y="63" className="chart-axis-label">
          {maxIv.toFixed(1)}%
        </text>
        <text x="18" y="247" className="chart-axis-label">
          {minIv.toFixed(1)}%
        </text>
        {series.map(({ expiry, points }, index) => {
          const color = colors[index % colors.length];
          const line = points
            .map((point) => {
              const strike = finiteNumber(point.strike_price) ?? minStrike;
              const iv = finiteNumber(point.surface_fitted_iv) ?? minIv;
              return `${x(strike)},${y(iv)}`;
            })
            .join(" ");
          return (
            <g key={expiry.expiry_date ?? `expiry-${index}`}>
              <polyline
                points={line}
                fill="none"
                stroke={color}
                strokeWidth={index === 0 ? 3 : 2.25}
                strokeDasharray={index === 0 ? undefined : "7 5"}
              />
              {points.map((point, pointIndex) => {
                const strike = finiteNumber(point.strike_price) ?? minStrike;
                const iv = finiteNumber(point.surface_fitted_iv) ?? minIv;
                return (
                  <circle
                    cx={x(strike)}
                    cy={y(iv)}
                    fill="#ffffff"
                    key={`${expiry.expiry_date}-${point.instrument_name ?? pointIndex}`}
                    r="3.5"
                    stroke={color}
                    strokeWidth="2"
                  />
                );
              })}
            </g>
          );
        })}
        <text x="346" y="288" className="chart-axis-title">
          执行价（USD）
        </text>
        <text
          x="-181"
          y="12"
          className="chart-axis-title"
          transform="rotate(-90)"
        >
          拟合 IV
        </text>
      </svg>
    </div>
  );
}

function SurfaceResearch({
  report,
}: {
  report: ResearchReport;
}): React.JSX.Element {
  const expiries = report.vol_surface_status?.expiries ?? [];
  const chartAvailable = expiries.some(
    (expiry) => surfaceSeries(expiry).length >= 2,
  );
  return (
    <section
      id="surface"
      className="research-section surface-section"
      aria-labelledby="surface-title"
    >
      <header className="research-section-heading">
        <div>
          <p className="section-kicker">Volatility surface / 证据</p>
          <h2 id="surface-title">波动率曲面证据</h2>
        </div>
        <p>
          拟合质量和无套利检查分开呈现；只有两者都通过，曲面才进入候选研究。
        </p>
      </header>
      {chartAvailable ? (
        <div className="surface-layout">
          <SurfaceChart expiries={expiries} />
          <div className="surface-expiries" aria-label="到期曲面质量">
            {expiries.map((expiry) => {
              const tone: Tone = expiry.candidate_eligible
                ? "safe"
                : expiry.fit_quality_pass
                  ? "warning"
                  : "danger";
              return (
                <article
                  className="surface-expiry"
                  data-tone={tone}
                  key={expiry.expiry_date ?? String(expiry.dte_days)}
                >
                  <div>
                    <span>{formatExpiry(expiry.expiry_date ?? null)}</span>
                    <strong>
                      {finiteNumber(expiry.dte_days)?.toFixed(1) ?? "—"} DTE
                    </strong>
                  </div>
                  <dl>
                    <div>
                      <dt>拟合质量</dt>
                      <dd>
                        {formatDecimal(
                          finiteNumber(expiry.fit_quality_score),
                          3,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>无套利</dt>
                      <dd>{expiry.no_arb_pass ? "通过" : "未通过"}</dd>
                    </div>
                    <div>
                      <dt>候选资格</dt>
                      <dd>{expiry.candidate_eligible ? "可用" : "不可用"}</dd>
                    </div>
                  </dl>
                  {(expiry.reason_codes ?? []).length > 0 ? (
                    <code>{expiry.reason_codes?.join(" · ")}</code>
                  ) : (
                    <code>NO_ARBITRAGE_PASS</code>
                  )}
                </article>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="section-empty" role="status">
          <strong>没有可验证的曲面数据</strong>
          <p>页面不会根据缺失报价推算曲线；请刷新或检查市场数据来源。</p>
        </div>
      )}
    </section>
  );
}

function CandidateTable({
  candidates,
}: {
  candidates: CandidateRow[];
}): React.JSX.Element {
  return (
    <div
      className="candidate-table-scroll"
      role="region"
      aria-label="研究候选表格"
      tabIndex={0}
    >
      <table className="candidate-table">
        <thead>
          <tr>
            <th scope="col">结构</th>
            <th scope="col">合约</th>
            <th scope="col">到期</th>
            <th scope="col">模型 Delta</th>
            <th scope="col">权利金 / 净信用</th>
            <th scope="col">曲面质量</th>
            <th scope="col">研究状态</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate) => (
            <tr key={candidate.id}>
              <td>
                <span className="structure-label" data-kind={candidate.kind}>
                  {candidate.kind === "spread" ? "CALL 信用价差" : "单腿空头 CALL"}
                </span>
              </td>
              <td className="candidate-contract">{candidate.contract}</td>
              <td>{formatExpiry(candidate.expiry)}</td>
              <td className="numeric-cell">
                {formatDecimal(candidate.delta, 3)}
              </td>
              <td className="numeric-cell">
                {formatDecimal(candidate.premium, 4)} BTC
              </td>
              <td className="numeric-cell">
                {formatDecimal(candidate.quality, 3)}
              </td>
              <td>
                <span
                  className="evidence-state"
                  data-tone={candidate.noArbPass ? "safe" : "warning"}
                >
                  {candidate.noArbPass ? "研究筛选通过" : "仍需复核"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CandidateResearchSection({
  candidates,
  report,
}: {
  candidates: CandidateRow[];
  report: ResearchReport;
}): React.JSX.Element {
  const summary = report.candidate_research?.summary;
  return (
    <section
      id="candidates"
      className="research-section candidates-section"
      aria-labelledby="candidates-title"
    >
      <header className="research-section-heading">
        <div>
          <p className="section-kicker">Candidate research / 只读</p>
          <h2 id="candidates-title">研究候选清单</h2>
        </div>
        <p>
          {summary?.eligible_naked_short_calls ?? 0} 个单腿、{" "}
          {summary?.eligible_call_credit_spreads ?? 0} 个价差通过当前过滤；这不是交易建议。
        </p>
      </header>
      {candidates.length > 0 ? (
        <CandidateTable candidates={candidates} />
      ) : (
        <div className="section-empty" role="status">
          <strong>没有通过筛选的研究候选</strong>
          <p>当前报告没有可验证的候选行；页面不会构造示例策略。</p>
        </div>
      )}
    </section>
  );
}

const STRATEGY_STAGE_LABELS: Record<string, string> = {
  ANALYZE: "分析",
  COLLECT: "采集",
  ENTER: "进场",
  EXIT: "退出",
  MONITOR: "监控",
  REVIEW: "复盘",
  RISK: "风控",
  SELECT: "结构",
};

const CONDITION_LABELS: Record<string, string> = {
  account_gate: "账户风控",
  calibrated_path_risk: "路径风险 / 校准",
  candidate_eligibility: "候选资格",
  cost_coverage: "成本覆盖",
  delta_band: "Delta 区间",
  event_gate: "事件风险",
  leg_liquidity: "双腿流动性",
  market_freshness: "数据新鲜度",
  market_quality: "市场快照",
  no_arbitrage: "无套利检查",
  regime_permission: "Regime 权限",
  settlement_window: "结算时段",
  surface_fit: "曲面拟合",
};

const CONDITION_STATUS_LABELS: Record<string, string> = {
  block: "未通过",
  pass: "通过",
  unknown: "待验证",
};

const POSITION_RESPONSE_LABELS: Record<string, string> = {
  close: "平仓",
  close_and_pause: "平仓并暂停",
  close_unless_defined_risk_conversion_reduces_total_stress:
    "平仓；仅允许可证明降低总压力的定义风险转换",
  hold_or_take_profit: "持有或按止盈规则减仓",
  no_additions_and_review: "停止加仓并复核",
  reduce_or_add_defined_risk_protection: "减仓或增加定义风险保护",
};

const PROFIT_RESPONSE_LABELS: Record<string, string> = {
  close_50_percent: "平掉 50%",
  close_all: "全部平仓",
  close_and_rescan: "平仓并重新扫描",
  close_early: "提前平仓",
};

const MONITOR_METRIC_LABELS: Record<string, string> = {
  account_age_sec: "账户快照年龄",
  buy_leg_spread_ratio: "买入腿价差比",
  candidate_delta: "候选 Delta",
  dte_days: "剩余到期天数",
  event_score: "事件风险分",
  market_age_sec: "市场数据年龄",
  no_arbitrage_pass: "无套利状态",
  position_loss_multiple: "持仓亏损倍数",
  sell_leg_spread_ratio: "卖出腿价差比",
  spread_permission: "Regime 价差权限",
  surface_fit_quality: "曲面拟合质量",
};

const MONITOR_RESPONSE_LABELS: Record<string, string> = {
  keep_monitor_only: "保持仅观察",
  kill_new_entry: "禁止新进场",
  move_to_caution: "转入 CAUTION",
  move_to_defense: "转入 DEFENSE",
  no_contract_sizing: "停止仓位计算",
  pause_research_setup: "暂停研究方案",
  remove_candidate: "移出候选",
  time_management_review: "启动时间管理复核",
};

const PROMOTION_LABELS: Record<string, string> = {
  "Attach a fresh read-only account snapshot before any sizing study.":
    "接入新鲜的只读账户快照后，才允许研究仓位上限。",
  "Persist enough rolling observations to promote regime evidence.":
    "积累足够的滚动样本，提升 Regime 证据等级。",
  "Promote walk-forward calibration and validated path-risk outputs.":
    "完成 Walk-forward 校准，并提升已验证的路径风险输出。",
  "Reconcile paper observations, fees, slippage, and forced-exit behavior.":
    "核对 Paper 观察、费用、滑点与强制退出行为。",
  "Run an aligned bounded backtest on licensed historical data.":
    "在获授权历史数据上运行口径对齐的有限边界 Backtest。",
};

function strategyStanceLabel(value: string | undefined): string {
  if (value === "CONDITIONAL_RESEARCH") {
    return "条件式研究";
  }
  if (value === "MONITOR_ONLY") {
    return "仅观察";
  }
  return "无可验证方案";
}

function formatSignedPoints(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return `${value > 0 ? "+" : ""}${value.toFixed(2)} pt`;
}

function formatConditionObserved(id: string, value: unknown): string {
  if (value === null || value === undefined) {
    return "未提供";
  }
  if (id === "market_freshness" && typeof value === "number") {
    return `${value.toFixed(0)} 秒`;
  }
  if (id === "surface_fit" && typeof value === "number") {
    return value.toFixed(3);
  }
  if (id === "delta_band" && typeof value === "number") {
    return value.toFixed(3);
  }
  if (id === "event_gate" && typeof value === "number") {
    return value.toFixed(2);
  }
  if (id === "leg_liquidity" && typeof value === "object") {
    const ratios = value as { buy?: number | null; sell?: number | null };
    return `卖 ${formatPercent(ratios.sell ?? null, 1)} · 买 ${formatPercent(
      ratios.buy ?? null,
      1,
    )}`;
  }
  if (id === "regime_permission" && typeof value === "object") {
    const permission = value as {
      spread_permission?: boolean;
      status?: string;
    };
    return `${displayStatus(permission.status)} · ${
      permission.spread_permission ? "允许" : "未允许"
    }`;
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (typeof value === "number") {
    return value.toLocaleString("zh-CN");
  }
  if (typeof value === "string") {
    const labels: Record<string, string> = {
      eligible: "通过筛选",
      outside: "窗口外",
      unavailable: "不可用",
      validated: "已验证",
    };
    return labels[value] ?? humanize(value);
  }
  return "见原始数据";
}

function StrategyFrameworkSection({
  report,
}: {
  report: ResearchReport;
}): React.JSX.Element {
  const strategy = report.strategy_research;
  const collection = strategy?.collection;
  const market = strategy?.analysis?.market;
  const volatility = strategy?.analysis?.volatility;
  const playbook = strategy?.playbook;
  const candidate = playbook?.candidate;
  const economics = playbook?.economics;
  const conditions = playbook?.entry_contract?.conditions ?? [];
  const riskBudget = playbook?.risk_budget;
  const exitContract = playbook?.exit_contract;
  const coverage = collection?.coverage;
  const quality = collection?.quality;
  const pipeline =
    strategy?.pipeline ??
    Object.keys(STRATEGY_STAGE_LABELS).map((stage) => ({
      stage,
      status: "blocked" as const,
    }));

  return (
    <section
      id="framework"
      className="research-section strategy-workflow"
      aria-label="完整策略工作流"
    >
      <header className="strategy-verdict">
        <div className="strategy-verdict-copy">
          <p className="section-kicker">Decision workflow / 研究闭环</p>
          <div className="strategy-title-line">
            <h2>今日策略结论</h2>
            <span
              className="stance-badge"
              data-tone={
                strategy?.decision?.stance === "CONDITIONAL_RESEARCH"
                  ? "safe"
                  : "warning"
              }
            >
              {strategyStanceLabel(strategy?.decision?.stance)}
            </span>
          </div>
          <strong className="primary-structure">
            {strategy?.decision?.primary_structure === "CALL_CREDIT_SPREAD"
              ? "CALL 信用价差"
              : "当前无主策略"}
          </strong>
          <p>
            {playbook
              ? "当前优先研究定义风险结构。市场与曲面已形成候选，但 Regime、账户、路径风险和成本覆盖尚未同时通过，因此不进场。"
              : "当前没有足够的可验证市场证据，系统不会构造策略或估算缺失值。"}
          </p>
        </div>
        <div className="strategy-verdict-aside">
          <span>研究置信上限</span>
          <strong>
            {strategy?.confidence_ceiling === "screening_only"
              ? "筛选级"
              : "证据不足"}
          </strong>
          <p>只读 · 不生成仓位 · 不生成订单</p>
        </div>
      </header>

      <ol className="strategy-pipeline" aria-label="策略研究八阶段">
        {pipeline.map((stage, index) => (
          <li data-status={stage.status} key={stage.stage}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{STRATEGY_STAGE_LABELS[stage.stage] ?? stage.stage}</strong>
            <small>
              {stage.status === "ready"
                ? "已形成"
                : stage.status === "partial"
                  ? "部分"
                  : "未通过"}
            </small>
          </li>
        ))}
      </ol>

      {playbook ? (
        <>
          <div className="strategy-analysis-grid">
            <article className="strategy-panel">
              <header>
                <span>01 · 采集</span>
                <strong>{friendlySource(collection?.source)}</strong>
              </header>
              <dl className="strategy-metric-grid">
                <div>
                  <dt>样本 / 全市场</dt>
                  <dd>
                    {coverage?.selected_instrument_count ?? "—"} /{" "}
                    {coverage?.upstream_instrument_count ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>覆盖口径</dt>
                  <dd>
                    {formatPercent(coverage?.coverage_ratio ?? null, 2)} 研究样本
                  </dd>
                </div>
                <div>
                  <dt>有效报价</dt>
                  <dd>
                    {quality?.valid_quotes ?? "—"} /{" "}
                    {quality?.total_quotes ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>公共采集图</dt>
                  <dd>{collection?.feed_graph?.complete ? "完整" : "不完整"}</dd>
                </div>
              </dl>
              <p className="strategy-note">
                这是分层研究样本，不是完整期权链；页面保留真实覆盖率，不把 20
                条样本包装成全市场。
              </p>
            </article>

            <article className="strategy-panel">
              <header>
                <span>02 · 市场与波动率分析</span>
                <strong>{market?.regime_label ?? "Unavailable"}</strong>
              </header>
              <dl className="strategy-metric-grid analysis-metrics">
                <div>
                  <dt>现货</dt>
                  <dd>{formatUsd(finiteNumber(market?.spot_usd))}</dd>
                </div>
                <div>
                  <dt>DVOL / ATM IV</dt>
                  <dd>
                    {formatPercent(
                      finiteNumber(market?.dvol_percent),
                      2,
                    )}{" "}
                    /{" "}
                    {formatPercent(
                      finiteNumber(market?.near_term_atm_iv_percent),
                      2,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>DVOL − ATM</dt>
                  <dd>
                    {formatSignedPoints(
                      finiteNumber(market?.dvol_minus_atm_iv_points),
                    )}
                  </dd>
                </div>
                <div>
                  <dt>预期波动</dt>
                  <dd>
                    {formatUsd(finiteNumber(volatility?.expected_move_usd))}
                  </dd>
                </div>
                <div>
                  <dt>期限斜率</dt>
                  <dd>
                    {formatSignedPoints(
                      finiteNumber(volatility?.term_slope_iv_points),
                    )}
                  </dd>
                </div>
                <div>
                  <dt>CALL 翼溢价</dt>
                  <dd>
                    {formatSignedPoints(
                      finiteNumber(
                        volatility?.call_wing_richness_iv_points,
                      ),
                    )}
                  </dd>
                </div>
              </dl>
              <p className="strategy-note">
                Regime 仍在收集，不能把当前快照命名为趋势或震荡；期限与偏度只作结构筛选。
              </p>
            </article>
          </div>

          <article className="strategy-plan">
            <header className="strategy-plan-heading">
              <div>
                <span>03 · 主策略研究样本</span>
                <h3>卖近腿 CALL，买远腿 CALL，限定尾部风险</h3>
              </div>
              <strong>{formatExpiry(candidate?.expiry_date ?? null)}</strong>
            </header>
            <div className="strategy-legs">
              <div data-leg="sell">
                <span>卖出腿 · 研究假设</span>
                <strong>{candidate?.sell_leg ?? "—"}</strong>
                <small>
                  Strike {formatUsd(finiteNumber(candidate?.sell_strike_usd))}
                </small>
              </div>
              <span className="leg-connector" aria-hidden="true">
                →
              </span>
              <div data-leg="buy">
                <span>买入保护腿</span>
                <strong>{candidate?.buy_leg ?? "—"}</strong>
                <small>
                  Strike {formatUsd(finiteNumber(candidate?.buy_strike_usd))}
                </small>
              </div>
            </div>
            <dl className="strategy-economics">
              <div>
                <dt>净信用估值</dt>
                <dd>{formatUsd(finiteNumber(economics?.credit_usd_shadow))}</dd>
                <small>
                  {formatDecimal(finiteNumber(economics?.credit_coin), 4)} BTC
                </small>
              </div>
              <div>
                <dt>单份参考最大损失</dt>
                <dd>
                  {formatUsd(
                    finiteNumber(economics?.reference_max_loss_usd_shadow),
                  )}
                </dd>
                <small>含保守费用影子，不含滑点</small>
              </div>
              <div>
                <dt>参考盈亏平衡</dt>
                <dd>
                  {formatUsd(
                    finiteNumber(economics?.breakeven_usd_shadow),
                  )}
                </dd>
                <small>执行价 + 入场信用的 USD 影子</small>
              </div>
              <div>
                <dt>卖出腿距离</dt>
                <dd>
                  {formatPercent(
                    finiteNumber(economics?.sell_strike_distance_percent),
                    2,
                  )}
                </dd>
                <small>
                  {formatDecimal(
                    finiteNumber(
                      economics?.sell_strike_expected_move_multiple,
                    ),
                    2,
                  )}
                  × 预期波动
                </small>
              </div>
              <div>
                <dt>组合 Delta</dt>
                <dd>{formatDecimal(finiteNumber(candidate?.model_delta), 3)}</dd>
                <small>
                  RN P(ITM){" "}
                  {formatPercent(
                    finiteNumber(candidate?.risk_neutral_p_itm),
                    1,
                  )}
                </small>
              </div>
            </dl>
          </article>

          <section className="entry-contract" aria-label="条件式进场规则">
            <header className="workflow-subheading">
              <div>
                <span>04 · 进场</span>
                <h3>条件式进场规则</h3>
              </div>
              <strong data-status={playbook.entry_contract?.status}>
                {playbook.entry_contract?.status === "ready"
                  ? "条件满足"
                  : "当前不进场"}
              </strong>
            </header>
            <div className="condition-grid">
              {conditions.map((condition) => (
                <article data-status={condition.status} key={condition.id}>
                  <div>
                    <span>
                      {CONDITION_LABELS[condition.id] ?? condition.id}
                    </span>
                    <strong>
                      {CONDITION_STATUS_LABELS[condition.status] ??
                        condition.status}
                    </strong>
                  </div>
                  <p>
                    当前：{formatConditionObserved(condition.id, condition.observed)}
                  </p>
                  <small>要求：{condition.requirement ?? "见策略合同"}</small>
                </article>
              ))}
            </div>
            <p className="strategy-note entry-note">
              定价口径：卖出腿 bid − 买入腿 ask；每次刷新必须重新满足全部硬条件。
            </p>
          </section>

          <section className="risk-exit-contract" aria-label="风险与退出规则">
            <header className="workflow-subheading">
              <div>
                <span>05–06 · 风控与退出</span>
                <h3>风险与退出规则</h3>
              </div>
              <strong>模板级 · 尚未校准</strong>
            </header>
            <div className="risk-budget-strip">
              <div>
                <span>单一价差损失预算</span>
                <strong>
                  {formatPercent(
                    finiteNumber(riskBudget?.max_single_spread_loss_nav),
                    2,
                  )}{" "}
                  NAV
                </strong>
              </div>
              <div>
                <span>新增保证金上限</span>
                <strong>
                  {formatPercent(
                    finiteNumber(riskBudget?.max_new_margin_nav),
                    1,
                  )}{" "}
                  NAV
                </strong>
              </div>
              <div>
                <span>市场深度占比</span>
                <strong>
                  {formatPercent(
                    finiteNumber(riskBudget?.max_depth_fraction),
                    1,
                  )}
                </strong>
              </div>
              <div>
                <span>实际张数</span>
                <strong>不生成</strong>
                <small>缺账户快照；研究模式也禁止输出仓位</small>
              </div>
            </div>
            <div className="exit-policy-grid">
              <div>
                <h4>止盈与时间管理</h4>
                <ol className="profit-policy">
                  {(exitContract?.profit_capture ?? []).map((rule) => (
                    <li key={rule.trigger}>
                      <strong>
                        {(rule.trigger ?? "")
                          .replace("premium_capture >= ", "")
                          .replace(
                            "remaining_premium < 3_to_5x_expected_close_cost",
                            "剩余权利金 < 3–5× 平仓成本",
                          )
                          .replace(
                            "short_call_delta < 0.03",
                            "卖出腿 Delta < 0.03",
                          )}
                      </strong>
                      <span>
                        {PROFIT_RESPONSE_LABELS[rule.response ?? ""] ??
                          humanize(rule.response)}
                      </span>
                    </li>
                  ))}
                </ol>
                <p>
                  DTE ≤ {exitContract?.time_management?.review_below_dte_days ?? 7}{" "}
                  天必须复核；只在 NORMAL / CAUTION 状态允许主动滚动，且必须同时改善
                  EV、P_Touch 与总压力损失。
                </p>
              </div>
              <div>
                <h4>仓位状态阶梯</h4>
                <ol className="position-ladder">
                  {(exitContract?.position_states ?? []).map((state) => (
                    <li key={state.state} data-state={state.state}>
                      <strong>{state.state}</strong>
                      <div>
                        <span>{state.delta_condition}</span>
                        <span>{state.loss_condition}</span>
                      </div>
                      <small>
                        {POSITION_RESPONSE_LABELS[state.response ?? ""] ??
                          humanize(state.response)}
                      </small>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          </section>

          <section className="monitor-review" aria-label="监控与复盘规则">
            <div>
              <header className="workflow-subheading compact">
                <div>
                  <span>07 · 监控</span>
                  <h3>每次刷新检查</h3>
                </div>
              </header>
              <ul className="monitor-list">
                {(strategy?.monitoring ?? []).slice(0, 8).map((watch) => (
                  <li key={watch.metric}>
                    <span>
                      {MONITOR_METRIC_LABELS[watch.metric ?? ""] ??
                        humanize(watch.metric)}
                    </span>
                    <strong>{watch.trigger ?? "—"}</strong>
                    <small>
                      {MONITOR_RESPONSE_LABELS[watch.response ?? ""] ??
                        humanize(watch.response)}
                    </small>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <header className="workflow-subheading compact">
                <div>
                  <span>08 · 复盘</span>
                  <h3>升级所需证据</h3>
                </div>
              </header>
              <ol className="review-list">
                {(strategy?.review?.promotion_conditions ?? []).map(
                  (condition, index) => (
                    <li key={condition}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <p>{PROMOTION_LABELS[condition] ?? condition}</p>
                    </li>
                  ),
                )}
              </ol>
            </div>
          </section>
        </>
      ) : (
        <div className="strategy-empty" role="status">
          <strong>完整工作流已建立，但当前没有可验证的策略样本</strong>
          <p>
            采集、分析、结构、进场、风控、退出、监控与复盘八阶段均保留；只有真实证据到位后才填充。
          </p>
        </div>
      )}
    </section>
  );
}

function TruthStrip({
  freshness,
  report,
}: {
  freshness: Freshness;
  report: ResearchReport;
}): React.JSX.Element {
  const trustVerdict = report.data_trust?.verdict;
  const evidenceBoundary =
    freshness.phase === "current" && trustVerdict === "trusted"
      ? { label: "当前且可信", tone: "safe" }
      : freshness.phase === "current" &&
          report.data_status?.validated === true
        ? { label: "快照已验证 · 观察中", tone: "warning" }
      : freshness.phase === "warning" && trustVerdict === "trusted"
        ? { label: "临近失效", tone: "warning" }
        : freshness.phase === "expired"
          ? { label: "已失效", tone: "danger" }
          : { label: "不可声明", tone: "danger" };

  return (
    <section className="truth-strip" aria-label="四项运行边界">
      <dl>
        <div data-tone="safe">
          <dt>报告服务</dt>
          <dd>已连接并验证</dd>
        </div>
        <div data-tone={evidenceBoundary.tone}>
          <dt>市场证据</dt>
          <dd>{evidenceBoundary.label}</dd>
        </div>
        <div data-tone="danger">
          <dt>产品发布</dt>
          <dd>
            {report.full_system_surface?.release_readiness?.status ?? "NO-GO"}
          </dd>
        </div>
        <div data-tone="danger">
          <dt>执行边界</dt>
          <dd>RESEARCH_ONLY · NO_TRADE</dd>
        </div>
      </dl>
    </section>
  );
}

function BlockerQueue({
  blockers,
  description,
  title,
  queue,
}: {
  blockers: Blocker[];
  description: string;
  title: string;
  queue: Queue;
}): React.JSX.Element {
  return (
    <section className="blocker-queue" data-queue={queue} aria-label={title}>
      <div className="queue-heading">
        <div>
          <p className="section-kicker">{queue === "operator" ? "External" : "System"}</p>
          <h3>{title}</h3>
        </div>
        <span>{blockers.length} 项</span>
      </div>
      <p className="queue-description">{description}</p>
      <div className="blocker-list">
        {blockers.length === 0 ? (
          <p className="empty-state">当前没有此类待办。</p>
        ) : (
          blockers.map((blocker) => (
            <article className="blocker-item" key={blocker.code}>
              <div>
                <span className="owner-label">{blocker.ownerLabel}</span>
                <h4>{blocker.label}</h4>
              </div>
              <p>{blocker.action}</p>
              <code>{blocker.code}</code>
            </article>
          ))
        )}
      </div>
    </section>
  );
}

function ReleaseBoundary({
  freshness,
  operatorBlockers,
  report,
  systemBlockers,
}: {
  freshness: Freshness;
  operatorBlockers: Blocker[];
  report: ResearchReport;
  systemBlockers: Blocker[];
}): React.JSX.Element {
  const blockedOutputs = report.blocked_outputs ?? [];
  const release =
    report.full_system_surface?.release_readiness?.status ?? "NO-GO";
  return (
    <section
      id="limitations"
      className="research-section limitations-section"
      aria-labelledby="limitations-title"
    >
      <header className="research-section-heading boundary-heading">
        <div>
          <p className="section-kicker">Release boundary / 次级状态</p>
          <h2 id="limitations-title">发布与能力边界</h2>
        </div>
        <div className="release-lockup">
          <span>发布状态</span>
          <strong>{release}</strong>
        </div>
      </header>
      <TruthStrip freshness={freshness} report={report} />
      <div className="blocked-output-note">
        <div>
          <strong>策略研究已形成，执行能力保持阻断。</strong>
          <p>不会生成交易建议、推荐仓位或订单指令。缺口只影响置信度与执行升级。</p>
        </div>
        <p>
          {blockedOutputs.length} 项输出已阻断：{" "}
          {blockedOutputs
            .map((output) => OUTPUT_LABELS[output] ?? humanize(output))
            .join(" · ")}
        </p>
      </div>
      <div className="boundary-priority">
        <div>
          <span>需要外部输入</span>
          <strong>{operatorBlockers.length} 项</strong>
          <p>
            {operatorBlockers
              .slice(0, 2)
              .map((blocker) => blocker.label)
              .join(" · ") || "当前无外部输入"}
          </p>
        </div>
        <div>
          <span>系统持续补齐</span>
          <strong>{systemBlockers.length} 项</strong>
          <p>
            {systemBlockers
              .slice(0, 2)
              .map((blocker) => blocker.label)
              .join(" · ") || "当前无系统缺口"}
          </p>
        </div>
      </div>
      <details className="diagnostic-drawer">
        <summary>
          <span>查看全部缺口与责任归属</span>
          <strong>{operatorBlockers.length + systemBlockers.length} 项</strong>
        </summary>
        <div className="queue-grid">
          <BlockerQueue
            blockers={operatorBlockers}
            description="需要凭证、账户快照或独立发布复核的外部输入。"
            queue="operator"
            title="操作员与外部动作"
          />
          <BlockerQueue
            blockers={systemBlockers}
            description="系统继续采集、计算或等待观察窗口，不归责给操作员。"
            queue="system"
            title="系统延续动作"
          />
        </div>
      </details>
    </section>
  );
}

function EvidenceChain({
  report,
}: {
  report: ResearchReport;
}): React.JSX.Element {
  return (
    <section
      id="evidence-chain"
      className="research-section evidence-section"
      aria-labelledby="evidence-chain-title"
    >
      <header className="research-section-heading">
        <div>
          <p className="section-kicker">Evidence chain / 审计</p>
          <h2 id="evidence-chain-title">从市场数据到组合仲裁</h2>
        </div>
        <p>只展示报告中存在的状态；缺失值不会被估算或补齐。</p>
      </header>
      <ol className="evidence-chain">
        {evidenceItems(report).map((item) => (
          <li key={item.label} data-tone={item.tone}>
            <span className="chain-marker" aria-hidden="true" />
            <div>
              <p>{item.label}</p>
              <strong>{item.status}</strong>
              <small>{item.detail}</small>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function EvidenceConsole({
  report,
  receivedAtMs,
  nowMs,
  onRefresh,
  refreshing = false,
}: EvidenceConsoleProps): React.JSX.Element {
  const blockers = reportBlockers(report);
  const operatorBlockers = blockers.filter(
    (blocker) => blocker.queue === "operator",
  );
  const systemBlockers = blockers.filter(
    (blocker) => blocker.queue === "system",
  );
  const freshness = reportFreshness(report, receivedAtMs, nowMs);
  const facts = marketFacts(report);
  const candidates = researchCandidates(report);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#evidence-main">
        跳到主要内容
      </a>
      <Masthead
        freshness={freshness}
        onRefresh={onRefresh}
        refreshing={refreshing}
        source={facts.source}
      />
      <SectionNavigation />
      <main id="evidence-main" className="console">
        <MarketBrief
          candidates={candidates}
          facts={facts}
          freshness={freshness}
          report={report}
        />
        <StrategyFrameworkSection report={report} />
        <SurfaceResearch report={report} />
        <CandidateResearchSection candidates={candidates} report={report} />
        <ReleaseBoundary
          freshness={freshness}
          operatorBlockers={operatorBlockers}
          report={report}
          systemBlockers={systemBlockers}
        />
        <EvidenceChain report={report} />
      </main>
      <footer className="page-footer">
        <span>LensOS Option · research only</span>
        <p>真实市场数据用于研究阅读；页面不连接下单与自动执行。</p>
      </footer>
    </div>
  );
}

export type LoadReport = () => Promise<ResearchReport>;

function assertSafeResearchReport(report: ResearchReport): void {
  const gate = report.mode_gate;
  const blockedOutputs = new Set(report.blocked_outputs ?? []);
  const remainsResearchOnly =
    SAFE_RESEARCH_ACTIONS.has(report.action ?? "") &&
    report.mode === "research_only" &&
    report.effective_mode === "research_only";
  const remainsNoTrade =
    gate?.trade_recommendation_allowed === false &&
    gate.recommended_size_allowed === false &&
    gate.order_instructions_allowed === false &&
    gate.paper_manual_candidates_allowed === false &&
    REQUIRED_BLOCKED_OUTPUTS.every((output) => blockedOutputs.has(output));
  const remainsNoGo =
    report.full_system_surface?.release_readiness?.status === "NO-GO";
  if (!remainsResearchOnly || !remainsNoTrade || !remainsNoGo) {
    throw new Error("research report attempted to weaken the safety boundary");
  }
}

async function loadResearchReport(): Promise<ResearchReport> {
  const response = await fetch("/research/report", {
    cache: "no-store",
    headers: {
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    throw new Error(`report request failed with ${response.status}`);
  }
  const payload: unknown = await response.json();
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("schema_version" in payload) ||
    payload.schema_version !== "research_report.v1"
  ) {
    throw new Error("unexpected research report schema");
  }
  return payload as ResearchReport;
}

type AppState =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      report: ResearchReport;
      receivedAtMs: number;
      refreshing: boolean;
    };

interface AppProps {
  loadReport?: LoadReport;
}

function LoadingState(): React.JSX.Element {
  return (
    <div className="app-shell state-shell">
      <Masthead refreshing={false} />
      <main className="state-main">
        <section className="state-card" role="status" aria-live="polite">
          <p className="section-kicker">research_report.v1</p>
          <h1>正在读取市场研究</h1>
          <p>正在核验 Deribit 快照、波动率曲面与候选研究；不会展示推断值。</p>
          <div className="loading-rule" aria-hidden="true" />
        </section>
      </main>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }): React.JSX.Element {
  return (
    <div className="app-shell state-shell">
      <Masthead refreshing={false} />
      <main className="state-main">
        <section className="state-card error-card" role="alert">
          <p className="section-kicker">report unavailable / fail closed</p>
          <h1>研究数据不可用</h1>
          <p>报告无法验证，BTC 价格、DVOL、曲面与候选均不展示。</p>
          <div className="error-boundary">
            <span>发布</span>
            <strong>NO-GO · NO_TRADE</strong>
          </div>
          <button className="refresh-button" type="button" onClick={onRetry}>
            重新读取
          </button>
        </section>
      </main>
    </div>
  );
}

export function App({
  loadReport = loadResearchReport,
}: AppProps): React.JSX.Element {
  const [state, setState] = useState<AppState>({ status: "loading" });
  const [nowMs, setNowMs] = useState(() => Date.now());
  const requestSequence = useRef(0);

  const refresh = useCallback(async () => {
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    setState((current) =>
      current.status === "ready"
        ? { ...current, refreshing: true }
        : { status: "loading" },
    );
    try {
      const report = await loadReport();
      assertSafeResearchReport(report);
      if (requestSequence.current === sequence) {
        const receivedAtMs = Date.now();
        setNowMs(receivedAtMs);
        setState({ status: "ready", report, receivedAtMs, refreshing: false });
      }
    } catch {
      if (requestSequence.current === sequence) {
        setState({ status: "error" });
      }
    }
  }, [loadReport]);

  useEffect(() => {
    void refresh();
    return () => {
      requestSequence.current += 1;
    };
  }, [refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1_000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const handleVisibility = () => {
      if (
        document.visibilityState === "visible" &&
        state.status === "ready" &&
        !state.refreshing &&
        reportFreshness(state.report, state.receivedAtMs, Date.now()).phase !==
          "current"
      ) {
        void refresh();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refresh, state]);

  if (state.status === "loading") {
    return <LoadingState />;
  }
  if (state.status === "error") {
    return <ErrorState onRetry={() => void refresh()} />;
  }
  return (
    <EvidenceConsole
      nowMs={nowMs}
      onRefresh={() => void refresh()}
      receivedAtMs={state.receivedAtMs}
      refreshing={state.refreshing}
      report={state.report}
    />
  );
}
