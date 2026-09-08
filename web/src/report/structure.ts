import type { ResearchReport } from "../contracts";

/** Input values never appear in diagnostics; transport can report the category. */
export class ResearchReportStructureError extends Error {
  readonly kind = "structure";
  constructor(readonly field: string) {
    super(`Invalid research report structure at ${field}`);
    this.name = "ResearchReportStructureError";
  }
}

type Check = (value: unknown, field: string) => void;
type Fields = Record<string, Check>;
function reject(field: string): never { throw new ResearchReportStructureError(field); }
const text: Check = (value, field) => { if (typeof value !== "string") reject(field); };
const number: Check = (value, field) => { if (typeof value !== "number" || !Number.isFinite(value)) reject(field); };
const flag: Check = (value, field) => { if (typeof value !== "boolean") reject(field); };
const nullable = (check: Check): Check => (value, field) => { if (value !== null) check(value, field); };
const member = (...values: string[]): Check => (value, field) => {
  if (typeof value !== "string" || !values.includes(value)) reject(field);
};
const list = (check: Check): Check => (value, field) => {
  if (!Array.isArray(value)) reject(field);
  for (let index = 0; index < value.length; index += 1) check(value[index], `${field}[${index}]`);
};
const record: Check = (value, field) => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) reject(field);
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) reject(field);
};
const object = (fields: Fields, required: readonly string[] = []): Check => (value, field) => {
  record(value, field);
  const data = value as Record<string, unknown>;
  for (const key of required) if (data[key] === undefined) reject(`${field}.${key}`);
  for (const [key, check] of Object.entries(fields)) {
    if (data[key] !== undefined) check(data[key], `${field}.${key}`);
  }
};
const dictionary = (check: Check): Check => (value, field) => {
  record(value, field);
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) check(item, `${field}.${key}`);
};
const group = (keys: string, check: Check): Fields => Object.fromEntries(keys.split(" ").map((key) => [key, check]));
const strings = list(text);
const nullableNumber = nullable(number);
const nullableText = nullable(text);

function calendarDate(value: string): boolean {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1];
}
const day: Check = (value, field) => {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !calendarDate(value)) reject(field);
};
const timestamp: Check = (value, field) => {
  if (typeof value !== "string") reject(field);
  const parts = /^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  if (!parts || !calendarDate(value) || Number(parts[1]) > 23 || Number(parts[2]) > 59 ||
      Number(parts[3]) > 59 || Number(parts[5] ?? 0) > 23 || Number(parts[6] ?? 0) > 59 ||
      !Number.isFinite(Date.parse(value))) reject(field);
};

// Values outside the fields the UI consumes remain forward-compatible JSON,
// but may not smuggle non-finite numbers or non-JSON objects through the boundary.
function jsonValue(value: unknown, field: string, ancestors = new Set<object>()): void {
  if (value === undefined || value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number") return number(value, field);
  if (typeof value !== "object" || ancestors.has(value) || ancestors.size >= 64) reject(field);
  ancestors.add(value);
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      if (value[index] === undefined) reject(`${field}[${index}]`);
      jsonValue(value[index], `${field}[${index}]`, ancestors);
    }
  }
  else {
    record(value, field);
    for (const [key, item] of Object.entries(value)) jsonValue(item, `${field}.${key}`, ancestors);
  }
  ancestors.delete(value);
}

const sourceStatus = { status: text, source: text, reason_code: nullableText };
const surfaceQuality = object({
  ...group("fit_quality_score no_arb_error", nullableNumber), no_arb_pass: flag,
});
const greekValues = object(group("delta gamma theta vega", nullableNumber));
const positionGreeks = object({
  ...group("delta gamma theta vega", nullableNumber), status: text, reason_code: nullableText, missing: strings,
});
const structureLeg = object({
  option_type: member("call", "put"),
  ...group("strike quantity surface_fitted_iv market_mark_iv", number),
  instrument_name: text, expiry_date: day,
}, ["option_type", "strike", "quantity"]);
const candidate = object({
  ...group("candidate_id decision instrument_name premium_currency premium_unit structure_type sell_leg_instrument_name buy_leg_instrument_name", nullableText),
  ...group("dte_days market_mark_iv market_mid model_delta surface_fitted_iv underlying_price buy_leg_strike_price sell_leg_strike_price net_credit spread_width", nullableNumber),
  expiry_date: nullable(day), surface_quality: nullable(surfaceQuality), structure_legs: nullable(list(structureLeg)),
  reason_codes: strings, position_greeks: nullable(positionGreeks),
});
const candidateBuckets = object({ eligible: list(candidate), rejected: list(candidate), review: list(candidate) });
const expiry = object({
  ...group("candidate_eligible fit_quality_pass no_arb_pass", flag),
  ...group("dte_days fit_quality_score no_arb_error quality_passing_quotes", nullableNumber),
  expiry_date: day, reason_codes: strings,
  surface_points: list(object({
    instrument_name: text,
    ...group("strike_price market_mark_iv surface_fitted_iv underlying_price", nullableNumber),
  })),
});
const qualityCounts = object(group("expiries_evaluated fetch_errors invalid_quotes total_quotes valid_quotes quality_passing_quotes", number));
const dataStatus = object({
  ...sourceStatus, validated: flag, market_data_age_sec: nullableNumber,
  feed_coverage: object({ feeds: dictionary(nullable(object(group("freshness_status reason_code scope source_endpoint status", nullableText)))) }),
  collection_scope: object({ ...group("selected_instrument_count upstream_instrument_count coverage_ratio", nullableNumber), scope: nullableText }),
  public_response_contract: object({ endpoints: object({ vol_index: object({
    ...group("status index_name", text), ...group("volatility age_sec max_age_sec", nullableNumber),
  }) }) }),
  quality_gate: object({
    passed: nullable(flag), reason_codes: strings, advisory_reason_codes: strings,
    summary: object({ ...group("expiries_evaluated fetch_errors invalid_quotes total_quotes valid_quotes", nullableNumber), market_data_age_sec: nullableNumber }),
    thresholds: object({ market_data_max_age_sec: nullableNumber }),
  }),
});
const strategyExpiry = nullable(object({
  expiry_date: nullable(day),
  ...group("dte_days atm_fitted_iv_percent fit_quality_score", nullableNumber),
  ...group("no_arbitrage_pass candidate_eligible", nullable(flag)),
}));
const condition = object({
  ...group("id label", text), ...group("requirement reason", nullableText), status: member("pass", "block", "unknown"), blocking: flag,
}, ["id", "label", "status"]);
const strategy = object({
  schema_version: text, generated_at: timestamp, status: member("partial", "blocked"),
  advisory_only: flag, execution_allowed: flag, confidence_ceiling: member("screening_only", "insufficient_data"),
  pipeline: list(object({
    stage: member("COLLECT", "ANALYZE", "SELECT", "ENTER", "RISK", "EXIT", "MONITOR", "REVIEW"),
    status: member("ready", "partial", "blocked"), output: text,
  }, ["stage", "status"])),
  decision: object({
    stance: member("NO_RESEARCH_SETUP", "MONITOR_ONLY", "CONDITIONAL_RESEARCH"),
    primary_structure: nullable(member("CALL_CREDIT_SPREAD")), entry_readiness: member("BLOCKED", "CONDITIONAL"),
    summary: text, why_now: strings, why_not: strings,
    rejected_structures: list(object({ structure: text, status: text, reason_codes: strings })),
  }),
  collection: object({
    ...sourceStatus, captured_at: nullable(timestamp), market_data_age_sec: nullableNumber,
    coverage: object({ ...group("scope", nullableText), ...group("selected_instrument_count upstream_instrument_count", number), coverage_ratio: nullableNumber, is_research_sample: flag }),
    quality: qualityCounts, feed_graph: object({ complete: flag, missing_required_feeds: strings }),
  }),
  analysis: object({
    market: object({
      ...group("spot_usd dvol_percent near_term_atm_iv_percent dvol_minus_atm_iv_points funding_rate basis_rate event_score sell_permission", nullableNumber),
      ...group("regime_label regime_status", text), ...group("spread_permission naked_permission", flag),
    }),
    volatility: object({
      ...group("surface_status fit_model", text),
      ...group("term_slope_iv_points candidate_expiry_atm_iv_percent expected_move_usd expected_move_percent call_wing_richness_iv_points", nullableNumber),
      front_expiry: strategyExpiry, next_expiry: strategyExpiry,
    }),
    interpretation_limits: strings,
  }),
  strategy_selection: object({ selection_method: text, eligible_spread_count: number, ranked_candidate_ids: strings, ranking_dimensions: strings }),
  playbook: nullable(object({
    playbook_id: text, structure: member("CALL_CREDIT_SPREAD"),
    candidate: object({
      ...group("candidate_id sell_leg buy_leg", text), expiry_date: day,
      ...group("dte_days sell_strike_usd buy_strike_usd model_delta risk_neutral_p_itm surface_fit_quality", nullableNumber),
    }),
    economics: object({
      ...group("premium_currency assumption", text),
      ...group("credit_coin credit_usd_shadow spread_width_usd reference_max_loss_usd_shadow estimated_total_fees_usd_shadow breakeven_usd_shadow sell_strike_distance_usd sell_strike_distance_percent sell_strike_expected_move_multiple credit_to_max_loss_ratio", nullableNumber),
    }),
    entry_contract: object({
      status: member("ready", "blocked"), revalidate_on_refresh: flag,
      ...group("price_basis execution_assumption", text), conditions: list(condition),
    }),
    risk_budget: object({
      ...group("max_single_spread_loss_nav max_single_naked_stress_loss_nav max_new_margin_nav max_net_delta_nav max_depth_fraction inverse_position_size_multiplier", number),
      ...group("sizing_status formula portfolio_final_action note", text), contracts: nullableNumber,
    }),
    exit_contract: object({
      policy_status: text,
      profit_capture: list(object({ trigger: text, response: text, validated: flag })),
      position_states: list(object(group("state delta_condition loss_condition response", text))),
      time_management: object({
        ...group("review_below_dte_days defensive_roll_minimum_stress_reduction", nullableNumber),
        roll_allowed_states: strings, roll_delta_band: list(number), roll_must_improve: strings, loss_deferral_alone_is_forbidden: nullable(flag),
      }),
      kill_switches: strings,
    }),
  })),
  monitoring: list(object(group("metric trigger response cadence", text))),
  review: object({
    ...group("status backtest_status calibration_status path_risk_status", text),
    missing_evidence: strings, promotion_conditions: strings, journal_template: strings,
  }),
  degradation: list(object(group("condition effect", text))),
}, ["schema_version"]);

const pathRisk = object({
  ...group("status sample_size_basis", nullableText),
  ...group("p_touch p_itm cvar_95_usdc cvar_99_usdc authoritative_sample_size", nullableNumber),
});
const rankedCandidate = object({
  candidate_id: text, action: member("RESEARCH_ONLY", "REVIEW", "REJECT"),
  ...group("structure_type score_status dominated_by premium_unit", nullableText),
  ...group("ranking_score premium_usdc executable_credit_usdc fair_value_usdc ev_after_cost_usdc dte_days model_delta net_credit market_bid underlying_price", nullableNumber),
  expiry_date: nullable(day), structure_legs: nullable(list(structureLeg)),
  position_greeks: nullable(positionGreeks),
  fair_iv_diagnostics: nullable(object({
    ...group("market_mark_iv surface_fitted_iv residual_iv_points", nullableNumber), ...group("residual_status measure", nullableText),
  })),
  path_risk: nullable(pathRisk),
  margin_snapshot: nullable(object({ status: text, basis: nullableText, reference_margin_usdc: nullableNumber, account_specific: flag })),
  hazard_zone: nullable(object({ ...group("breakeven_cushion_expected_moves risk_neutral_p_itm", nullableNumber), physical_probability_available: flag })),
  kill_conditions: strings, reason_codes: strings, losing_axes: strings,
  edge_components: nullable(dictionary(object({
    value: nullableNumber, ...group("unit reason_code direction", nullableText), status: member("OK", "CAUTION", "UNKNOWN", "BLOCKED"),
  }, ["status"]))),
  absolute_ev: nullable(object({
    ...group("status sample_size_basis evidence_class", nullableText),
    ...group("ev_after_cost_usdc entry_credit_usdc expected_payout_usdc p_touch p_itm cvar_95_usdc cvar_99_usdc authoritative_sample_size", nullableNumber),
    modelled_fees_usdc: nullable(object({ basis: nullableText, ...group("entry_fee_usdc expected_delivery_fee_usdc total_usdc", nullableNumber) })),
    nav_relative_metrics_available: flag, regime_similarity_applied: flag,
  })),
}, ["candidate_id", "action"]);
const scanner = object({
  status: member("unavailable", "blocked", "validated"), score_status: text, reason_code: nullableText,
  ranking_basis: object({ method: nullableText, tie_break_order: strings, dominance_scope: nullableText, absolute_ev_available: nullable(flag) }),
  dominated_explanations: list(object({ candidate_id: text, structure_type: nullableText, dominated_by: nullableText, losing_axes: strings }, ["candidate_id"])),
  ranked_candidates: list(rankedCandidate),
  path_risk_evidence: object({ ...sourceStatus, source: nullableText, artifact_id: nullableText, validated: flag }),
}, ["status"]);
const releaseGate = object({
  name: text, status: text, ...group("satisfied configurable execution_allowed", flag),
  ...group("evidence_class evidence_state reason_code", nullableText), reason_codes: strings,
}, ["name"]);
const combination = object({
  status: text, reason_code: nullableText, cannot_tell: strings,
  members: list(object({
    ...group("candidate_id structure_type", text), expiry_date: day,
    ...group("credit_usdc max_loss_usdc", nullableNumber), loss_is_bounded: flag,
  })),
  book: nullable(object({
    ...group("reason_code max_loss_upper_bound_basis", nullableText),
    ...group("total_credit_usdc max_loss_upper_bound_usdc", nullableNumber),
    expiries: list(day), unbounded_members: strings, loss_is_bounded: flag,
    joint_terminal_risk: object({ status: text, reason_code: nullableText, note: text, max_loss_usdc: nullableNumber }),
    greeks: object({
      status: text, reason_code: nullableText, missing: strings, net_assumes: text,
      net: nullable(greekValues), by_expiry: dictionary(greekValues),
    }),
  })),
  marginal_contributions: list(object({
    candidate_id: text, status: text, reason_code: nullableText,
    ...group("standalone_max_loss_usdc marginal_max_loss_usdc", nullableNumber),
  })),
});

const report = object({
  schema_version: member("research_report.v1"), generated_at: nullable(timestamp),
  ...group("action mode effective_mode risk_state", text), reason_codes: strings, blocked_outputs: strings,
  data_status: dataStatus,
  data_trust: object({ verdict: text, source_class: text, reason_codes: strings }),
  event_status: object({
    ...group("source source_status scope reason_code", nullableText), macro_calendar_covered: flag, event_score: nullableNumber,
    exchange_lock_state: member("unknown", "normal", "partial", "full"),
  }),
  account_status: object({ ...sourceStatus, margin_light: text, trade_gate: text, freshness_limit_ms: number, data_age_ms: nullableNumber }),
  mode_gate: object({ ...group("trade_recommendation_allowed recommended_size_allowed order_instructions_allowed paper_manual_candidates_allowed", flag), reason_codes: strings }),
  calibration_status: object({ status: text, model_version: nullableText, reason_code: nullableText }),
  backtest_status: object({ status: text, reason_code: nullableText, artifact_id: nullableText }),
  vol_surface_status: object({
    status: text, validated: flag, reason_code: nullableText, fit_model: text,
    summary: object(group("eligible_expiries expiries_evaluated quality_passing_quotes", number)), expiries: list(expiry),
  }),
  candidate_research: object({
    status: text, reason_code: nullableText,
    summary: object({
      ...group("eligible_call_credit_spreads eligible_expiries eligible_naked_short_calls expiries_considered rejected_call_credit_spreads rejected_naked_short_calls review_call_credit_spreads review_naked_short_calls eligible_put_credit_spreads eligible_iron_condors rejected_put_credit_spreads rejected_iron_condors review_put_credit_spreads review_iron_condors iron_condor_limit iron_condors_truncated", number),
      rejected_expiries: list(object({ expiry_date: day, reason_codes: strings })),
    }),
    ...group("naked_short_calls call_credit_spreads put_credit_spreads iron_condors", candidateBuckets),
  }),
  strategy_research: strategy, ev_candidate_scanner: nullable(scanner), combination_risk: nullable(combination),
  portfolio_risk: object({ final_action: text, final_signal: object({ reason: text, reason_codes: strings }) }),
  full_system_surface: object({
    release_readiness: object({ status: text, prerequisites: list(object({
      ...group("name owner action next_action reason_code", text), satisfied: flag, reason_codes: strings,
    }, ["name"])) }),
    release_gates: list(releaseGate),
  }),
  runtime_context: object({
    profile: nullableText, mode: nullable(member("live", "replay", "published")), ...group("replay demo_mode live_fetch_allowed", nullable(flag)),
    evaluation_clock: nullable(timestamp), snapshot_fixture: nullableText, notice: nullableText,
  }),
  publish_edition: object({ ...group("captured_at published_at next_expected_at stale_after", nullable(timestamp)), cadence: nullable(member("daily")) }),
  vrp_status: object({
    ...group("schema_version status band evidence_class reason_code action", nullableText),
    ...group("current_vrp_percent_points current_dvol_percent current_rv30_percent percentile sample_count minimum_series_sample_count window_days", nullableNumber),
    missing_dates: list(day), series: list(object({
      observed_at: nullable(timestamp), ...group("vrp_percent_points dvol_percent rv30_percent percentile", nullableNumber),
      ...group("band evidence_class", nullableText),
    })),
  }),
}, ["schema_version"]);

/** Validate the declared consumer fields; optional missing/degraded evidence stays optional. */
export function validateReportStructure(payload: unknown): asserts payload is ResearchReport {
  jsonValue(payload, "report");
  report(payload, "report");
}
