export interface EvidenceDataStatus {
  status?: string;
  source?: string;
  validated?: boolean;
  reason_code?: string | null;
  market_data_age_sec?: number | null;
  collection_scope?: {
    selected_instrument_count?: number;
    upstream_instrument_count?: number;
    coverage_ratio?: number;
    scope?: string;
  };
  public_response_contract?: {
    endpoints?: {
      vol_index?: {
        status?: string;
        volatility?: number | null;
        index_name?: string;
        age_sec?: number | null;
        max_age_sec?: number | null;
      };
    };
  };
  quality_gate?: {
    passed?: boolean;
    summary?: {
      expiries_evaluated?: number;
      fetch_errors?: number;
      invalid_quotes?: number;
      market_data_age_sec?: number | null;
      total_quotes?: number;
      valid_quotes?: number;
    };
    thresholds?: {
      market_data_max_age_sec?: number;
    };
  };
}

export interface SurfacePoint {
  instrument_name?: string;
  strike_price?: number;
  market_mark_iv?: number;
  surface_fitted_iv?: number;
  underlying_price?: number;
}

export interface SurfaceExpiry {
  candidate_eligible?: boolean;
  dte_days?: number;
  expiry_date?: string;
  fit_quality_pass?: boolean;
  fit_quality_score?: number;
  no_arb_error?: number;
  no_arb_pass?: boolean;
  quality_passing_quotes?: number;
  reason_codes?: string[];
  surface_points?: SurfacePoint[];
}

export interface CandidateSurfaceQuality {
  fit_quality_score?: number;
  no_arb_error?: number;
  no_arb_pass?: boolean;
}

export interface NakedCallCandidate {
  candidate_id?: string;
  decision?: string;
  dte_days?: number;
  expiry_date?: string;
  instrument_name?: string;
  market_mark_iv?: number;
  market_mid?: number;
  model_delta?: number;
  premium_currency?: string;
  structure_type?: string;
  surface_fitted_iv?: number;
  surface_quality?: CandidateSurfaceQuality;
  underlying_price?: number;
}

export interface CallCreditSpreadCandidate {
  buy_leg_instrument_name?: string;
  buy_leg_strike_price?: number;
  candidate_id?: string;
  decision?: string;
  dte_days?: number;
  expiry_date?: string;
  model_delta?: number;
  net_credit?: number;
  premium_currency?: string;
  sell_leg_instrument_name?: string;
  sell_leg_strike_price?: number;
  spread_width?: number;
  structure_type?: string;
  surface_quality?: CandidateSurfaceQuality;
  underlying_price?: number;
}

export interface CandidateResearch {
  status?: string;
  reason_code?: string | null;
  summary?: {
    eligible_call_credit_spreads?: number;
    eligible_expiries?: number;
    eligible_naked_short_calls?: number;
    expiries_considered?: number;
    rejected_call_credit_spreads?: number;
    rejected_naked_short_calls?: number;
    review_call_credit_spreads?: number;
    review_naked_short_calls?: number;
  };
  naked_short_calls?: {
    eligible?: NakedCallCandidate[];
    rejected?: NakedCallCandidate[];
    review?: NakedCallCandidate[];
  };
  call_credit_spreads?: {
    eligible?: CallCreditSpreadCandidate[];
    rejected?: CallCreditSpreadCandidate[];
    review?: CallCreditSpreadCandidate[];
  };
}

export interface StrategyPipelineStage {
  stage:
    | "COLLECT"
    | "ANALYZE"
    | "SELECT"
    | "ENTER"
    | "RISK"
    | "EXIT"
    | "MONITOR"
    | "REVIEW";
  status: "ready" | "partial" | "blocked";
  output?: string;
}

export interface StrategyCondition {
  id: string;
  label: string;
  observed?: unknown;
  requirement?: string;
  status: "pass" | "block" | "unknown";
  blocking?: boolean;
  reason?: string;
}

export interface StrategyResearch {
  schema_version: "strategy_research.v1";
  generated_at?: string;
  status?: "partial" | "blocked";
  advisory_only?: boolean;
  execution_allowed?: boolean;
  confidence_ceiling?: "screening_only" | "insufficient_data";
  pipeline?: StrategyPipelineStage[];
  decision?: {
    stance?: "NO_RESEARCH_SETUP" | "MONITOR_ONLY" | "CONDITIONAL_RESEARCH";
    primary_structure?: "CALL_CREDIT_SPREAD" | null;
    entry_readiness?: "BLOCKED" | "CONDITIONAL";
    summary?: string;
    why_now?: string[];
    why_not?: string[];
    rejected_structures?: Array<{
      structure?: string;
      status?: string;
      reason_codes?: string[];
    }>;
  };
  collection?: {
    status?: string;
    source?: string;
    captured_at?: string | null;
    market_data_age_sec?: number | null;
    coverage?: {
      scope?: string | null;
      selected_instrument_count?: number;
      upstream_instrument_count?: number;
      coverage_ratio?: number | null;
      is_research_sample?: boolean;
    };
    quality?: {
      valid_quotes?: number;
      total_quotes?: number;
      invalid_quotes?: number;
      fetch_errors?: number;
      expiries_evaluated?: number;
    };
    feed_graph?: {
      complete?: boolean;
      missing_required_feeds?: string[];
    };
  };
  analysis?: {
    market?: {
      spot_usd?: number | null;
      dvol_percent?: number | null;
      near_term_atm_iv_percent?: number | null;
      dvol_minus_atm_iv_points?: number | null;
      funding_rate?: number | null;
      basis_rate?: number | null;
      event_score?: number | null;
      regime_label?: string;
      regime_status?: string;
      sell_permission?: number | null;
      spread_permission?: boolean;
      naked_permission?: boolean;
    };
    volatility?: {
      surface_status?: string;
      term_slope_iv_points?: number | null;
      candidate_expiry_atm_iv_percent?: number | null;
      expected_move_usd?: number | null;
      expected_move_percent?: number | null;
      call_wing_richness_iv_points?: number | null;
      front_expiry?: {
        expiry_date?: string;
        dte_days?: number | null;
        atm_fitted_iv_percent?: number | null;
        fit_quality_score?: number | null;
        no_arbitrage_pass?: boolean;
        candidate_eligible?: boolean;
      } | null;
      next_expiry?: {
        expiry_date?: string;
        dte_days?: number | null;
        atm_fitted_iv_percent?: number | null;
        fit_quality_score?: number | null;
        no_arbitrage_pass?: boolean;
        candidate_eligible?: boolean;
      } | null;
    };
    interpretation_limits?: string[];
  };
  strategy_selection?: {
    selection_method?: string;
    eligible_spread_count?: number;
    ranked_candidate_ids?: string[];
    ranking_dimensions?: string[];
  };
  playbook?: {
    playbook_id?: string;
    structure?: "CALL_CREDIT_SPREAD";
    candidate?: {
      candidate_id?: string;
      expiry_date?: string;
      dte_days?: number | null;
      sell_leg?: string;
      buy_leg?: string;
      sell_strike_usd?: number | null;
      buy_strike_usd?: number | null;
      model_delta?: number | null;
      risk_neutral_p_itm?: number | null;
      surface_fit_quality?: number | null;
    };
    economics?: {
      premium_currency?: string;
      credit_coin?: number | null;
      credit_usd_shadow?: number | null;
      spread_width_usd?: number | null;
      reference_max_loss_usd_shadow?: number | null;
      estimated_total_fees_usd_shadow?: number | null;
      breakeven_usd_shadow?: number | null;
      sell_strike_distance_usd?: number | null;
      sell_strike_distance_percent?: number | null;
      sell_strike_expected_move_multiple?: number | null;
      credit_to_max_loss_ratio?: number | null;
      assumption?: string;
    };
    entry_contract?: {
      status?: "ready" | "blocked";
      revalidate_on_refresh?: boolean;
      price_basis?: string;
      execution_assumption?: string;
      conditions?: StrategyCondition[];
    };
    risk_budget?: {
      max_single_spread_loss_nav?: number;
      max_single_naked_stress_loss_nav?: number;
      max_new_margin_nav?: number;
      max_net_delta_nav?: number;
      max_depth_fraction?: number;
      inverse_position_size_multiplier?: number;
      sizing_status?: string;
      contracts?: number | null;
      formula?: string;
      portfolio_final_action?: string;
      note?: string;
    };
    exit_contract?: {
      policy_status?: string;
      profit_capture?: Array<{
        trigger?: string;
        response?: string;
        validated?: boolean;
      }>;
      position_states?: Array<{
        state?: string;
        delta_condition?: string;
        loss_condition?: string;
        response?: string;
      }>;
      time_management?: {
        review_below_dte_days?: number;
        roll_allowed_states?: string[];
        roll_delta_band?: number[];
        roll_must_improve?: string[];
        defensive_roll_minimum_stress_reduction?: number;
        loss_deferral_alone_is_forbidden?: boolean;
      };
      kill_switches?: string[];
    };
  } | null;
  monitoring?: Array<{
    metric?: string;
    current?: unknown;
    trigger?: string;
    response?: string;
    cadence?: string;
  }>;
  review?: {
    status?: string;
    backtest_status?: string;
    calibration_status?: string;
    path_risk_status?: string;
    missing_evidence?: string[];
    promotion_conditions?: string[];
    journal_template?: string[];
  };
  degradation?: Array<{
    condition?: string;
    effect?: string;
  }>;
}

export interface ReleasePrerequisite {
  name: string;
  satisfied?: boolean;
  owner?: string;
  action?: string;
  next_action?: string;
  reason_code?: string;
  reason_codes?: string[];
}

export interface ResearchReport {
  schema_version: "research_report.v1";
  generated_at?: string | null;
  action?: string;
  mode?: string;
  effective_mode?: string;
  risk_state?: string;
  reason_codes?: string[];
  blocked_outputs?: string[];
  data_trust?: {
    verdict?: string;
    source_class?: string;
    reason_codes?: string[];
  };
  data_status?: EvidenceDataStatus;
  account_status?: {
    status?: string;
    source?: string;
    margin_light?: string;
    trade_gate?: string;
    reason_code?: string | null;
    freshness_limit_ms?: number;
    data_age_ms?: number | null;
  };
  mode_gate?: {
    trade_recommendation_allowed?: boolean;
    recommended_size_allowed?: boolean;
    order_instructions_allowed?: boolean;
    paper_manual_candidates_allowed?: boolean;
    reason_codes?: string[];
  };
  calibration_status?: {
    status?: string;
    model_version?: string | null;
    reason_code?: string | null;
  };
  backtest_status?: {
    status?: string;
    reason_code?: string | null;
  };
  vol_surface_status?: {
    status?: string;
    validated?: boolean;
    reason_code?: string | null;
    fit_model?: string;
    summary?: {
      eligible_expiries?: number;
      expiries_evaluated?: number;
      quality_passing_quotes?: number;
    };
    expiries?: SurfaceExpiry[];
  };
  candidate_research?: CandidateResearch;
  strategy_research?: StrategyResearch;
  portfolio_risk?: {
    final_action?: string;
    final_signal?: {
      reason?: string;
      reason_codes?: string[];
    };
  };
  full_system_surface?: {
    release_readiness?: {
      status?: string;
      prerequisites?: ReleasePrerequisite[];
    };
  };
}
