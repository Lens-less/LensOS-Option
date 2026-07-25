import type {
  ResearchReport,
  StrategyCondition,
  StrategyResearch,
} from "../contracts";
import type { LoadedReport } from "../transport/http";
import { finiteNumber } from "./numbers";

export type FreshnessPhase = "current" | "warning" | "expired" | "unavailable";
export type DeribitContractMatchStatus =
  | "sell_leg"
  | "buy_leg"
  | "strategy_candidate"
  | "mismatch"
  | "unknown";

export interface ReportFreshness {
  ageSec: number | null;
  maxAgeSec: number;
  phase: FreshnessPhase;
}

export interface DeribitContractMatch {
  currentInstrumentName: string | null;
  candidateId: string | null;
  sellLeg: string | null;
  buyLeg: string | null;
  status: DeribitContractMatchStatus;
  message: string;
}

export interface SidePanelEntryConditionViewModel {
  id: string;
  label: string;
  status: "pass" | "block" | "unknown";
  blocking: boolean;
  requirement: string | null;
  observed: unknown;
  reason: string | null;
}

export interface SidePanelReviewViewModel {
  status: string | null;
  backtestStatus: string | null;
  calibrationStatus: string | null;
  pathRiskStatus: string | null;
  missingEvidence: string[];
  promotionConditions: string[];
}

export interface SidePanelViewModel {
  sourceLabel: string;
  trustVerdict: string | null;
  freshness: ReportFreshness;
  analysisRunId?: string;
  etag?: string;
  cached?: boolean;
  contractMatch: DeribitContractMatch;
  stance: string | null;
  summary: string | null;
  primaryStructure: string | null;
  whyNow: string[];
  whyNot: string[];
  strategyCandidateId: string | null;
  sellLeg: string | null;
  buyLeg: string | null;
  expiryDate: string | null;
  dteDays: number | null;
  entryStatus: string | null;
  entryConditions: SidePanelEntryConditionViewModel[];
  riskNote: string | null;
  riskSizingStatus: string | null;
  maxSingleSpreadLossNav: number | null;
  referenceCreditUsdShadow: number | null;
  referenceMaxLossUsdShadow: number | null;
  exitPolicyStatus: string | null;
  exitProfitCapture: Array<{ trigger: string | null; response: string | null }>;
  exitPositionStates: Array<{
    state: string | null;
    deltaCondition: string | null;
    lossCondition: string | null;
    response: string | null;
  }>;
  exitTimeManagement: {
    reviewBelowDteDays: number | null;
    rollAllowedStates: string[];
    rollDeltaBand: number[];
    rollMustImprove: string[];
    lossDeferralAloneIsForbidden: boolean | null;
  };
  exitKillSwitches: string[];
  monitoring: Array<{
    metric: string | null;
    current: unknown;
    trigger: string | null;
    response: string | null;
    cadence: string | null;
  }>;
  review: SidePanelReviewViewModel;
}

function strategyConditionLabel(condition: StrategyCondition): string {
  return condition.label?.trim() || condition.id;
}

export function selectReportFreshness(
  report: ResearchReport,
  receivedAtMs: number,
  nowMs: number,
): ReportFreshness {
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

function selectContractMatch(
  report: ResearchReport,
  strategy: StrategyResearch | undefined,
  currentInstrumentName: string | null | undefined,
): DeribitContractMatch {
  const normalizedCurrent = currentInstrumentName?.trim() || null;
  const candidate = strategy?.playbook?.candidate;
  const sellLeg = candidate?.sell_leg ?? null;
  const buyLeg = candidate?.buy_leg ?? null;
  const candidateId = candidate?.candidate_id ?? null;

  if (!normalizedCurrent) {
    return {
      currentInstrumentName: null,
      candidateId,
      sellLeg,
      buyLeg,
      status: "unknown",
      message: "尚未识别 Deribit 合约；请打开期权详情页或手动输入完整合约名。",
    };
  }

  if (normalizedCurrent === sellLeg) {
    return {
      currentInstrumentName: normalizedCurrent,
      candidateId,
      sellLeg,
      buyLeg,
      status: "sell_leg",
      message: "当前 Deribit 合约与主研究结构的卖腿一致。",
    };
  }

  if (normalizedCurrent === buyLeg) {
    return {
      currentInstrumentName: normalizedCurrent,
      candidateId,
      sellLeg,
      buyLeg,
      status: "buy_leg",
      message: "当前 Deribit 合约与主研究结构的保护腿一致。",
    };
  }

  if (normalizedCurrent === candidateId) {
    return {
      currentInstrumentName: normalizedCurrent,
      candidateId,
      sellLeg,
      buyLeg,
      status: "strategy_candidate",
      message: "当前选择与主研究候选标识一致。",
    };
  }

  const candidateResearch = report.candidate_research;
  const spreadCandidates = [
    ...(candidateResearch?.call_credit_spreads?.eligible ?? []),
    ...(candidateResearch?.call_credit_spreads?.review ?? []),
    ...(candidateResearch?.call_credit_spreads?.rejected ?? []),
  ];
  const matchingSpread = spreadCandidates.find(
    (spread) =>
      spread.sell_leg_instrument_name === normalizedCurrent ||
      spread.buy_leg_instrument_name === normalizedCurrent,
  );
  if (matchingSpread) {
    return {
      currentInstrumentName: normalizedCurrent,
      candidateId: matchingSpread.candidate_id ?? null,
      sellLeg: matchingSpread.sell_leg_instrument_name ?? null,
      buyLeg: matchingSpread.buy_leg_instrument_name ?? null,
      status: "strategy_candidate",
      message:
        "当前合约出现在研究候选集中，但不是主 playbook；以下结论是组合研究，不是该合约的专属进场信号。",
    };
  }

  const nakedCandidates = [
    ...(candidateResearch?.naked_short_calls?.eligible ?? []),
    ...(candidateResearch?.naked_short_calls?.review ?? []),
    ...(candidateResearch?.naked_short_calls?.rejected ?? []),
  ];
  const matchingNaked = nakedCandidates.find(
    (candidateRow) => candidateRow.instrument_name === normalizedCurrent,
  );
  if (matchingNaked) {
    return {
      currentInstrumentName: normalizedCurrent,
      candidateId: matchingNaked.candidate_id ?? null,
      sellLeg: matchingNaked.instrument_name ?? null,
      buyLeg: null,
      status: "strategy_candidate",
      message:
        "当前合约仅出现在研究对照集中；裸卖看涨仍是被拒绝的研究备选，不是进场信号。",
    };
  }

  return {
    currentInstrumentName: normalizedCurrent,
    candidateId,
    sellLeg,
    buyLeg,
    status: "mismatch",
    message:
      "当前 Deribit 合约未被本次主研究结构覆盖；不要把全局 BTC 结论当作该合约的专属进场信号。",
  };
}

export function selectSidePanelViewModel(
  loaded: LoadedReport,
  options?: {
    nowMs?: number;
    currentInstrumentName?: string | null;
  },
): SidePanelViewModel {
  const report = loaded.report;
  const strategy = report.strategy_research;
  const candidate = strategy?.playbook?.candidate;
  const entryConditions = strategy?.playbook?.entry_contract?.conditions ?? [];
  const exitContract = strategy?.playbook?.exit_contract;
  const riskBudget = strategy?.playbook?.risk_budget;
  const economics = strategy?.playbook?.economics;
  const nowMs = options?.nowMs ?? loaded.receivedAtMs;

  return {
    sourceLabel: report.data_status?.source ?? "not_configured",
    trustVerdict: report.data_trust?.verdict ?? null,
    freshness: selectReportFreshness(report, loaded.receivedAtMs, nowMs),
    analysisRunId: loaded.analysisRunId,
    etag: loaded.etag,
    cached: loaded.cached,
    contractMatch: selectContractMatch(
      report,
      strategy,
      options?.currentInstrumentName ?? null,
    ),
    stance: strategy?.decision?.stance ?? null,
    summary: strategy?.decision?.summary ?? null,
    primaryStructure: strategy?.decision?.primary_structure ?? null,
    whyNow: strategy?.decision?.why_now ?? [],
    whyNot: strategy?.decision?.why_not ?? [],
    strategyCandidateId: candidate?.candidate_id ?? null,
    sellLeg: candidate?.sell_leg ?? null,
    buyLeg: candidate?.buy_leg ?? null,
    expiryDate: candidate?.expiry_date ?? null,
    dteDays: finiteNumber(candidate?.dte_days),
    entryStatus: strategy?.playbook?.entry_contract?.status ?? null,
    entryConditions: entryConditions.map((condition) => ({
      id: condition.id,
      label: strategyConditionLabel(condition),
      status: condition.status,
      blocking: Boolean(condition.blocking),
      requirement: condition.requirement ?? null,
      observed: condition.observed,
      reason: condition.reason ?? null,
    })),
    riskNote: riskBudget?.note ?? null,
    riskSizingStatus: riskBudget?.sizing_status ?? null,
    maxSingleSpreadLossNav: finiteNumber(
      riskBudget?.max_single_spread_loss_nav,
    ),
    referenceCreditUsdShadow: finiteNumber(economics?.credit_usd_shadow),
    referenceMaxLossUsdShadow: finiteNumber(
      economics?.reference_max_loss_usd_shadow,
    ),
    exitPolicyStatus: exitContract?.policy_status ?? null,
    exitProfitCapture: (exitContract?.profit_capture ?? []).map((rule) => ({
      trigger: rule.trigger ?? null,
      response: rule.response ?? null,
    })),
    exitPositionStates: (exitContract?.position_states ?? []).map((state) => ({
      state: state.state ?? null,
      deltaCondition: state.delta_condition ?? null,
      lossCondition: state.loss_condition ?? null,
      response: state.response ?? null,
    })),
    exitTimeManagement: {
      reviewBelowDteDays: finiteNumber(
        exitContract?.time_management?.review_below_dte_days,
      ),
      rollAllowedStates:
        exitContract?.time_management?.roll_allowed_states ?? [],
      rollDeltaBand: exitContract?.time_management?.roll_delta_band ?? [],
      rollMustImprove:
        exitContract?.time_management?.roll_must_improve ?? [],
      lossDeferralAloneIsForbidden:
        typeof exitContract?.time_management?.loss_deferral_alone_is_forbidden ===
        "boolean"
          ? exitContract.time_management.loss_deferral_alone_is_forbidden
          : null,
    },
    exitKillSwitches: exitContract?.kill_switches ?? [],
    monitoring: (strategy?.monitoring ?? []).map((item) => ({
      metric: item.metric ?? null,
      current: item.current,
      trigger: item.trigger ?? null,
      response: item.response ?? null,
      cadence: item.cadence ?? null,
    })),
    review: {
      status: strategy?.review?.status ?? null,
      backtestStatus: strategy?.review?.backtest_status ?? null,
      calibrationStatus: strategy?.review?.calibration_status ?? null,
      pathRiskStatus: strategy?.review?.path_risk_status ?? null,
      missingEvidence: strategy?.review?.missing_evidence ?? [],
      promotionConditions: strategy?.review?.promotion_conditions ?? [],
    },
  };
}
