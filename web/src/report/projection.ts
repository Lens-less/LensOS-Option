import type {
  CallCreditSpreadCandidate,
  CandidateResearch,
  CandidateSurfaceQuality,
  NakedCallCandidate,
  ResearchReport,
  StrategyResearch,
} from "../contracts";
import { validateResearchReport } from "./runtime";

function projectSurfaceQuality(
  quality: CandidateSurfaceQuality | undefined,
): CandidateSurfaceQuality | undefined {
  if (!quality) {
    return undefined;
  }
  return {
    fit_quality_score: quality.fit_quality_score,
    no_arb_pass: quality.no_arb_pass,
  };
}

function projectSpreadCandidate(
  candidate: CallCreditSpreadCandidate,
): CallCreditSpreadCandidate {
  return {
    candidate_id: candidate.candidate_id,
    decision: candidate.decision,
    structure_type: candidate.structure_type,
    sell_leg_instrument_name: candidate.sell_leg_instrument_name,
    buy_leg_instrument_name: candidate.buy_leg_instrument_name,
    sell_leg_strike_price: candidate.sell_leg_strike_price,
    buy_leg_strike_price: candidate.buy_leg_strike_price,
    expiry_date: candidate.expiry_date,
    dte_days: candidate.dte_days,
    model_delta: candidate.model_delta,
    net_credit: candidate.net_credit,
    spread_width: candidate.spread_width,
    premium_currency: candidate.premium_currency,
    surface_quality: projectSurfaceQuality(candidate.surface_quality),
  };
}

function projectNakedCandidate(
  candidate: NakedCallCandidate,
): NakedCallCandidate {
  return {
    candidate_id: candidate.candidate_id,
    decision: candidate.decision,
    structure_type: candidate.structure_type,
    instrument_name: candidate.instrument_name,
    expiry_date: candidate.expiry_date,
    dte_days: candidate.dte_days,
    model_delta: candidate.model_delta,
    market_mid: candidate.market_mid,
    premium_currency: candidate.premium_currency,
    surface_quality: projectSurfaceQuality(candidate.surface_quality),
  };
}

function projectCandidateResearch(
  candidates: CandidateResearch | undefined,
): CandidateResearch | undefined {
  if (!candidates) {
    return undefined;
  }

  return {
    call_credit_spreads: candidates.call_credit_spreads
      ? {
          eligible:
            candidates.call_credit_spreads.eligible?.map(
              projectSpreadCandidate,
            ) ?? [],
          review:
            candidates.call_credit_spreads.review?.map(
              projectSpreadCandidate,
            ) ?? [],
          rejected:
            candidates.call_credit_spreads.rejected?.map(
              projectSpreadCandidate,
            ) ?? [],
        }
      : undefined,
    naked_short_calls: candidates.naked_short_calls
      ? {
          eligible:
            candidates.naked_short_calls.eligible?.map(projectNakedCandidate) ??
            [],
          review:
            candidates.naked_short_calls.review?.map(projectNakedCandidate) ??
            [],
          rejected:
            candidates.naked_short_calls.rejected?.map(projectNakedCandidate) ??
            [],
        }
      : undefined,
  };
}

function projectStrategy(
  strategy: StrategyResearch | undefined,
): StrategyResearch | undefined {
  if (!strategy) {
    return undefined;
  }

  const playbook = strategy.playbook;
  const exitContract = playbook?.exit_contract;

  return {
    schema_version: strategy.schema_version,
    execution_allowed: strategy.execution_allowed,
    decision: strategy.decision
      ? {
          stance: strategy.decision.stance,
          primary_structure: strategy.decision.primary_structure,
          summary: strategy.decision.summary,
          why_now: strategy.decision.why_now,
          why_not: strategy.decision.why_not,
        }
      : undefined,
    playbook: playbook
      ? {
          candidate: playbook.candidate
            ? {
                candidate_id: playbook.candidate.candidate_id,
                expiry_date: playbook.candidate.expiry_date,
                dte_days: playbook.candidate.dte_days,
                sell_leg: playbook.candidate.sell_leg,
                buy_leg: playbook.candidate.buy_leg,
              }
            : undefined,
          economics: playbook.economics
            ? {
                credit_usd_shadow: playbook.economics.credit_usd_shadow,
                reference_max_loss_usd_shadow:
                  playbook.economics.reference_max_loss_usd_shadow,
              }
            : undefined,
          entry_contract: playbook.entry_contract
            ? {
                status: playbook.entry_contract.status,
                conditions: playbook.entry_contract.conditions,
              }
            : undefined,
          risk_budget: playbook.risk_budget
            ? {
                sizing_status: playbook.risk_budget.sizing_status,
                max_single_spread_loss_nav:
                  playbook.risk_budget.max_single_spread_loss_nav,
                note: playbook.risk_budget.note,
              }
            : undefined,
          exit_contract: exitContract
            ? {
                policy_status: exitContract.policy_status,
                profit_capture: exitContract.profit_capture,
                position_states: exitContract.position_states,
                time_management: exitContract.time_management
                  ? {
                      review_below_dte_days:
                        exitContract.time_management.review_below_dte_days,
                      roll_allowed_states:
                        exitContract.time_management.roll_allowed_states,
                      roll_delta_band:
                        exitContract.time_management.roll_delta_band,
                      roll_must_improve:
                        exitContract.time_management.roll_must_improve,
                      loss_deferral_alone_is_forbidden:
                        exitContract.time_management
                          .loss_deferral_alone_is_forbidden,
                    }
                  : undefined,
                kill_switches: exitContract.kill_switches,
              }
            : undefined,
        }
      : playbook === null
        ? null
        : undefined,
    strategy_selection: strategy.strategy_selection
      ? {
          selection_method: strategy.strategy_selection.selection_method,
          eligible_spread_count:
            strategy.strategy_selection.eligible_spread_count,
          ranked_candidate_ids:
            strategy.strategy_selection.ranked_candidate_ids,
          ranking_dimensions: strategy.strategy_selection.ranking_dimensions,
        }
      : undefined,
    monitoring: strategy.monitoring,
    review: strategy.review
      ? {
          status: strategy.review.status,
          backtest_status: strategy.review.backtest_status,
          calibration_status: strategy.review.calibration_status,
          path_risk_status: strategy.review.path_risk_status,
          missing_evidence: strategy.review.missing_evidence,
          promotion_conditions: strategy.review.promotion_conditions,
        }
      : undefined,
  };
}

/**
 * `report.ev_candidate_scanner` is new backend surface not yet declared on
 * the shared `ResearchReport` contract (see `crypto_options_report/ev_scanner.py`).
 * These local shapes describe it structurally without widening that contract,
 * matching only the fields the side panel is allowed to read.
 */
export interface EvCandidatePathRiskProjection {
  status?: string;
  reason_code?: string | null;
  p_touch?: number | null;
  p_itm?: number | null;
  cvar_95_usdc?: number | null;
  authoritative_sample_size?: number | null;
  sample_size_basis?: string | null;
}

export interface EvCandidateComparisonRow {
  candidate_id: string | null;
  structure_type: string | null;
  action: string | null;
  ranking_score: number | null;
  ev_after_cost_usdc: number | null;
  executable_credit_usdc: number | null;
  path_risk: EvCandidatePathRiskProjection | null;
  kill_conditions: string[];
  dominated_by: string | null;
  losing_axes: string[];
}

export interface EvCandidateRankingBasisProjection {
  method?: string;
  tie_break_order?: string[];
  absolute_ev_available?: boolean;
}

export interface EvCandidateScannerProjection {
  status?: string;
  score_status?: string;
  ranking_basis?: EvCandidateRankingBasisProjection;
  ranked_candidates: EvCandidateComparisonRow[];
  rejected_count: number;
}

/** Structural view of the raw, undeclared `ev_candidate_scanner` payload. */
interface RawEvCandidateScanner {
  status?: unknown;
  score_status?: unknown;
  ranking_basis?: {
    method?: unknown;
    tie_break_order?: unknown;
    absolute_ev_available?: unknown;
  } | null;
  ranked_candidates?: unknown[];
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNumberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function projectEvCandidatePathRisk(
  value: unknown,
): EvCandidatePathRiskProjection | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const raw = value as Record<string, unknown>;
  return {
    status: typeof raw.status === "string" ? raw.status : undefined,
    reason_code: asStringOrNull(raw.reason_code),
    p_touch: asNumberOrNull(raw.p_touch),
    p_itm: asNumberOrNull(raw.p_itm),
    cvar_95_usdc: asNumberOrNull(raw.cvar_95_usdc),
    authoritative_sample_size: asNumberOrNull(raw.authoritative_sample_size),
    sample_size_basis: asStringOrNull(raw.sample_size_basis),
  };
}

function projectEvCandidateRow(value: unknown): EvCandidateComparisonRow | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const raw = value as Record<string, unknown>;
  return {
    candidate_id: asStringOrNull(raw.candidate_id),
    structure_type: asStringOrNull(raw.structure_type),
    action: asStringOrNull(raw.action),
    ranking_score: asNumberOrNull(raw.ranking_score),
    ev_after_cost_usdc: asNumberOrNull(raw.ev_after_cost_usdc),
    executable_credit_usdc: asNumberOrNull(raw.executable_credit_usdc),
    path_risk: projectEvCandidatePathRisk(raw.path_risk),
    kill_conditions: asStringArray(raw.kill_conditions),
    dominated_by: asStringOrNull(raw.dominated_by),
    losing_axes: asStringArray(raw.losing_axes),
  };
}

/**
 * Trim `ev_candidate_scanner` to the O(candidate-count) scalars the
 * comparison surface needs. `edge_components`, `fair_iv_diagnostics`,
 * `margin_snapshot`, and `path_risk_evidence` are dense, evidence-shaped
 * blobs and are deliberately dropped here, same as `vol_surface_status`.
 * REJECT rows are dropped to a single count rather than copied in full,
 * since a chain can reject far more candidates than the panel ever compares.
 */
function projectEvCandidateScanner(
  scanner: unknown,
): EvCandidateScannerProjection | undefined {
  if (!scanner || typeof scanner !== "object") {
    return undefined;
  }
  const raw = scanner as RawEvCandidateScanner;
  const rankingBasisRaw = raw.ranking_basis;
  const rows = Array.isArray(raw.ranked_candidates)
    ? raw.ranked_candidates
        .map(projectEvCandidateRow)
        .filter((row): row is EvCandidateComparisonRow => row !== null)
    : [];
  const kept = rows.filter((row) => row.action !== "REJECT");
  const rejectedCount = rows.length - kept.length;

  return {
    status: typeof raw.status === "string" ? raw.status : undefined,
    score_status: typeof raw.score_status === "string" ? raw.score_status : undefined,
    ranking_basis: rankingBasisRaw
      ? {
          method:
            typeof rankingBasisRaw.method === "string"
              ? rankingBasisRaw.method
              : undefined,
          tie_break_order: asStringArray(rankingBasisRaw.tie_break_order),
          absolute_ev_available:
            typeof rankingBasisRaw.absolute_ev_available === "boolean"
              ? rankingBasisRaw.absolute_ev_available
              : undefined,
        }
      : undefined,
    ranked_candidates: kept,
    rejected_count: rejectedCount,
  };
}

/**
 * Keep the complete report inside the worker's HTTP boundary. Runtime messages
 * carry only the fields required by the compact side panel and its fail-closed
 * validator; dense lineage and analytical surfaces remain in Evidence Console.
 */
export function projectResearchReportForSidePanel(
  payload: unknown,
): ResearchReport {
  const report = validateResearchReport(payload);
  const evCandidateScanner = projectEvCandidateScanner(
    (report as ResearchReport & { ev_candidate_scanner?: unknown })
      .ev_candidate_scanner,
  );
  const projected: ResearchReport & {
    ev_candidate_scanner?: EvCandidateScannerProjection;
  } = {
    schema_version: report.schema_version,
    action: report.action,
    mode: report.mode,
    effective_mode: report.effective_mode,
    blocked_outputs: report.blocked_outputs,
    mode_gate: report.mode_gate
      ? {
          trade_recommendation_allowed:
            report.mode_gate.trade_recommendation_allowed,
          recommended_size_allowed: report.mode_gate.recommended_size_allowed,
          order_instructions_allowed:
            report.mode_gate.order_instructions_allowed,
          paper_manual_candidates_allowed:
            report.mode_gate.paper_manual_candidates_allowed,
        }
      : undefined,
    data_trust: report.data_trust
      ? {
          verdict: report.data_trust.verdict,
        }
      : undefined,
    data_status: report.data_status
      ? {
          source: report.data_status.source,
          market_data_age_sec: report.data_status.market_data_age_sec,
          quality_gate: report.data_status.quality_gate
            ? {
                reason_codes: report.data_status.quality_gate.reason_codes,
                advisory_reason_codes:
                  report.data_status.quality_gate.advisory_reason_codes,
                thresholds: report.data_status.quality_gate.thresholds
                  ? {
                      market_data_max_age_sec:
                        report.data_status.quality_gate.thresholds
                          .market_data_max_age_sec,
                    }
                  : undefined,
              }
            : undefined,
        }
      : undefined,
    candidate_research: projectCandidateResearch(report.candidate_research),
    strategy_research: projectStrategy(report.strategy_research),
    ev_candidate_scanner: evCandidateScanner,
    full_system_surface: {
      release_readiness: {
        status: report.full_system_surface?.release_readiness?.status,
      },
    },
  };

  return validateResearchReport(
    projected,
  ) as ResearchReport & { ev_candidate_scanner?: EvCandidateScannerProjection };
}
