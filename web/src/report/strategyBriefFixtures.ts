import type {
  StrategyBrief,
  StrategyBriefStrategy,
  StrategyBriefSurfaceState,
} from "./strategyBrief";

function clone<T>(value: T): T {
  return structuredClone(value);
}

export const liveSurface: StrategyBriefSurfaceState = {
  freshness_status: "CURRENT",
  source_kind: "live",
  presented_as: "live",
  source_label: "Live API snapshot",
  now_ms: Date.parse("2026-08-30T14:30:30+08:00"),
};

export const staleSurface: StrategyBriefSurfaceState = {
  freshness_status: "STALE",
  source_kind: "live",
  presented_as: "live",
  source_label: "Stale live snapshot",
  now_ms: Date.parse("2026-08-30T14:40:30+08:00"),
};

export const demoMasqueradingLiveSurface: StrategyBriefSurfaceState = {
  freshness_status: "CURRENT",
  source_kind: "demo",
  presented_as: "live",
  source_label: "Demo snapshot",
  now_ms: Date.parse("2026-08-30T14:30:30+08:00"),
};

export const recommendedStrategyFixture: StrategyBriefStrategy = {
  recommendation_id: `recommendation:${"0".repeat(64)}`,
  rank: 1,
  recommendation_status: "RECOMMENDED",
  structure_type: "BEAR_CALL_CREDIT_SPREAD",
  thesis_zh: "偏空且隐含波动率偏贵, 卖出看涨信用价差并用买入翼限制最大亏损.",
  as_of: "2026-08-30T14:30:05+08:00",
  valid_until: "2026-08-30T14:35:05+08:00",
  legs: [
    {
      instrument_name: "BTC-30AUG26-125000-C",
      side: "SELL",
      quantity: 1,
      observed_at: "2026-08-30T14:30:04+08:00",
      bid: 0.0132,
      ask: 0.0135,
      premium_unit: "BTC",
    },
    {
      instrument_name: "BTC-30AUG26-130000-C",
      side: "BUY",
      quantity: 1,
      observed_at: "2026-08-30T14:30:05+08:00",
      bid: 0.0091,
      ask: 0.0095,
      premium_unit: "BTC",
    },
  ],
  entry: {
    price_basis: "SHORT_BID_LONG_ASK",
    minimum_net_credit: 0.0037,
    currency: "BTC",
    fees_included: true,
    slippage_included: true,
  },
  risk: {
    max_loss_per_unit: 0.0463,
    currency: "BTC",
    breakevens: [125000],
    path_risk_status: "VALIDATED",
    cvar_95: 0.0281,
  },
  economics: {
    relative_value_status: "AVAILABLE",
    absolute_ev_status: "VALIDATED",
    ev_after_cost: 0.0014,
    net_r: 0.0302,
  },
  history: {
    status: "VALIDATED",
    win_rate: 0.68,
    mean_net_r: 0.21,
    independent_cohorts: 12,
    observation_count: 118,
    exit_basis: "hold_to_expiry",
    artifact_id: "history:bear-call-validated",
    scope: {
      underlying: "BTC",
      structure_type: "BEAR_CALL_CREDIT_SPREAD",
      direction: "BEARISH",
      dte_band_days: [7, 35],
      entry_cost_basis: "SHORT_BID_LONG_ASK",
      exit_basis: "hold_to_expiry",
    },
  },
  forecast: {
    status: "UNAVAILABLE",
    win_rate_low: null,
    win_rate_high: null,
    confidence: null,
    scope: null,
    artifact_id: "forecast:screening-only",
  },
  kill_conditions: ["任一腿报价失效", "两腿 observed_at 相差超过 2 秒"],
  primary_reason_codes: [],
  copy_recipe: [
    "STRATEGY: BEAR_CALL_CREDIT_SPREAD",
    "SELL 1 BTC-30AUG26-125000-C",
    "BUY  1 BTC-30AUG26-130000-C",
    "MIN NET CREDIT: 0.0037 BTC",
    "MAX LOSS PER UNIT: 0.0463 BTC",
    "VALID UNTIL: 2026-08-30T14:35:05+08:00",
    "CANCEL IF: 任一腿报价失效",
    "CANCEL IF: 两腿 observed_at 相差超过 2 秒",
    "RESEARCH_ONLY / MANUAL REVIEW REQUIRED",
  ].join("\n"),
};

const watchStrategyFixture: StrategyBriefStrategy = {
  ...clone(recommendedStrategyFixture),
  recommendation_id: `recommendation:${"1".repeat(64)}`,
  recommendation_status: "WATCH",
  structure_type: "BEAR_CALL_CREDIT_SPREAD",
  rank: 1,
  thesis_zh: "偏空结构值得继续观察，但历史与预测证据仍未成熟。",
  history: {
    status: "EXPLORATORY",
    win_rate: null,
    mean_net_r: null,
    independent_cohorts: 5,
    observation_count: 44,
    exit_basis: "hold_to_expiry",
    artifact_id: "history:condor-exploratory",
    scope: null,
  },
  forecast: {
    status: "UNAVAILABLE",
    win_rate_low: null,
    win_rate_high: null,
    confidence: null,
    scope: null,
    artifact_id: "forecast:unavailable",
  },
  primary_reason_codes: [
    "HISTORICAL_EVIDENCE_INSUFFICIENT",
    "FORECAST_NOT_CALIBRATED",
  ],
};

export const strategyBriefFixture: StrategyBrief = {
  schema_version: "strategy_brief.v1",
  brief_id: `brief:${"0".repeat(64)}`,
  analysis_run_id: "analysis:fixture",
  generated_at: "2026-08-30T14:30:05+08:00",
  research_only: true,
  execution_allowed: false,
  market: {
    underlying: "BTC",
    as_of: "2026-08-30T14:30:05+08:00",
    expires_at: "2026-08-30T14:35:05+08:00",
    direction: "RANGE",
    volatility: "RICH",
    liquidity: "EXECUTABLE",
    confidence: "HIGH",
    action: "STRATEGIES_AVAILABLE",
    summary_zh: "BTC: 震荡 | 隐含波动率偏贵 | 流动性可执行",
  },
  action: "STRATEGIES_AVAILABLE",
  strategies: [clone(recommendedStrategyFixture)],
  no_trade: {
    active: false,
    headline_zh: null,
    summary_zh: null,
    primary_reason_codes: [],
    reasons_zh: [],
    next_update_at: "2026-08-30T14:35:05+08:00",
  },
  evidence_summary: {
    candidate_count: 2,
    hard_gate_pass_count: 1,
    selected_count: 1,
    recommended_count: 1,
    watch_count: 0,
    rejection_counts: {},
    default_structure_family: "IRON_CONDOR",
    summary_zh: "市场、执行、风险和证据摘要可展开审计。",
    as_of: "2026-08-30T14:30:05+08:00",
    valid_until: "2026-08-30T14:35:05+08:00",
    primary_reason_codes: [],
    surface: liveSurface,
    items: [],
  },
};

export const watchOnlyBriefFixture: StrategyBrief = {
  ...clone(strategyBriefFixture),
  action: "WATCH",
  market: {
    ...strategyBriefFixture.market,
    action: "WATCH",
  },
  strategies: [clone(watchStrategyFixture)],
  no_trade: {
    active: false,
    headline_zh: null,
    summary_zh: null,
    primary_reason_codes: [],
    reasons_zh: [],
    next_update_at: "2026-08-30T14:35:05+08:00",
  },
  evidence_summary: {
    candidate_count: 1,
    hard_gate_pass_count: 1,
    selected_count: 1,
    recommended_count: 0,
    watch_count: 1,
    rejection_counts: {},
    default_structure_family: "IRON_CONDOR",
    summary_zh: "仅观察，不展示预测概率。",
    as_of: "2026-08-30T14:30:05+08:00",
    valid_until: "2026-08-30T14:35:05+08:00",
    primary_reason_codes: ["FORECAST_NOT_CALIBRATED"],
    surface: liveSurface,
    items: [],
  },
};

export const noTradeBriefFixture: StrategyBrief = {
  ...clone(strategyBriefFixture),
  action: "NO_TRADE",
  market: {
    ...strategyBriefFixture.market,
    direction: "UNCLEAR",
    action: "NO_TRADE",
  },
  strategies: [],
  no_trade: {
    active: true,
    headline_zh: "今日暂无可靠策略",
    summary_zh: "当前表面不能把这份简报当作有效策略建议。",
    primary_reason_codes: ["NEGATIVE_EV_AFTER_COST"],
    reasons_zh: ["当前没有可靠策略卡可展示。"],
    next_update_at: "2026-08-30T14:35:05+08:00",
  },
  evidence_summary: {
    candidate_count: 3,
    hard_gate_pass_count: 0,
    selected_count: 0,
    recommended_count: 0,
    watch_count: 0,
    rejection_counts: { NEGATIVE_EV_AFTER_COST: 3 },
    default_structure_family: null,
    summary_zh: "当前没有可展示的策略卡。",
    as_of: "2026-08-30T14:30:05+08:00",
    valid_until: "2026-08-30T14:35:05+08:00",
    primary_reason_codes: ["NEGATIVE_EV_AFTER_COST"],
    surface: staleSurface,
    items: [],
  },
};
