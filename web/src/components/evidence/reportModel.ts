import type { ReleasePrerequisite, ResearchReport } from "../../contracts";
import type { FreshnessPhase, ReportFreshness } from "../../report";
import { finiteNumber } from "../../report";

export { selectReportFreshness as reportFreshness } from "../../report";
export { finiteNumber };
export type Freshness = ReportFreshness;

export type Queue = "operator" | "system";
export type Tone = "danger" | "muted" | "safe" | "warning";

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

export const OUTPUT_LABELS: Record<string, string> = {
  order_instructions: "订单指令",
  paper_manual_trade_candidates: "Paper 手工候选",
  recommended_size: "推荐仓位",
  trade_recommendation: "交易建议",
};

export interface Blocker {
  action: string;
  code: string;
  label: string;
  ownerLabel: string;
  queue: Queue;
}

interface EvidenceItem {
  detail: string;
  label: string;
  status: string;
  tone: Tone;
}

export const FRESHNESS_LABELS: Record<FreshnessPhase, string> = {
  current: "当前",
  warning: "预警",
  expired: "已失效",
  unavailable: "不可用",
};

export function humanize(value: string | null | undefined, fallback = "未提供"): string {
  if (!value) {
    return fallback;
  }
  return value.replaceAll("_", " ");
}

export function displayStatus(
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

export function friendlySource(value: string | null | undefined): string {
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

export function reportBlockers(report: ResearchReport): Blocker[] {
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

export function evidenceItems(report: ResearchReport): EvidenceItem[] {
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
