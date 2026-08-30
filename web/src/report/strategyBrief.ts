export const STRATEGY_BRIEF_SCHEMA = "strategy_brief.v1";

export type StrategyBriefAction =
  | "STRATEGIES_AVAILABLE"
  | "WATCH"
  | "NO_TRADE";
export type StrategyRecommendationStatus = "RECOMMENDED" | "WATCH";
export type StrategyStructureType =
  | "BULL_PUT_CREDIT_SPREAD"
  | "BEAR_CALL_CREDIT_SPREAD"
  | "IRON_CONDOR";
export type MarketDirection = "BULLISH" | "RANGE" | "BEARISH" | "UNCLEAR";
export type MarketVolatility = "CHEAP" | "FAIR" | "RICH" | "UNKNOWN";
export type MarketLiquidity = "EXECUTABLE" | "LIMITED" | "UNAVAILABLE";
export type MarketConfidence = "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE";
export type StrategyLegSide = "BUY" | "SELL";
export type StrategyOptionType = "call" | "put";
export type PriceBasis = "SHORT_BID_LONG_ASK";
export type HistoryStatus =
  | "INSUFFICIENT"
  | "EXPLORATORY"
  | "VALIDATED"
  | "FAILED";
export type ForecastStatus =
  | "UNAVAILABLE"
  | "SCREENING_ONLY"
  | "CALIBRATED"
  | "RETIRED";
export type PathRiskStatus =
  | "VALIDATED"
  | "INSUFFICIENT"
  | "UNAVAILABLE"
  | "FAILED";
export type FreshnessStatus = "CURRENT" | "STALE" | "UNAVAILABLE";
export type SourceKind =
  | "live"
  | "replay"
  | "published"
  | "demo"
  | "fallback";
export type PresentedAs = "live" | "replay" | "published";

export interface StrategyBriefMarket {
  underlying: string;
  as_of: string;
  expires_at: string;
  direction: MarketDirection;
  volatility: MarketVolatility;
  liquidity: MarketLiquidity;
  confidence: MarketConfidence;
  action: StrategyBriefAction;
  summary_zh: string;
}

export interface StrategyBriefLeg {
  instrument_name: string;
  side: StrategyLegSide;
  quantity: number;
  observed_at: string;
  bid: number;
  ask: number;
  premium_unit: string;
  expiry_date?: string;
  option_type?: StrategyOptionType;
  premium_currency?: string;
  strike?: number;
}

export interface StrategyBriefEntry {
  price_basis: PriceBasis;
  minimum_net_credit: number;
  currency: string;
  fees_included: boolean;
  slippage_included: boolean;
}

export interface StrategyBriefRisk {
  max_loss_per_unit: number;
  currency: string;
  breakevens: number[];
  path_risk_status: PathRiskStatus;
  cvar_95: number;
}

export interface StrategyBriefEconomics {
  relative_value_status: string;
  absolute_ev_status: string;
  ev_after_cost: number;
  net_r: number;
}

export interface StrategyEvidenceScope {
  underlying: string;
  structure_type: StrategyStructureType;
  direction: Exclude<MarketDirection, "UNCLEAR">;
  dte_band_days: [number, number];
  entry_cost_basis: PriceBasis;
  exit_basis: string;
  expiry_date?: string;
  dte_days?: number;
}

export interface StrategyBriefHistory {
  status: HistoryStatus;
  win_rate: number | null;
  mean_net_r: number | null;
  independent_cohorts: number | null;
  observation_count: number | null;
  exit_basis: string | null;
  artifact_id: string | null;
  scope: StrategyEvidenceScope | null;
}

export interface StrategyBriefForecast {
  status: ForecastStatus;
  win_rate_low: number | null;
  win_rate_high: number | null;
  confidence: MarketConfidence | null;
  scope: StrategyEvidenceScope | null;
  artifact_id: string | null;
}

export interface StrategyBriefStrategy {
  recommendation_id: string;
  rank: number;
  recommendation_status: StrategyRecommendationStatus;
  structure_type: StrategyStructureType;
  thesis_zh: string;
  as_of: string;
  valid_until: string;
  expiry_date?: string;
  dte_days?: number;
  legs: StrategyBriefLeg[];
  entry: StrategyBriefEntry;
  risk: StrategyBriefRisk;
  economics: StrategyBriefEconomics;
  history: StrategyBriefHistory;
  forecast: StrategyBriefForecast;
  kill_conditions: string[];
  primary_reason_codes: string[];
  copy_recipe: string;
}

export interface StrategyBriefNoTrade {
  active: boolean;
  headline_zh: string | null;
  summary_zh: string | null;
  primary_reason_codes: string[];
  reasons_zh?: string[];
  next_update_at: string | null;
}

export interface StrategyBriefEvidenceSummary {
  candidate_count: number;
  hard_gate_pass_count: number;
  selected_count: number;
  recommended_count: number;
  watch_count: number;
  rejection_counts: Record<string, number>;
  default_structure_family: StrategyStructureType | null;
  summary_zh?: string;
  as_of?: string;
  valid_until?: string;
  primary_reason_codes?: string[];
  items?: Array<{
    label: string;
    status: "PASS" | "WARN" | "BLOCK" | "INFO";
    summary_zh: string;
    detail_zh: string;
    artifact_id: string | null;
  }>;
  surface?: StrategyBriefSurfaceState;
}

export interface StrategyBrief {
  schema_version: typeof STRATEGY_BRIEF_SCHEMA;
  brief_id: string;
  analysis_run_id: string;
  generated_at: string;
  research_only: true;
  execution_allowed: false;
  market: StrategyBriefMarket;
  action: StrategyBriefAction;
  strategies: StrategyBriefStrategy[];
  no_trade: StrategyBriefNoTrade;
  evidence_summary: StrategyBriefEvidenceSummary;
}

export interface StrategyBriefSurfaceState {
  freshness_status: FreshnessStatus;
  source_kind: SourceKind;
  presented_as: PresentedAs;
  source_label: string;
  now_ms?: number;
}

export interface StrategyBriefSuppression {
  suppress_cards: boolean;
  reasons_zh: string[];
}

export interface StrategyBriefSurfaceNoTrade extends StrategyBriefNoTrade {
  reasons_zh: string[];
}

export interface StrategyBriefSurfaceProjection {
  action: StrategyBriefAction;
  no_trade: StrategyBriefSurfaceNoTrade;
  strategies: StrategyBriefStrategy[];
  suppression: StrategyBriefSuppression;
}

const ACTIONS = new Set<StrategyBriefAction>([
  "STRATEGIES_AVAILABLE",
  "WATCH",
  "NO_TRADE",
]);
const STRATEGY_STATUSES = new Set<StrategyRecommendationStatus>([
  "RECOMMENDED",
  "WATCH",
]);
const STRUCTURES = new Set<StrategyStructureType>([
  "BULL_PUT_CREDIT_SPREAD",
  "BEAR_CALL_CREDIT_SPREAD",
  "IRON_CONDOR",
]);
const DIRECTIONS = new Set<MarketDirection>([
  "BULLISH",
  "RANGE",
  "BEARISH",
  "UNCLEAR",
]);
const VOLATILITY_STATES = new Set<MarketVolatility>([
  "CHEAP",
  "FAIR",
  "RICH",
  "UNKNOWN",
]);
const LIQUIDITY_STATES = new Set<MarketLiquidity>([
  "EXECUTABLE",
  "LIMITED",
  "UNAVAILABLE",
]);
const MARKET_CONFIDENCE = new Set<MarketConfidence>([
  "HIGH",
  "MEDIUM",
  "LOW",
  "UNAVAILABLE",
]);
const LEG_SIDES = new Set<StrategyLegSide>(["BUY", "SELL"]);
const OPTION_TYPES = new Set<StrategyOptionType>(["call", "put"]);
const FRESHNESS_STATES = new Set<FreshnessStatus>([
  "CURRENT",
  "STALE",
  "UNAVAILABLE",
]);
const SOURCE_KINDS = new Set<SourceKind>([
  "live",
  "replay",
  "published",
  "demo",
  "fallback",
]);
const PRESENTED_AS = new Set<PresentedAs>(["live", "replay", "published"]);
const HISTORY_STATUSES = new Set<HistoryStatus>([
  "INSUFFICIENT",
  "EXPLORATORY",
  "VALIDATED",
  "FAILED",
]);
const FORECAST_STATUSES = new Set<ForecastStatus>([
  "UNAVAILABLE",
  "SCREENING_ONLY",
  "CALIBRATED",
  "RETIRED",
]);
const PATH_RISK_STATUSES = new Set<PathRiskStatus>([
  "VALIDATED",
  "INSUFFICIENT",
  "UNAVAILABLE",
  "FAILED",
]);
const MAX_LEG_SKEW_MS = 2_000;
const REASON_TEXT_ZH: Record<string, string> = {
  NO_CAPTURABLE_EDGE_AT_TOUCH: "当前可成交价格下没有足够收益空间",
  OTHER_DIRECTION_IS_POSITIVE: "当前数据更支持反方向，不建议该卖方结构",
  NEGATIVE_EV_AFTER_COST: "扣除成本后期望收益为负",
  UNBOUNDED_LOSS_STRUCTURE: "亏损上限不明确，本版本不推荐",
  MISSING_VALIDATED_PATH_RISK: "风险历史证据不足，暂不推荐",
  STALE_MARKET_DATA: "行情已过期，等待刷新",
  LEGS_NOT_SYNCHRONIZED: "多腿报价不同步，无法确认组合价格",
  HISTORICAL_EVIDENCE_INSUFFICIENT: "历史样本不足，仅供观察",
  FORECAST_NOT_CALIBRATED: "预测胜率尚未完成校准",
  PROMOTION_EXPIRED: "预测证据已过期，等待重新验证",
  MISSING_POSITIVE_TWO_SIDED_QUOTES: "关键腿缺少正的双边报价",
  CROSSED_MARKET_QUOTES: "关键腿报价交叉，无法确认真实价格",
  UNIT_MISMATCH: "报价、结算或风险单位不一致",
  STRATEGY_EXPIRED: "策略已过期，等待下一次筛选",
  KILL_CONDITION_HIT: "触发取消条件，当前不再成立",
  NO_ELIGIBLE_STRATEGY: "当前没有通过全部硬门禁的有限风险策略",
  SURFACE_SOURCE_STALE_OR_UNAVAILABLE: "当前表面已过期或不可验证，策略卡被收起。",
  SURFACE_PROVENANCE_NOT_LIVE: "当前来源不是 live，不展示可执行感很强的策略卡。",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function requireRecord(value: unknown, field: string): Record<string, unknown> {
  if (!isRecord(value)) {
    fail(`${field} must be an object`);
  }
  return value;
}

function fail(message: string): never {
  throw new Error(message);
}

function parseTimestamp(value: string, field: string): number {
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) {
    fail(`${field} must include an explicit UTC offset`);
  }
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) {
    fail(`${field} must be a valid timestamp`);
  }
  return parsed;
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    fail(`${field} must be a non-empty string`);
  }
  return value;
}

function requireFiniteNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    fail(`${field} must be a finite number`);
  }
  return value;
}

function requirePositiveNumber(value: unknown, field: string): number {
  const number = requireFiniteNumber(value, field);
  if (number <= 0) {
    fail(`${field} must be positive`);
  }
  return number;
}

function requireArray<T>(value: unknown, field: string): T[] {
  if (!Array.isArray(value)) {
    fail(`${field} must be an array`);
  }
  return value as T[];
}

function requireMember<T extends string>(
  value: unknown,
  allowed: Set<T>,
  field: string,
): T {
  if (typeof value !== "string" || !allowed.has(value as T)) {
    fail(`${field} is invalid`);
  }
  return value as T;
}

function validateReasonCodes(value: unknown, field: string): string[] {
  return requireArray<unknown>(value, field).map((entry, index) =>
    requireString(entry, `${field}[${index}]`),
  );
}

function validateEvidenceScope(
  value: unknown,
  field: string,
): StrategyEvidenceScope {
  if (!isRecord(value)) {
    fail(`${field} must be an object`);
  }
  const dteBand = requireArray<unknown>(
    value.dte_band_days,
    `${field}.dte_band_days`,
  );
  if (dteBand.length !== 2) {
    fail(`${field}.dte_band_days must contain exactly two values`);
  }
  const dteMin = requirePositiveNumber(dteBand[0], `${field}.dte_band_days[0]`);
  const dteMax = requirePositiveNumber(dteBand[1], `${field}.dte_band_days[1]`);
  if (dteMax < dteMin) {
    fail(`${field}.dte_band_days must be ordered`);
  }
  const direction = requireMember(value.direction, DIRECTIONS, `${field}.direction`);
  if (direction === "UNCLEAR") {
    fail(`${field}.direction must be exact`);
  }
  const scope: StrategyEvidenceScope = {
    underlying: requireString(value.underlying, `${field}.underlying`),
    structure_type: requireMember(
      value.structure_type,
      STRUCTURES,
      `${field}.structure_type`,
    ),
    direction,
    dte_band_days: [dteMin, dteMax],
    entry_cost_basis: requireMember(
      value.entry_cost_basis,
      new Set<PriceBasis>(["SHORT_BID_LONG_ASK"]),
      `${field}.entry_cost_basis`,
    ),
    exit_basis: requireString(value.exit_basis, `${field}.exit_basis`),
  };
  if (value.expiry_date !== undefined) {
    scope.expiry_date = requireString(value.expiry_date, `${field}.expiry_date`);
  }
  if (value.dte_days !== undefined) {
    scope.dte_days = requirePositiveNumber(value.dte_days, `${field}.dte_days`);
  }
  return scope;
}

function validateSurfaceState(
  value: unknown,
  field: string,
): StrategyBriefSurfaceState {
  if (!isRecord(value)) {
    fail(`${field} must be an object`);
  }
  const result: StrategyBriefSurfaceState = {
    freshness_status: requireMember(
      value.freshness_status,
      FRESHNESS_STATES,
      `${field}.freshness_status`,
    ),
    source_kind: requireMember(value.source_kind, SOURCE_KINDS, `${field}.source_kind`),
    presented_as: requireMember(
      value.presented_as,
      PRESENTED_AS,
      `${field}.presented_as`,
    ),
    source_label: requireString(value.source_label, `${field}.source_label`),
  };
  if (value.now_ms !== undefined) {
    result.now_ms = requireFiniteNumber(value.now_ms, `${field}.now_ms`);
  }
  return result;
}

function validateMarket(market: unknown): StrategyBriefMarket {
  if (!isRecord(market)) {
    fail("market must be an object");
  }
  const asOf = parseTimestamp(requireString(market.as_of, "market.as_of"), "market.as_of");
  const expiresAt = parseTimestamp(
    requireString(market.expires_at, "market.expires_at"),
    "market.expires_at",
  );
  if (expiresAt < asOf) {
    fail("market.expires_at must be after or equal to market.as_of");
  }
  return {
    underlying: requireString(market.underlying, "market.underlying"),
    as_of: requireString(market.as_of, "market.as_of"),
    expires_at: requireString(market.expires_at, "market.expires_at"),
    direction: requireMember(market.direction, DIRECTIONS, "market.direction"),
    volatility: requireMember(
      market.volatility,
      VOLATILITY_STATES,
      "market.volatility",
    ),
    liquidity: requireMember(
      market.liquidity,
      LIQUIDITY_STATES,
      "market.liquidity",
    ),
    confidence: requireMember(
      market.confidence,
      MARKET_CONFIDENCE,
      "market.confidence",
    ),
    action: requireMember(market.action, ACTIONS, "market.action"),
    summary_zh: requireString(market.summary_zh, "market.summary_zh"),
  };
}

function validateLeg(leg: unknown, index: number): StrategyBriefLeg {
  if (!isRecord(leg)) {
    fail(`strategies[${index}].legs[] must be an object`);
  }
  const quantity = requirePositiveNumber(
    leg.quantity,
    `strategies[].legs[${index}].quantity`,
  );
  if (quantity !== 1) {
    fail(`strategies[].legs[${index}].quantity must remain exactly 1`);
  }
  const bid = requirePositiveNumber(leg.bid, `strategies[].legs[${index}].bid`);
  const ask = requirePositiveNumber(leg.ask, `strategies[].legs[${index}].ask`);
  if (ask < bid) {
    fail(`strategies[].legs[${index}] quotes must not be crossed`);
  }
  const result: StrategyBriefLeg = {
    instrument_name: requireString(
      leg.instrument_name,
      `strategies[].legs[${index}].instrument_name`,
    ),
    side: requireMember(leg.side, LEG_SIDES, `strategies[].legs[${index}].side`),
    quantity,
    observed_at: requireString(
      leg.observed_at,
      `strategies[].legs[${index}].observed_at`,
    ),
    bid,
    ask,
    premium_unit: requireString(
      leg.premium_unit,
      `strategies[].legs[${index}].premium_unit`,
    ),
  };
  if (leg.expiry_date !== undefined) {
    result.expiry_date = requireString(
      leg.expiry_date,
      `strategies[].legs[${index}].expiry_date`,
    );
  }
  if (leg.option_type !== undefined) {
    result.option_type = requireMember(
      leg.option_type,
      OPTION_TYPES,
      `strategies[].legs[${index}].option_type`,
    );
  }
  if (leg.premium_currency !== undefined) {
    result.premium_currency = requireString(
      leg.premium_currency,
      `strategies[].legs[${index}].premium_currency`,
    );
  }
  if (leg.strike !== undefined) {
    result.strike = requirePositiveNumber(
      leg.strike,
      `strategies[].legs[${index}].strike`,
    );
  }
  return result;
}

function deriveExactLegEconomics(
  structureType: StrategyStructureType,
  legs: StrategyBriefLeg[],
): { credit: number; expiryDate: string; maxLoss: number } | null {
  const optionalFields = legs.flatMap((leg) => [
    leg.expiry_date,
    leg.option_type,
    leg.premium_currency,
    leg.strike,
  ]);
  if (optionalFields.every((value) => value === undefined)) {
    return null;
  }
  if (optionalFields.some((value) => value === undefined)) {
    fail("exact strategy legs must provide expiry, option type, currency, and strike together");
  }
  const expiryDates = new Set(legs.map((leg) => leg.expiry_date));
  const premiumUnits = new Set(legs.map((leg) => leg.premium_unit));
  const premiumCurrencies = new Set(legs.map((leg) => leg.premium_currency));
  if (expiryDates.size !== 1 || premiumUnits.size !== 1 || premiumCurrencies.size !== 1) {
    fail("exact strategy legs must share expiry and unit semantics");
  }
  const credit =
    legs
      .filter((leg) => leg.side === "SELL")
      .reduce((sum, leg) => sum + leg.bid, 0) -
    legs
      .filter((leg) => leg.side === "BUY")
      .reduce((sum, leg) => sum + leg.ask, 0);
  if (!(credit > 0)) {
    fail("exact strategy executable credit must be positive");
  }
  let width: number;
  if (structureType === "BEAR_CALL_CREDIT_SPREAD") {
    const short = legs.find((leg) => leg.side === "SELL" && leg.option_type === "call");
    const long = legs.find((leg) => leg.side === "BUY" && leg.option_type === "call");
    if (!short || !long || legs.length !== 2 || long.strike! <= short.strike!) {
      fail("legs do not form a bear call credit spread");
    }
    width = long.strike! - short.strike!;
  } else if (structureType === "BULL_PUT_CREDIT_SPREAD") {
    const short = legs.find((leg) => leg.side === "SELL" && leg.option_type === "put");
    const long = legs.find((leg) => leg.side === "BUY" && leg.option_type === "put");
    if (!short || !long || legs.length !== 2 || short.strike! <= long.strike!) {
      fail("legs do not form a bull put credit spread");
    }
    width = short.strike! - long.strike!;
  } else {
    const shortPut = legs.find(
      (leg) => leg.side === "SELL" && leg.option_type === "put",
    );
    const longPut = legs.find(
      (leg) => leg.side === "BUY" && leg.option_type === "put",
    );
    const shortCall = legs.find(
      (leg) => leg.side === "SELL" && leg.option_type === "call",
    );
    const longCall = legs.find(
      (leg) => leg.side === "BUY" && leg.option_type === "call",
    );
    if (
      !shortPut ||
      !longPut ||
      !shortCall ||
      !longCall ||
      legs.length !== 4 ||
      shortPut.strike! <= longPut.strike! ||
      longCall.strike! <= shortCall.strike!
    ) {
      fail("legs do not form an iron condor");
    }
    width = Math.max(
      shortPut.strike! - longPut.strike!,
      longCall.strike! - shortCall.strike!,
    );
  }
  const maxLoss = width - credit;
  if (!(maxLoss > 0)) {
    fail("exact strategy max loss must be bounded and positive");
  }
  return {
    credit,
    expiryDate: legs[0].expiry_date!,
    maxLoss,
  };
}

function validateHistory(history: unknown): StrategyBriefHistory {
  if (!isRecord(history)) {
    fail("strategies[].history must be an object");
  }
  const status = requireMember(
    history.status,
    HISTORY_STATUSES,
    "strategies[].history.status",
  );
  const winRate =
    history.win_rate === null
      ? null
      : requireFiniteNumber(history.win_rate, "strategies[].history.win_rate");
  const meanNetR =
    history.mean_net_r === null
      ? null
      : requireFiniteNumber(
          history.mean_net_r,
          "strategies[].history.mean_net_r",
        );
  const scope =
    history.scope === null
      ? null
      : validateEvidenceScope(history.scope, "strategies[].history.scope");
  if (status !== "VALIDATED" && (winRate !== null || meanNetR !== null || scope !== null)) {
    fail("history metrics must be null unless history.status is VALIDATED");
  }
  if (
    status === "VALIDATED" &&
    (winRate === null ||
      winRate < 0 ||
      winRate > 1 ||
      meanNetR === null ||
      scope === null ||
      typeof history.artifact_id !== "string" ||
      history.artifact_id.trim() === "")
  ) {
    fail("validated history must provide win_rate and mean_net_r");
  }
  return {
    status,
    win_rate: winRate,
    mean_net_r: meanNetR,
    independent_cohorts:
      history.independent_cohorts === null
        ? null
        : requireFiniteNumber(
            history.independent_cohorts,
            "strategies[].history.independent_cohorts",
          ),
    observation_count:
      history.observation_count === null
        ? null
        : requireFiniteNumber(
            history.observation_count,
            "strategies[].history.observation_count",
          ),
    exit_basis:
      history.exit_basis === null
        ? null
        : requireString(history.exit_basis, "strategies[].history.exit_basis"),
    artifact_id:
      history.artifact_id === null
        ? null
        : requireString(history.artifact_id, "strategies[].history.artifact_id"),
    scope,
  };
}

function validateForecast(forecast: unknown): StrategyBriefForecast {
  if (!isRecord(forecast)) {
    fail("strategies[].forecast must be an object");
  }
  const status = requireMember(
    forecast.status,
    FORECAST_STATUSES,
    "strategies[].forecast.status",
  );
  const low =
    forecast.win_rate_low === null
      ? null
      : requireFiniteNumber(
          forecast.win_rate_low,
          "strategies[].forecast.win_rate_low",
        );
  const high =
    forecast.win_rate_high === null
      ? null
      : requireFiniteNumber(
          forecast.win_rate_high,
          "strategies[].forecast.win_rate_high",
        );
  if (status !== "CALIBRATED" && (low !== null || high !== null)) {
    fail("forecast probabilities must be null unless forecast.status is CALIBRATED");
  }
  const confidence =
    forecast.confidence === null
      ? null
      : requireMember(
          forecast.confidence,
          MARKET_CONFIDENCE,
          "strategies[].forecast.confidence",
        );
  const scope =
    forecast.scope === null
      ? null
      : validateEvidenceScope(forecast.scope, "strategies[].forecast.scope");
  if (status === "CALIBRATED") {
    if (low === null || high === null || low < 0 || high > 1) {
      fail("calibrated forecast must provide win_rate_low and win_rate_high");
    }
    if (low > high) {
      fail("forecast.win_rate_low must be <= forecast.win_rate_high");
    }
    if (
      confidence === null ||
      confidence === "UNAVAILABLE" ||
      scope === null ||
      typeof forecast.artifact_id !== "string" ||
      forecast.artifact_id.trim() === ""
    ) {
      fail("calibrated forecast must provide confidence and scope");
    }
  } else if (confidence !== null || scope !== null) {
    fail("forecast confidence and scope must be null unless forecast is CALIBRATED");
  }
  return {
    status,
    win_rate_low: low,
    win_rate_high: high,
    confidence,
    scope,
    artifact_id:
      forecast.artifact_id === null
        ? null
        : requireString(forecast.artifact_id, "strategies[].forecast.artifact_id"),
  };
}

function validateStrategy(
  strategy: unknown,
  index: number,
): StrategyBriefStrategy {
  if (!isRecord(strategy)) {
    fail(`strategies[${index}] must be an object`);
  }
  const status = requireMember(
    strategy.recommendation_status,
    STRATEGY_STATUSES,
    `strategies[${index}].recommendation_status`,
  );
  const structureType = requireMember(
    strategy.structure_type,
    STRUCTURES,
    `strategies[${index}].structure_type`,
  );
  const asOf = parseTimestamp(
    requireString(strategy.as_of, `strategies[${index}].as_of`),
    `strategies[${index}].as_of`,
  );
  const validUntil = parseTimestamp(
    requireString(strategy.valid_until, `strategies[${index}].valid_until`),
    `strategies[${index}].valid_until`,
  );
  if (validUntil <= asOf) {
    fail(`strategies[${index}].valid_until must be after as_of`);
  }
  const legs = requireArray<unknown>(
    strategy.legs,
    `strategies[${index}].legs`,
  ).map((leg, legIndex) => validateLeg(leg, legIndex));
  const expectedLegCount = structureType === "IRON_CONDOR" ? 4 : 2;
  if (legs.length !== expectedLegCount) {
    fail(`strategies[${index}] leg count does not match structure`);
  }
  const observedAtMs = legs.map((leg, legIndex) =>
    parseTimestamp(
      leg.observed_at,
      `strategies[${index}].legs[${legIndex}].observed_at`,
    ),
  );
  if (Math.max(...observedAtMs) - Math.min(...observedAtMs) > MAX_LEG_SKEW_MS) {
    fail(`strategies[${index}] legs must be synchronized within 2 seconds`);
  }
  const history = validateHistory(strategy.history);
  const forecast = validateForecast(strategy.forecast);
  const entryRaw = requireRecord(strategy.entry, `strategies[${index}].entry`);
  const riskRaw = requireRecord(strategy.risk, `strategies[${index}].risk`);
  const economicsRaw = requireRecord(
    strategy.economics,
    `strategies[${index}].economics`,
  );
  if (entryRaw.fees_included !== true || entryRaw.slippage_included !== true) {
    fail(`strategies[${index}].entry must include frozen fees and slippage`);
  }
  if (riskRaw.path_risk_status !== "VALIDATED") {
    fail(`strategies[${index}].risk.path_risk_status must be VALIDATED`);
  }
  if (economicsRaw.absolute_ev_status !== "VALIDATED") {
    fail(`strategies[${index}].economics.absolute_ev_status must be VALIDATED`);
  }
  const killConditions = requireArray<unknown>(
    strategy.kill_conditions,
    `strategies[${index}].kill_conditions`,
  ).map((condition, conditionIndex) =>
    requireString(
      condition,
      `strategies[${index}].kill_conditions[${conditionIndex}]`,
    ),
  );
  if (killConditions.length < 1 || killConditions.length > 2) {
    fail(`strategies[${index}].kill_conditions must contain one or two conditions`);
  }
  const copyRecipe = requireString(
    strategy.copy_recipe,
    `strategies[${index}].copy_recipe`,
  );
  for (const marker of [
    "MIN NET CREDIT:",
    "MAX LOSS PER UNIT:",
    "VALID UNTIL:",
    "CANCEL IF:",
    "RESEARCH_ONLY / MANUAL REVIEW REQUIRED",
  ]) {
    if (!copyRecipe.includes(marker)) {
      fail(`strategies[${index}].copy_recipe is incomplete`);
    }
  }
  const result: StrategyBriefStrategy = {
    recommendation_id: requireString(
      strategy.recommendation_id,
      `strategies[${index}].recommendation_id`,
    ),
    rank: requirePositiveNumber(strategy.rank, `strategies[${index}].rank`),
    recommendation_status: status,
    structure_type: structureType,
    thesis_zh: requireString(strategy.thesis_zh, `strategies[${index}].thesis_zh`),
    as_of: requireString(strategy.as_of, `strategies[${index}].as_of`),
    valid_until: requireString(
      strategy.valid_until,
      `strategies[${index}].valid_until`,
    ),
    legs,
    entry: {
      price_basis: requireMember(
        entryRaw.price_basis,
        new Set<PriceBasis>(["SHORT_BID_LONG_ASK"]),
        `strategies[${index}].entry.price_basis`,
      ),
      minimum_net_credit: requirePositiveNumber(
        entryRaw.minimum_net_credit,
        `strategies[${index}].entry.minimum_net_credit`,
      ),
      currency: requireString(
        entryRaw.currency,
        `strategies[${index}].entry.currency`,
      ),
      fees_included: true,
      slippage_included: true,
    },
    risk: {
      max_loss_per_unit: requirePositiveNumber(
        riskRaw.max_loss_per_unit,
        `strategies[${index}].risk.max_loss_per_unit`,
      ),
      currency: requireString(
        riskRaw.currency,
        `strategies[${index}].risk.currency`,
      ),
      breakevens: requireArray<unknown>(
        riskRaw.breakevens,
        `strategies[${index}].risk.breakevens`,
      ).map((breakeven, breakevenIndex) =>
        requireFiniteNumber(
          breakeven,
          `strategies[${index}].risk.breakevens[${breakevenIndex}]`,
        ),
      ),
      path_risk_status: requireMember(
        riskRaw.path_risk_status,
        PATH_RISK_STATUSES,
        `strategies[${index}].risk.path_risk_status`,
      ),
      cvar_95: requirePositiveNumber(
        riskRaw.cvar_95,
        `strategies[${index}].risk.cvar_95`,
      ),
    },
    economics: {
      relative_value_status: requireString(
        economicsRaw.relative_value_status,
        `strategies[${index}].economics.relative_value_status`,
      ),
      absolute_ev_status: requireString(
        economicsRaw.absolute_ev_status,
        `strategies[${index}].economics.absolute_ev_status`,
      ),
      ev_after_cost: requirePositiveNumber(
        economicsRaw.ev_after_cost,
        `strategies[${index}].economics.ev_after_cost`,
      ),
      net_r: requirePositiveNumber(
        economicsRaw.net_r,
        `strategies[${index}].economics.net_r`,
      ),
    },
    history,
    forecast,
    kill_conditions: killConditions,
    primary_reason_codes: validateReasonCodes(
      strategy.primary_reason_codes,
      `strategies[${index}].primary_reason_codes`,
    ),
    copy_recipe: copyRecipe,
  };
  if (!/^recommendation:[0-9a-f]{64}$/.test(result.recommendation_id)) {
    fail(`strategies[${index}].recommendation_id is invalid`);
  }
  if (strategy.expiry_date !== undefined) {
    result.expiry_date = requireString(
      strategy.expiry_date,
      `strategies[${index}].expiry_date`,
    );
  }
  if (strategy.dte_days !== undefined) {
    result.dte_days = requirePositiveNumber(
      strategy.dte_days,
      `strategies[${index}].dte_days`,
    );
  }
  const exactEconomics = deriveExactLegEconomics(structureType, legs);
  if (exactEconomics) {
    if (Math.abs(exactEconomics.credit - result.entry.minimum_net_credit) > 1e-6) {
      fail(`strategies[${index}] entry credit must equal short bid minus long ask`);
    }
    if (Math.abs(exactEconomics.maxLoss - result.risk.max_loss_per_unit) > 1e-6) {
      fail(`strategies[${index}] max loss must match exact legs`);
    }
    if (result.expiry_date !== exactEconomics.expiryDate) {
      fail(`strategies[${index}] expiry_date must match exact legs`);
    }
    if (legs.some((leg) => leg.premium_currency !== result.entry.currency)) {
      fail(`strategies[${index}] entry, risk, and premium currency must match`);
    }
  }
  if (result.entry.currency !== result.risk.currency) {
    fail(`strategies[${index}] entry and risk currency must match`);
  }
  const expectedDirection = {
    BEAR_CALL_CREDIT_SPREAD: "BEARISH",
    BULL_PUT_CREDIT_SPREAD: "BULLISH",
    IRON_CONDOR: "RANGE",
  }[structureType];
  for (const [claim, scope] of [
    ["history", history.status === "VALIDATED" ? history.scope : null],
    ["forecast", forecast.status === "CALIBRATED" ? forecast.scope : null],
  ] as const) {
    if (
      scope &&
      (scope.underlying !== "BTC" ||
        scope.structure_type !== structureType ||
        scope.direction !== expectedDirection ||
        scope.entry_cost_basis !== "SHORT_BID_LONG_ASK" ||
        scope.exit_basis !== "hold_to_expiry")
    ) {
      fail(`strategies[${index}] ${claim} scope does not match exact strategy`);
    }
  }
  if (
    result.recommendation_status === "RECOMMENDED" &&
    result.history.status !== "VALIDATED" &&
    result.forecast.status !== "CALIBRATED"
  ) {
    fail(`strategies[${index}] RECOMMENDED requires validated history or calibrated forecast`);
  }
  return result;
}

function validateNoTrade(value: unknown): StrategyBriefNoTrade {
  if (!isRecord(value)) {
    fail("no_trade must be an object");
  }
  const result: StrategyBriefNoTrade = {
    active:
      typeof value.active === "boolean"
        ? value.active
        : fail("no_trade.active must be boolean"),
    headline_zh:
      value.headline_zh === null
        ? null
        : requireString(value.headline_zh, "no_trade.headline_zh"),
    summary_zh:
      value.summary_zh === null
        ? null
        : requireString(value.summary_zh, "no_trade.summary_zh"),
    primary_reason_codes: validateReasonCodes(
      value.primary_reason_codes,
      "no_trade.primary_reason_codes",
    ),
    next_update_at:
      value.next_update_at === null
        ? null
        : requireString(value.next_update_at, "no_trade.next_update_at"),
  };
  if (result.next_update_at !== null) {
    parseTimestamp(result.next_update_at, "no_trade.next_update_at");
  }
  return result;
}

function validateEvidenceSummary(value: unknown): StrategyBriefEvidenceSummary {
  if (!isRecord(value)) {
    fail("evidence_summary must be an object");
  }
  const requiredCount = (field: string): number => {
    const count = requireFiniteNumber((value as Record<string, unknown>)[field], field);
    if (!Number.isInteger(count) || count < 0) {
      fail(`${field} must be a non-negative integer`);
    }
    return count;
  };
  const rejectionCountsRaw = value.rejection_counts;
  if (!isRecord(rejectionCountsRaw)) {
    fail("evidence_summary.rejection_counts must be an object");
  }
  const rejectionCounts: Record<string, number> = {};
  for (const [key, raw] of Object.entries(rejectionCountsRaw)) {
    const count = requireFiniteNumber(raw, `evidence_summary.rejection_counts.${key}`);
    if (!Number.isInteger(count) || count <= 0) {
      fail(`evidence_summary.rejection_counts.${key} must be a positive integer`);
    }
    rejectionCounts[key] = count;
  }
  const result: StrategyBriefEvidenceSummary = {
    candidate_count: requiredCount("candidate_count"),
    hard_gate_pass_count: requiredCount("hard_gate_pass_count"),
    selected_count: requiredCount("selected_count"),
    recommended_count: requiredCount("recommended_count"),
    watch_count: requiredCount("watch_count"),
    rejection_counts: rejectionCounts,
    default_structure_family:
      value.default_structure_family === null
        ? null
        : requireMember(
            value.default_structure_family,
            STRUCTURES,
            "evidence_summary.default_structure_family",
          ),
  };
  if (value.summary_zh !== undefined) {
    result.summary_zh = requireString(value.summary_zh, "evidence_summary.summary_zh");
  }
  if (value.as_of !== undefined) {
    result.as_of = requireString(value.as_of, "evidence_summary.as_of");
    parseTimestamp(result.as_of, "evidence_summary.as_of");
  }
  if (value.valid_until !== undefined) {
    result.valid_until = requireString(
      value.valid_until,
      "evidence_summary.valid_until",
    );
    parseTimestamp(result.valid_until, "evidence_summary.valid_until");
  }
  if (value.primary_reason_codes !== undefined) {
    result.primary_reason_codes = validateReasonCodes(
      value.primary_reason_codes,
      "evidence_summary.primary_reason_codes",
    );
  }
  if (value.surface !== undefined) {
    result.surface = validateSurfaceState(value.surface, "evidence_summary.surface");
  }
  if (value.items !== undefined) {
    result.items = requireArray<unknown>(value.items, "evidence_summary.items").map(
      (item, index) => {
        const record = requireRecord(item, `evidence_summary.items[${index}]`);
        return {
          label: requireString(record.label, `evidence_summary.items[${index}].label`),
          status: requireMember(
            record.status,
            new Set<"PASS" | "WARN" | "BLOCK" | "INFO">([
              "PASS",
              "WARN",
              "BLOCK",
              "INFO",
            ]),
            `evidence_summary.items[${index}].status`,
          ),
          summary_zh: requireString(
            record.summary_zh,
            `evidence_summary.items[${index}].summary_zh`,
          ),
          detail_zh: requireString(
            record.detail_zh,
            `evidence_summary.items[${index}].detail_zh`,
          ),
          artifact_id:
            record.artifact_id === null
              ? null
              : requireString(
                  record.artifact_id,
                  `evidence_summary.items[${index}].artifact_id`,
                ),
        };
      },
    );
  }
  return result;
}

export function deriveStrategyBriefAction(
  strategies: readonly Pick<StrategyBriefStrategy, "recommendation_status">[],
): StrategyBriefAction {
  if (strategies.some((strategy) => strategy.recommendation_status === "RECOMMENDED")) {
    return "STRATEGIES_AVAILABLE";
  }
  if (strategies.length > 0) {
    return "WATCH";
  }
  return "NO_TRADE";
}

function defaultStructureFamily(
  market: StrategyBriefMarket,
): StrategyStructureType | null {
  if (market.volatility !== "RICH") {
    return null;
  }
  if (market.direction === "BEARISH") {
    return "BEAR_CALL_CREDIT_SPREAD";
  }
  if (market.direction === "BULLISH") {
    return "BULL_PUT_CREDIT_SPREAD";
  }
  if (market.direction === "RANGE") {
    return "IRON_CONDOR";
  }
  return null;
}

function reasonText(code: string): string {
  return REASON_TEXT_ZH[code] ?? code;
}

function defaultSurface(
  surface?: StrategyBriefSurfaceState,
): StrategyBriefSurfaceState {
  return (
    surface ?? {
      freshness_status: "UNAVAILABLE",
      source_kind: "fallback",
      presented_as: "published",
      source_label: "运行来源不可验证",
    }
  );
}

function hasExpired(timestamp: string, nowMs?: number): boolean {
  if (nowMs === undefined) {
    return false;
  }
  return parseTimestamp(timestamp, "surface.now") <= nowMs;
}

function toSurfaceNoTrade(
  noTrade: StrategyBriefNoTrade,
  reasonCodes: string[],
): StrategyBriefSurfaceNoTrade {
  return {
    ...noTrade,
    headline_zh: noTrade.headline_zh ?? "今日暂无可靠策略",
    summary_zh: noTrade.summary_zh ?? "当前没有可靠策略卡可展示。",
    reasons_zh: reasonCodes.map(reasonText),
  };
}

export function detectStrategyBriefSuppression(
  brief: StrategyBrief,
  surface?: StrategyBriefSurfaceState,
): StrategyBriefSuppression {
  const state = defaultSurface(surface);
  const reasons: string[] = [];
  if (state.freshness_status !== "CURRENT") {
    reasons.push(reasonText("SURFACE_SOURCE_STALE_OR_UNAVAILABLE"));
  }
  if (state.presented_as === "live" && ["demo", "fallback"].includes(state.source_kind)) {
    reasons.push(reasonText("SURFACE_PROVENANCE_NOT_LIVE"));
  }
  if (hasExpired(brief.market.expires_at, state.now_ms)) {
    reasons.push(reasonText("STALE_MARKET_DATA"));
  }
  return {
    suppress_cards: reasons.length > 0,
    reasons_zh: Array.from(new Set(reasons)),
  };
}

export function projectStrategyBriefForSurface(
  brief: StrategyBrief,
  surface?: StrategyBriefSurfaceState,
): StrategyBriefSurfaceProjection {
  const state = defaultSurface(surface);
  const suppression = detectStrategyBriefSuppression(brief, state);
  const liveStrategies = brief.strategies.filter(
    (strategy) => !hasExpired(strategy.valid_until, state.now_ms),
  );
  if (!suppression.suppress_cards && liveStrategies.length > 0) {
    return {
      action: deriveStrategyBriefAction(liveStrategies),
      no_trade: toSurfaceNoTrade(brief.no_trade, brief.no_trade.primary_reason_codes),
      strategies: liveStrategies,
      suppression,
    };
  }
  const reasonCodes =
    brief.no_trade.primary_reason_codes.length > 0
      ? brief.no_trade.primary_reason_codes
      : liveStrategies.length === 0 && brief.strategies.length > 0
        ? ["STALE_MARKET_DATA"]
        : ["NO_ELIGIBLE_STRATEGY"];
  return {
    action: "NO_TRADE",
    no_trade: toSurfaceNoTrade(
      brief.no_trade,
      suppression.suppress_cards
        ? ["SURFACE_SOURCE_STALE_OR_UNAVAILABLE"]
        : reasonCodes,
    ),
    strategies: [],
    suppression,
  };
}

export function buildStrategyCombinationCopy(
  strategy: StrategyBriefStrategy,
): string {
  return strategy.copy_recipe;
}

export function validateStrategyBrief(payload: unknown): StrategyBrief {
  if (!isRecord(payload)) {
    fail("strategy brief payload must be an object");
  }
  if (payload.schema_version !== STRATEGY_BRIEF_SCHEMA) {
    fail(`unexpected strategy brief schema: ${String(payload.schema_version)}`);
  }
  const briefId = requireString(payload.brief_id, "brief_id");
  if (!/^brief:[0-9a-f]{64}$/.test(briefId)) {
    fail("brief_id must be a canonical brief identifier");
  }
  const brief: StrategyBrief = {
    schema_version: STRATEGY_BRIEF_SCHEMA,
    brief_id: briefId,
    analysis_run_id: requireString(payload.analysis_run_id, "analysis_run_id"),
    generated_at: requireString(payload.generated_at, "generated_at"),
    research_only:
      payload.research_only === true
        ? true
        : fail("research_only must remain true"),
    execution_allowed:
      payload.execution_allowed === false
        ? false
        : fail("execution_allowed must remain false"),
    market: validateMarket(payload.market),
    action: requireMember(payload.action, ACTIONS, "action"),
    strategies: requireArray<unknown>(payload.strategies, "strategies").map(
      (strategy, index) => validateStrategy(strategy, index),
    ),
    no_trade: validateNoTrade(payload.no_trade),
    evidence_summary: validateEvidenceSummary(payload.evidence_summary),
  };
  parseTimestamp(brief.generated_at, "generated_at");
  if (brief.market.action !== brief.action) {
    fail("market.action must match action");
  }
  if (brief.strategies.length > 3) {
    fail("strategies.length must be <= 3");
  }
  if (brief.action !== deriveStrategyBriefAction(brief.strategies)) {
    fail("action must match strategies");
  }
  if (brief.action === "NO_TRADE" && brief.strategies.length > 0) {
    fail("NO_TRADE briefs must not include strategies");
  }
  const seenFamilies = new Set<StrategyStructureType>();
  for (const [index, strategy] of brief.strategies.entries()) {
    if (strategy.rank !== index + 1) {
      fail("strategy ranks must be consecutive from 1");
    }
    if (seenFamilies.has(strategy.structure_type)) {
      fail("strategies must contain at most one card per structure family");
    }
    seenFamilies.add(strategy.structure_type);
    if (Date.parse(strategy.valid_until) > Date.parse(brief.market.expires_at)) {
      fail("strategy.valid_until must not outlive market.expires_at");
    }
  }
  const recommendedCount = brief.strategies.filter(
    (strategy) => strategy.recommendation_status === "RECOMMENDED",
  ).length;
  const watchCount = brief.strategies.length - recommendedCount;
  if (
    brief.evidence_summary.selected_count !== brief.strategies.length ||
    brief.evidence_summary.recommended_count !== recommendedCount ||
    brief.evidence_summary.watch_count !== watchCount ||
    brief.evidence_summary.selected_count >
      brief.evidence_summary.hard_gate_pass_count ||
    brief.evidence_summary.hard_gate_pass_count >
      brief.evidence_summary.candidate_count
  ) {
    fail("evidence_summary counts must match selected strategies");
  }
  if (
    brief.evidence_summary.default_structure_family !==
    defaultStructureFamily(brief.market)
  ) {
    fail("evidence_summary.default_structure_family must match market state");
  }
  const noTradeExpected = brief.action === "NO_TRADE";
  if (brief.no_trade.active !== noTradeExpected) {
    fail("no_trade.active must match action");
  }
  if (
    noTradeExpected &&
    (brief.no_trade.headline_zh !== "今日暂无可靠策略" ||
      !brief.no_trade.summary_zh)
  ) {
    fail("active no_trade must explain 今日暂无可靠策略");
  }
  if (
    !noTradeExpected &&
    (brief.no_trade.headline_zh !== null || brief.no_trade.summary_zh !== null)
  ) {
    fail("inactive no_trade text must be null");
  }
  return brief;
}
