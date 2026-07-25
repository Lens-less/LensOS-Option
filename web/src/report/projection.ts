import type {
  CallCreditSpreadCandidate,
  CandidateResearch,
  NakedCallCandidate,
  ResearchReport,
  StrategyResearch,
} from "../contracts";
import { validateResearchReport } from "./runtime";

function projectSpreadCandidate(
  candidate: CallCreditSpreadCandidate,
): CallCreditSpreadCandidate {
  return {
    candidate_id: candidate.candidate_id,
    sell_leg_instrument_name: candidate.sell_leg_instrument_name,
    buy_leg_instrument_name: candidate.buy_leg_instrument_name,
  };
}

function projectNakedCandidate(
  candidate: NakedCallCandidate,
): NakedCallCandidate {
  return {
    candidate_id: candidate.candidate_id,
    instrument_name: candidate.instrument_name,
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
 * Keep the complete report inside the worker's HTTP boundary. Runtime messages
 * carry only the fields required by the compact side panel and its fail-closed
 * validator; dense lineage and analytical surfaces remain in Evidence Console.
 */
export function projectResearchReportForSidePanel(
  payload: unknown,
): ResearchReport {
  const report = validateResearchReport(payload);
  const projected: ResearchReport = {
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
    full_system_surface: {
      release_readiness: {
        status: report.full_system_surface?.release_readiness?.status,
      },
    },
  };

  return validateResearchReport(projected);
}
