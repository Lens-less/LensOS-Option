import type { ResearchReport } from "../contracts";
import type { LoadedReport } from "../transport";

export const strategyResearchFixture: NonNullable<
  ResearchReport["strategy_research"]
> = {
  schema_version: "strategy_research.v1",
  generated_at: "2026-07-24T10:25:00Z",
  status: "partial",
  advisory_only: true,
  execution_allowed: false,
  confidence_ceiling: "screening_only",
  pipeline: [
    { stage: "COLLECT", status: "ready" },
    { stage: "ANALYZE", status: "ready" },
    { stage: "SELECT", status: "ready" },
    { stage: "ENTER", status: "blocked" },
    { stage: "RISK", status: "partial" },
    { stage: "EXIT", status: "partial" },
    { stage: "MONITOR", status: "ready" },
    { stage: "REVIEW", status: "blocked" },
  ],
  decision: {
    stance: "MONITOR_ONLY",
    primary_structure: "CALL_CREDIT_SPREAD",
    entry_readiness: "BLOCKED",
    summary:
      "A defined-risk call credit spread is the primary screening setup; activation gates remain closed.",
    why_now: [
      "20/20 sampled quotes pass the market-data gate.",
      "5 defined-risk call credit spreads pass observable screening.",
    ],
    why_not: [
      "Regime evidence has not been promoted.",
      "A fresh read-only account snapshot is unavailable.",
      "Validated path-risk and EV ranking are unavailable.",
    ],
  },
  collection: {
    status: "validated",
    source: "deribit_live:https://www.deribit.com",
    market_data_age_sec: 4,
    coverage: {
      scope: "research_sample",
      selected_instrument_count: 20,
      upstream_instrument_count: 864,
      coverage_ratio: 0.0231,
      is_research_sample: true,
    },
    quality: {
      valid_quotes: 20,
      total_quotes: 20,
      invalid_quotes: 0,
      fetch_errors: 0,
      expiries_evaluated: 2,
    },
    feed_graph: {
      complete: true,
      missing_required_feeds: [],
    },
  },
  playbook: {
    playbook_id:
      "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
    structure: "CALL_CREDIT_SPREAD",
    candidate: {
      candidate_id:
        "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
      expiry_date: "2026-08-07",
      dte_days: 13.9,
      sell_leg: "BTC-7AUG26-71000-C",
      buy_leg: "BTC-7AUG26-77000-C",
      sell_strike_usd: 71_000,
      buy_strike_usd: 77_000,
      model_delta: 0.087,
      risk_neutral_p_itm: 0.106,
      surface_fit_quality: 0.9687,
    },
    entry_contract: {
      status: "blocked",
      conditions: [
        {
          id: "market_quality",
          label: "Market snapshot passes the quality gate",
          observed: "validated",
          requirement: "validated",
          status: "pass",
          blocking: true,
        },
        {
          id: "regime_permission",
          label: "Promoted regime evidence permits credit spreads",
          observed: { status: "blocked", spread_permission: false },
          requirement: "validated and true",
          status: "block",
          blocking: true,
        },
      ],
    },
    economics: {
      credit_usd_shadow: 720,
      reference_max_loss_usd_shadow: 3_280,
      assumption: "Reference economics only; not an executable quote.",
    },
    risk_budget: {
      contracts: null,
      note: "No contract count is emitted in research-only mode.",
      sizing_status: "account_input_missing",
      max_single_spread_loss_nav: 0.005,
    },
    exit_contract: {
      policy_status: "template_only_uncalibrated",
      profit_capture: [
        {
          trigger: "premium_capture >= 60%",
          response: "close_50_percent",
          validated: false,
        },
      ],
      position_states: [
        {
          state: "review",
          delta_condition: "short_leg_delta >= 0.20",
          loss_condition: "loss >= 0.50 * reference_max_loss",
          response: "reduce_or_close_after_fresh_research",
        },
      ],
      time_management: {
        review_below_dte_days: 7,
        roll_allowed_states: ["healthy", "review"],
        roll_delta_band: [0.08, 0.16],
        roll_must_improve: ["stress_loss", "expiry_distance"],
        loss_deferral_alone_is_forbidden: true,
      },
      kill_switches: ["market data age > 60 sec"],
    },
  },
  monitoring: [
    {
      metric: "market_age_sec",
      current: 4,
      trigger: "> 60 sec",
      response: "pause_research_setup",
      cadence: "every_refresh",
    },
  ],
  review: {
    status: "blocked",
    backtest_status: "not_run",
    calibration_status: "unavailable",
    path_risk_status: "unavailable",
    missing_evidence: [
      "MISSING_ACCOUNT_API_SNAPSHOT",
      "CALIBRATION_NOT_IMPLEMENTED",
    ],
    promotion_conditions: [
      "Persist enough rolling observations to promote regime evidence.",
      "Run an aligned bounded backtest on licensed historical data.",
    ],
  },
};

export const safeResearchReport: ResearchReport = {
  schema_version: "research_report.v1",
  generated_at: "2026-07-24T10:25:00Z",
  action: "RESEARCH_ONLY",
  mode: "research_only",
  effective_mode: "research_only",
  risk_state: "HALT",
  blocked_outputs: [
    "trade_recommendation",
    "recommended_size",
    "order_instructions",
    "paper_manual_trade_candidates",
  ],
  data_trust: {
    verdict: "trusted",
    source_class: "validated",
    reason_codes: [],
  },
  data_status: {
    status: "validated",
    source: "deribit_live:https://www.deribit.com",
    validated: true,
    market_data_age_sec: 4,
    quality_gate: {
      passed: true,
      thresholds: {
        market_data_max_age_sec: 60,
      },
    },
  },
  mode_gate: {
    trade_recommendation_allowed: false,
    recommended_size_allowed: false,
    order_instructions_allowed: false,
    paper_manual_candidates_allowed: false,
  },
  strategy_research: strategyResearchFixture,
  full_system_surface: {
    release_readiness: {
      status: "NO-GO",
    },
  },
};

export function buildLoadedReport(overrides?: {
  report?: ResearchReport;
  receivedAtMs?: number;
  etag?: string;
  analysisRunId?: string;
  cached?: boolean;
}): LoadedReport {
  return {
    report: overrides?.report ?? safeResearchReport,
    receivedAtMs:
      overrides?.receivedAtMs ?? Date.parse("2026-07-24T10:25:04Z"),
    etag: overrides?.etag,
    analysisRunId: overrides?.analysisRunId,
    cached: overrides?.cached,
  };
}
