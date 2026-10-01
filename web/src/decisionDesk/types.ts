export type DeskAsset = "BTC" | "ETH";
export type Viewpoint = "all" | "bullish" | "bearish" | "range";
export type DeskStructure = "BULL_PUT_CREDIT" | "BEAR_CALL_CREDIT" | "IRON_CONDOR";
export interface DeskCriteria {
  viewpoint: Viewpoint;
  dte_min: number;
  dte_max: number;
  max_width_pct: number;
  max_spread_ratio: number;
}
export interface DeskReason { code: string; detail: string }
export interface DeskSource {
  mode: "live" | "demo" | "replay";
  provider: string;
  captured_at: string;
  notice?: string | null;
}
export interface DeskLeg {
  instrument_name: string;
  side: "BUY" | "SELL";
  ratio: number;
  contract_size: number;
  strike: number;
  option_type: "call" | "put";
  bid: number | null;
  ask: number | null;
  bid_size: number | null;
  ask_size: number | null;
  quote_time: string | null;
  observed_at: string | null;
  price_currency: "USDC";
  settlement_currency: "USDC";
  iv_decimal: number | null;
}
export interface DeskCandidate {
  candidate_id: string;
  structure: DeskStructure;
  viewpoint: Exclude<Viewpoint, "all">;
  expiry_date: string;
  expiration_timestamp: number;
  dte_days: number;
  status: "comparable" | "research_only" | "excluded";
  reasons: DeskReason[];
  legs: DeskLeg[];
  economics: {
    entry_cash: number | null;
    premium_kind: "credit" | "debit";
    entry_fees: number | null;
    net_entry_cash: number | null;
    mid_to_touch_drag: number | null;
    option_payoff_loss_bound: number | null;
    loss_bound_scope: "OPTION_PAYOFF_EXCLUDING_DYNAMIC_DELIVERY_FEES";
    currency: "USDC";
    fee_policy_id: string;
  };
  invalidation: DeskReason[];
  recheck_at: string;
  assumptions_id: string;
}
export interface DeskCoverage {
  registry_count: number;
  summary_count: number;
  scan_complete: boolean;
  inverse_excluded_count: number;
  eligible_instrument_count: number;
  deepened_count: number;
  failures: string[];
  exclusions: Record<string, number>;
  expiry_counts: { expiry_date: string; count: number }[];
  scanned_instrument_count?: number;
  formed_structure_count?: number;
  matched_count?: number;
  shortlisted_count?: number;
  shortlist_limit?: number;
  deep_candidate_count?: number;
}
export interface DecisionDesk {
  schema_version: "decision_desk.v1";
  generated_at: string;
  expires_at: string;
  snapshot_id: string;
  analysis_id: string;
  asset: DeskAsset;
  venue: "DERIBIT";
  contract_family: "LINEAR_USDC";
  source: DeskSource;
  market: { index_price: number | null; index_currency: "USDC"; settlement_currency: "USDC" };
  coverage: DeskCoverage;
  criteria: DeskCriteria;
  qualification: {
    data_status: "current" | "partial" | "stale" | "unavailable";
    opportunity_status: "available" | "no_match" | "data_blocked" | "liquidity_blocked" | "risk_blocked";
    exclusion_counts: Record<string, number>;
    execution_allowed: false;
  };
  candidates: DeskCandidate[];
}
export interface DeskScenario { price_change_pct: number; time_days: number; iv_shift_points: number }
export interface DeskComparison {
  schema_version: "research_comparison.v1";
  analysis_id: string;
  snapshot_id: string;
  scenario_id: string;
  assumptions_id: string;
  asset: DeskAsset;
  currency: "USDC";
  generated_at: string;
  scenario: DeskScenario;
  assumptions: string[];
  execution_allowed: false;
  members: {
    candidate_id: string;
    expiry_points: { price: number; pnl: number }[];
    stress: { theoretical_value: number; hypothetical_pnl: number } | null;
    stress_reason?: string | null;
    entry_cash: number;
    entry_fees: number;
    currency: "USDC";
  }[];
}
export type DeskMode = "demo" | "live";
export interface DeskReview {
  schema_version: "desk_review.v1";
  reviewed_at: string;
  original_snapshot_id: string;
  original_candidate_id: string;
  reviewed_candidate_id: string | null;
  desk: DecisionDesk | null;
  status: "current" | "expired" | "unavailable";
  reasons: DeskReason[];
}
export const DEFAULT_DESK_CRITERIA: DeskCriteria = {
  viewpoint: "all", dte_min: 7, dte_max: 45,
  max_width_pct: 0.1, max_spread_ratio: 0.5,
};
export const DEFAULT_DESK_SCENARIO: DeskScenario = {
  price_change_pct: 0, time_days: 0, iv_shift_points: 0,
};
