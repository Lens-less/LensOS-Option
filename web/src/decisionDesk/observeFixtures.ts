import type { DecisionDesk, DeskCandidate, DeskComparison, DeskLeg, DeskReview } from "./types";

/** Fictional fixtures, confined to deterministic browser-state tests. */
export function observeDeskFixture(): DecisionDesk {
  const now = new Date();
  const expiry = new Date(now.getTime() + 21 * 86_400_000);
  const generated = now.toISOString();
  const expires = new Date(now.getTime() + 60_000).toISOString();
  const leg = (side: "BUY" | "SELL", strike: number, kind: "put" | "call"): DeskLeg => ({
    instrument_name: `BTC_USDC-${expiry.toISOString().slice(0, 10)}-${strike}-${kind[0].toUpperCase()}`,
    side, strike, option_type: kind, ratio: 1, contract_size: 1,
    bid: side === "SELL" ? 900 : 300, ask: side === "SELL" ? 950 : 350,
    bid_size: 10, ask_size: 10, quote_time: generated, observed_at: generated,
    price_currency: "USDC", settlement_currency: "USDC", iv_decimal: 0.65,
  });
  const candidate = (id: string, kind: "put" | "call"): DeskCandidate => ({
    candidate_id: id, structure: kind === "put" ? "BULL_PUT_CREDIT" : "BEAR_CALL_CREDIT",
    viewpoint: kind === "put" ? "bullish" : "bearish", expiry_date: expiry.toISOString().slice(0, 10),
    expiration_timestamp: expiry.getTime(), dte_days: 21, status: "comparable", reasons: [],
    legs: kind === "put" ? [leg("BUY", 85_000, kind), leg("SELL", 90_000, kind)]
      : [leg("SELL", 110_000, kind), leg("BUY", 115_000, kind)],
    economics: {
      entry_cash: 550, net_entry_cash: 548, premium_kind: "credit", entry_fees: 2,
      mid_to_touch_drag: 50, option_payoff_loss_bound: 4_450,
      loss_bound_scope: "OPTION_PAYOFF_EXCLUDING_DYNAMIC_DELIVERY_FEES", currency: "USDC", fee_policy_id: "fixture-fees",
    },
    invalidation: [{ code: "QUOTE_EXPIRY", detail: "报价过期后重新复核" }],
    recheck_at: expires, assumptions_id: "fixture-assumptions",
  });
  return {
    schema_version: "decision_desk.v1", generated_at: generated, expires_at: expires,
    snapshot_id: "fixture-original", analysis_id: "fixture-analysis", asset: "BTC", venue: "DERIBIT",
    contract_family: "LINEAR_USDC", source: { mode: "demo", provider: "SYNTHETIC_TEST", captured_at: generated },
    market: { index_price: 100_000, index_currency: "USDC", settlement_currency: "USDC" },
    coverage: {
      registry_count: 4, summary_count: 4, scan_complete: true, inverse_excluded_count: 0,
      eligible_instrument_count: 4, deepened_count: 4, failures: [], exclusions: {},
      expiry_counts: [{ expiry_date: expiry.toISOString().slice(0, 10), count: 4 }],
    },
    criteria: { viewpoint: "all", dte_min: 7, dte_max: 45, max_width_pct: 0.1, max_spread_ratio: 0.5 },
    qualification: { data_status: "current", opportunity_status: "available", exclusion_counts: {}, execution_allowed: false },
    candidates: [candidate("fixture-put", "put"), candidate("fixture-call", "call")],
  };
}

export function observeComparisonFixture(desk: DecisionDesk): DeskComparison {
  return {
    schema_version: "research_comparison.v1", snapshot_id: desk.snapshot_id, scenario_id: "fixture-scenario",
    assumptions_id: "fixture-assumptions", analysis_id: desk.analysis_id, asset: "BTC", currency: "USDC", generated_at: desk.generated_at,
    scenario: { price_change_pct: -10, time_days: 3, iv_shift_points: 5 },
    assumptions: ["测试用固定结构比例，模型结果不代表实际持仓"], execution_allowed: false,
    members: desk.candidates.map((candidate) => ({
      candidate_id: candidate.candidate_id,
      expiry_points: [{ price: 80_000, pnl: -4_452 }, { price: 100_000, pnl: 548 }, { price: 120_000, pnl: 548 }],
      stress: { theoretical_value: -200, hypothetical_pnl: 348 }, entry_cash: 550, entry_fees: 2, currency: "USDC",
    })),
  };
}

export function observeReviewFixture(desk: DecisionDesk): DeskReview {
  const current = structuredClone(desk);
  current.snapshot_id = "fixture-reviewed";
  current.analysis_id = "fixture-new-analysis";
  current.candidates[0].candidate_id = "fixture-new-put";
  current.candidates[0].legs[0].bid = 325;
  current.candidates[0].legs[0].ask = 375;
  return {
    schema_version: "desk_review.v1", reviewed_at: new Date().toISOString(),
    original_snapshot_id: desk.snapshot_id, original_candidate_id: desk.candidates[0].candidate_id,
    reviewed_candidate_id: current.candidates[0].candidate_id, desk: current, status: "current", reasons: [],
  };
}
