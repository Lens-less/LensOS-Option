// This schema covers fields consumed by the public UI. Keep it independent of
// the internal report validator so private field names stay out of the bundle.
type Check = (value: unknown) => boolean;
type Fields = Record<string, Check>;
const text: Check = (value) => typeof value === "string";
const numeric: Check = (value) => typeof value === "number" && Number.isFinite(value);
const count: Check = (value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const fraction: Check = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
const flag: Check = (value) => typeof value === "boolean";
const nullable = (check: Check): Check => (value) => value === null || check(value);
const list = (check: Check): Check => (value) => Array.isArray(value) && value.every(check);
const member = (...values: string[]): Check => (value) => typeof value === "string" && values.includes(value);
const group = (keys: string, check: Check): Fields => Object.fromEntries(keys.split(" ").map((key) => [key, check]));
const strings = list(text);
const nText = nullable(text);
const nNumber = nullable(numeric);
const nCount = nullable(count);
const nFlag = nullable(flag);

function record(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

const object = (fields: Fields, required: string[] = []): Check => (value) =>
  record(value) && required.every((key) => value[key] !== undefined) &&
  Object.entries(fields).every(([key, check]) => value[key] === undefined || check(value[key]));

function calendarDate(value: string): boolean {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1];
}

const day: Check = (value) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && calendarDate(value);
const timestamp: Check = (value) => {
  if (typeof value !== "string") return false;
  const parts = /^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  return Boolean(parts && calendarDate(value) && Number(parts[1]) <= 23 && Number(parts[2]) <= 59 &&
    Number(parts[3]) <= 59 && Number(parts[5] ?? 0) <= 23 && Number(parts[6] ?? 0) <= 59 && Number.isFinite(Date.parse(value)));
};

// JSON permits exponents which overflow JS numbers. Reject those everywhere,
// including forward-compatible fields, before any data reaches rendering.
function jsonValue(value: unknown, ancestors = new Set<object>()): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return numeric(value);
  if (typeof value !== "object" || ancestors.has(value) || ancestors.size >= 64) return false;
  if (!Array.isArray(value) && !record(value)) return false;
  ancestors.add(value);
  const valid = Object.values(value).every((item) => jsonValue(item, ancestors));
  ancestors.delete(value);
  return valid;
}

const surfaceQuality = object({ ...group("fit_quality_score no_arb_error", nNumber), no_arb_pass: nFlag });
const candidate = object({
  ...group("candidate_id instrument_name sell_leg_instrument_name buy_leg_instrument_name", nText),
  ...group("model_delta net_credit market_mid", nNumber), expiry_date: nullable(day),
  surface_quality: nullable(surfaceQuality), reason_codes: strings,
});
const bucket = object({ eligible: list(candidate), review: list(candidate), rejected: list(candidate) });
const source = member("deribit_published_snapshot");
const condition = object({
  ...group("id label", text), status: member("pass", "block", "unknown"), blocking: flag,
}, ["status"]);
const strategy = object({
  ...group("schema_version status confidence_ceiling", nText), generated_at: nullable(timestamp),
  advisory_only: flag, execution_allowed: flag,
  decision: object(group("primary_structure stance entry_readiness summary", nText)),
  collection: object({ source }, ["source"]),
  analysis: object({ market: object({ spot_usd: nNumber }) }),
  playbook: nullable(object({
    ...group("playbook_id structure", nText),
    candidate: object({
      ...group("candidate_id sell_leg buy_leg", nText), expiry_date: nullable(day),
      ...group("sell_strike_usd buy_strike_usd model_delta dte_days surface_fit_quality", nNumber),
      risk_neutral_p_itm: nullable(fraction),
    }),
    economics: object(group("credit_coin credit_usd_shadow reference_max_loss_usd_shadow breakeven_usd_shadow", nNumber)),
    entry_contract: object({ status: member("ready", "blocked"), conditions: list(condition) }),
    risk_budget: object({ contracts: nNumber }),
  })),
});

const publicReport = object({
  schema_version: member("research_report.v1"), generated_at: nullable(timestamp),
  ...group("action mode effective_mode risk_state", text), reason_codes: strings, blocked_outputs: strings,
  data_status: object({
    source, ...group("status reason_code", nText), validated: nFlag, market_data_age_sec: nNumber,
    collection_scope: object({
      ...group("selected_instrument_count upstream_instrument_count", nCount), coverage_ratio: nullable(fraction), scope: nText,
    }),
    public_response_contract: object({ endpoints: object({ vol_index: object({
      ...group("status index_name", nText), ...group("volatility age_sec max_age_sec", nNumber),
    }) }) }),
    quality_gate: object({
      passed: nFlag, reason_codes: strings, advisory_reason_codes: strings,
      summary: object({ ...group("expiries_evaluated fetch_errors invalid_quotes total_quotes valid_quotes", nCount), market_data_age_sec: nNumber }),
      thresholds: object({ market_data_max_age_sec: nNumber }),
    }),
  }, ["source"]),
  data_trust: object({ verdict: nText, source_class: member("published_snapshot"), reason_codes: strings }, ["source_class"]),
  event_status: object({
    ...group("source source_status scope reason_code", nText), macro_calendar_covered: flag, event_score: nNumber,
    exchange_lock_state: member("unknown", "normal", "partial", "full"),
  }),
  mode_gate: object(group("trade_recommendation_allowed recommended_size_allowed order_instructions_allowed paper_manual_candidates_allowed", flag)),
  vol_surface_status: object({
    ...group("status reason_code fit_model", nText), validated: nFlag,
    summary: object(group("eligible_expiries expiries_evaluated quality_passing_quotes", nCount)),
    expiries: list(object({
      ...group("candidate_eligible fit_quality_pass no_arb_pass", nFlag),
      ...group("dte_days fit_quality_score no_arb_error", nNumber), quality_passing_quotes: nCount,
      expiry_date: nullable(day), reason_codes: strings,
      surface_points: list(object({
        instrument_name: nText, ...group("strike_price market_mark_iv surface_fitted_iv underlying_price", nNumber),
      })),
    })),
  }),
  candidate_research: object({
    ...group("status reason_code", nText),
    summary: object(group("eligible_call_credit_spreads eligible_naked_short_calls eligible_expiries expiries_considered", count)),
    ...group("naked_short_calls call_credit_spreads", bucket),
  }),
  strategy_research: nullable(strategy),
  full_system_surface: object({
    release_readiness: object({ status: text }),
    release_gates: list(object({
      name: text, status: text, ...group("satisfied configurable execution_allowed", flag),
      ...group("evidence_class evidence_state reason_code", nText), reason_codes: strings,
    }, ["name"])),
  }),
  runtime_context: object({
    mode: text, replay: flag, ...group("demo_mode live_fetch_allowed", nFlag), evaluation_clock: timestamp,
  }),
  publish_edition: object({ ...group("captured_at published_at next_expected_at stale_after", timestamp), cadence: text }),
  vrp_status: object({
    ...group("schema_version status band evidence_class reason_code action", nText),
    ...group("current_vrp_percent_points current_dvol_percent current_rv30_percent", nNumber),
    ...group("sample_count minimum_series_sample_count window_days", nCount), percentile: nullable(fraction),
    missing_dates: list(day), series: list(object({
      observed_at: nullable(timestamp), ...group("vrp_percent_points dvol_percent rv30_percent", nNumber),
      percentile: nullable(fraction), ...group("band evidence_class", nText),
    })),
  }),
}, ["schema_version", "data_status", "data_trust"]);

const publicSummary = object({
  schema_version: member("public_summary.v1"),
  ...group("captured_at published_at", nullable(timestamp)),
  change: object({
    status: text, band_changed: nFlag,
    ...group("current_observed_at prior_observed_at", nullable(timestamp)),
    ...group("percentile_delta vrp_percent_points_delta", nNumber),
  }),
  vrp: object({ band: nText, percentile: nullable(fraction), vrp_percent_points: nNumber }),
}, ["schema_version"]);

export function validatePublicReportStructure(value: unknown): void {
  if (!jsonValue(value) || !publicReport(value)) throw new Error("Invalid public report structure");
}

export function isPublicSummary(value: unknown): boolean {
  return jsonValue(value) && publicSummary(value);
}
