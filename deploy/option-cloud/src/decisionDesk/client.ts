import type { DecisionDesk, DeskAsset, DeskComparison, DeskCriteria, DeskMode, DeskReview, DeskScenario } from "./types";

type Obj = Record<string, unknown>;
function fail(): never { throw new Error("研究数据格式或安全约束校验失败，请重新获取。" ); }
function obj(value: unknown): Obj {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail();
  return value as Obj;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value.trim() || value.length > 2000) fail();
  return value;
}
function number(value: unknown, min = -1e12, max = 1e12): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) fail();
  return value;
}
function count(value: unknown): void { if (!Number.isSafeInteger(number(value, 0, 1e8))) fail(); }
function optionalNumber(value: unknown, min = -1e12): void { if (value !== null) number(value, min); }
function oneOf(value: unknown, values: readonly unknown[]): void { if (!values.includes(value)) fail(); }
function date(value: unknown): string {
  const result = text(value);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(result) || !Number.isFinite(Date.parse(result))) fail();
  return result;
}
function list(value: unknown, max = 200): unknown[] { if (!Array.isArray(value) || value.length > max) fail(); return value; }
function reasons(value: unknown): void { list(value).forEach((item) => { const r = obj(item); text(r.code); text(r.detail); }); }
function counts(value: unknown): void { Object.values(obj(value)).forEach(count); }

/** Validate observed research independently of the legacy historical admission contract. */
export function validateDecisionDesk(value: unknown): DecisionDesk {
  const d = obj(value);
  oneOf(d.schema_version, ["decision_desk.v1"]);
  date(d.generated_at); date(d.expires_at); text(d.snapshot_id); text(d.analysis_id);
  oneOf(d.asset, ["BTC", "ETH"]); oneOf(d.venue, ["DERIBIT"]); oneOf(d.contract_family, ["LINEAR_USDC"]);
  const source = obj(d.source);
  oneOf(source.mode, ["live", "demo", "replay"]); text(source.provider); date(source.captured_at);
  if (source.notice !== undefined && source.notice !== null) text(source.notice);
  const generatedMs = Date.parse(d.generated_at as string);
  const expiresMs = Date.parse(d.expires_at as string);
  const capturedMs = Date.parse(source.captured_at as string);
  if (capturedMs > generatedMs + 5000 || expiresMs > capturedMs + 60000) fail();
  const market = obj(d.market);
  optionalNumber(market.index_price, 0); oneOf(market.index_currency, ["USDC"]); oneOf(market.settlement_currency, ["USDC"]);
  const coverage = obj(d.coverage);
  for (const key of ["registry_count", "summary_count", "inverse_excluded_count", "eligible_instrument_count", "deepened_count"]) count(coverage[key]);
  if (typeof coverage.scan_complete !== "boolean") fail();
  list(coverage.failures).forEach(text); counts(coverage.exclusions);
  list(coverage.expiry_counts).forEach((item) => { const row = obj(item); text(row.expiry_date); count(row.count); });
  for (const key of ["scanned_instrument_count", "formed_structure_count", "matched_count", "shortlisted_count", "shortlist_limit", "deep_candidate_count"]) {
    if (coverage[key] !== undefined) count(coverage[key]);
  }
  const criteria = obj(d.criteria);
  oneOf(criteria.viewpoint, ["all", "bullish", "bearish", "range"]);
  number(criteria.dte_min, 0, 365); number(criteria.dte_max, number(criteria.dte_min), 365);
  number(criteria.max_width_pct, 0.001, 1); number(criteria.max_spread_ratio, 0, 10);
  const q = obj(d.qualification);
  if (q.execution_allowed !== false) fail();
  oneOf(q.data_status, ["current", "partial", "stale", "unavailable"]);
  oneOf(q.opportunity_status, ["available", "no_match", "data_blocked", "liquidity_blocked", "risk_blocked"]);
  counts(q.exclusion_counts);
  const ids = new Set<string>();
  for (const raw of list(d.candidates, 200)) {
    const c = obj(raw);
    const id = text(c.candidate_id); if (ids.has(id)) fail(); ids.add(id);
    oneOf(c.structure, ["BULL_PUT_CREDIT", "BEAR_CALL_CREDIT", "IRON_CONDOR"]);
    oneOf(c.viewpoint, ["bullish", "bearish", "range"]);
    text(c.expiry_date); number(c.expiration_timestamp, 1, Number.MAX_SAFE_INTEGER); number(c.dte_days, -36500, 36500);
    oneOf(c.status, ["comparable", "research_only", "excluded"]);
    reasons(c.reasons); reasons(c.invalidation); date(c.recheck_at); text(c.assumptions_id);
    const legs = list(c.legs, 4).map(obj);
    if (legs.length !== (c.structure === "IRON_CONDOR" ? 4 : 2)) fail();
    const names = new Set<string>();
    for (const leg of legs) {
      const name = text(leg.instrument_name); if (names.has(name)) fail(); names.add(name);
      oneOf(leg.side, ["BUY", "SELL"]); number(leg.ratio, 1, 1); number(leg.contract_size, Number.MIN_VALUE);
      number(leg.strike, Number.MIN_VALUE); oneOf(leg.option_type, ["call", "put"]);
      oneOf(leg.price_currency, ["USDC"]); oneOf(leg.settlement_currency, ["USDC"]);
      for (const key of ["bid", "ask", "bid_size", "ask_size", "iv_decimal"]) optionalNumber(leg[key], 0);
      for (const key of ["quote_time", "observed_at"]) if (leg[key] !== null) date(leg[key]);
      if (c.status === "comparable") {
        number(leg.bid, Number.MIN_VALUE); number(leg.ask, number(leg.bid));
        number(leg.bid_size, Number.MIN_VALUE); number(leg.ask_size, Number.MIN_VALUE);
        date(leg.quote_time); date(leg.observed_at);
      }
    }
    if (new Set(legs.map((leg) => leg.contract_size)).size !== 1) fail();
    if (c.status === "comparable") {
      const expiryMs = number(c.expiration_timestamp, 1, Number.MAX_SAFE_INTEGER);
      const recheckMs = Date.parse(c.recheck_at as string);
      const quoteTimes = legs.map((leg) => Date.parse(leg.quote_time as string));
      if (expiryMs <= generatedMs || expiresMs <= generatedMs || recheckMs <= generatedMs || recheckMs > expiresMs || recheckMs > expiryMs) fail();
      if (new Date(expiryMs).toISOString().slice(0, 10) !== c.expiry_date || Math.abs(number(c.dte_days) - (expiryMs - generatedMs) / 86400000) > 0.00002) fail();
      if (Math.max(...quoteTimes) - Math.min(...quoteTimes) > 2000 || recheckMs > Math.min(...quoteTimes) + 60000) fail();
      for (const leg of legs) {
        const qt = Date.parse(leg.quote_time as string), observed = Date.parse(leg.observed_at as string);
        if (generatedMs - qt > 60000 || qt - generatedMs > 5000 || observed - generatedMs > 5000 || qt - observed > 5000) fail();
      }
    }
    const wing = (kind: "call" | "put"): void => {
      const rows = legs.filter((leg) => leg.option_type === kind);
      if (rows.length !== 2 || rows.filter((leg) => leg.side === "BUY").length !== 1 || rows.filter((leg) => leg.side === "SELL").length !== 1) fail();
      const buy = rows.find((leg) => leg.side === "BUY")!;
      const sell = rows.find((leg) => leg.side === "SELL")!;
      if (kind === "put" ? number(buy.strike) >= number(sell.strike) : number(buy.strike) <= number(sell.strike)) fail();
    };
    if (c.structure !== "BEAR_CALL_CREDIT") wing("put");
    if (c.structure !== "BULL_PUT_CREDIT") wing("call");
    if (c.structure === "IRON_CONDOR") {
      if (Math.max(...legs.filter((l) => l.option_type === "put").map((l) => number(l.strike))) >= Math.min(...legs.filter((l) => l.option_type === "call").map((l) => number(l.strike)))) fail();
    }
    const e = obj(c.economics);
    oneOf(e.currency, ["USDC"]); oneOf(e.premium_kind, ["credit", "debit"]);
    oneOf(e.loss_bound_scope, ["OPTION_PAYOFF_EXCLUDING_DYNAMIC_DELIVERY_FEES"]); text(e.fee_policy_id);
    optionalNumber(e.entry_cash); optionalNumber(e.net_entry_cash);
    for (const key of ["entry_fees", "mid_to_touch_drag", "option_payoff_loss_bound"]) optionalNumber(e[key], 0);
    if (c.status === "comparable") {
      number(e.entry_cash); number(e.entry_fees, 0); number(e.net_entry_cash);
      if (Math.abs(number(e.net_entry_cash) - (number(e.entry_cash) - number(e.entry_fees))) > 0.00001) fail();
    }
  }
  if (q.opportunity_status === "available" && !(d.candidates as Obj[]).some((candidate) => candidate.status === "comparable")) fail();
  return value as DecisionDesk;
}

export function validateDeskComparison(value: unknown): DeskComparison {
  const d = obj(value);
  oneOf(d.schema_version, ["research_comparison.v1"]); oneOf(d.asset, ["BTC", "ETH"]); oneOf(d.currency, ["USDC"]);
  if (d.execution_allowed !== false) fail();
  text(d.snapshot_id); text(d.analysis_id); text(d.scenario_id); text(d.assumptions_id); date(d.generated_at);
  const scenario = obj(d.scenario);
  number(scenario.price_change_pct, -50, 50); number(scenario.time_days, 0, 365); number(scenario.iv_shift_points, -30, 30);
  list(d.assumptions).forEach(text);
  const members = list(d.members, 3); if (members.length < 2) fail();
  const ids = new Set<string>();
  for (const raw of members) {
    const m = obj(raw); const id = text(m.candidate_id); if (ids.has(id)) fail(); ids.add(id);
    oneOf(m.currency, ["USDC"]); number(m.entry_cash); number(m.entry_fees, 0);
    const points = list(m.expiry_points, 1000); if (points.length < 2) fail();
    let prior = -1;
    for (const rawPoint of points) { const p = obj(rawPoint); const price = number(p.price, 0); if (price < prior) fail(); prior = price; number(p.pnl); }
    if (m.stress !== null) { const stress = obj(m.stress); number(stress.theoretical_value); number(stress.hypothetical_pnl); }
    if (m.stress_reason !== undefined && m.stress_reason !== null) text(m.stress_reason);
  }
  return value as DeskComparison;
}

export function validateDeskReview(value: unknown): DeskReview {
  const r = obj(value);
  oneOf(r.schema_version, ["desk_review.v1"]); date(r.reviewed_at); text(r.original_snapshot_id); text(r.original_candidate_id);
  if (r.reviewed_candidate_id !== null) text(r.reviewed_candidate_id);
  oneOf(r.status, ["current", "expired", "unavailable"]); reasons(r.reasons);
  if (r.desk !== null) validateDecisionDesk(r.desk);
  if (r.status === "current" && r.desk === null) fail();
  if (r.desk !== null && !(r.desk as DecisionDesk).candidates.some((candidate) => candidate.candidate_id === r.reviewed_candidate_id)) fail();
  return value as DeskReview;
}

async function post<T>(path: string, body: unknown, validate: (value: unknown) => T): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => { controller.abort(); reject(new Error("行情采集超时，请稍后重新获取。")); }, 75_000);
  });
  try {
    const request = (async () => {
      const response = await fetch(path, {
        method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body), cache: "no-store", redirect: "error", credentials: "same-origin", signal: controller.signal,
      });
      if (response.redirected) fail();
      const declared = Number(response.headers.get("Content-Length"));
      if (declared > 4 * 1024 * 1024) fail();
      const raw = await response.text(); if (raw.length > 4 * 1024 * 1024) fail();
      let value: unknown; try { value = JSON.parse(raw); } catch { fail(); }
      if (!response.ok) {
        if (response.status === 409) throw new Error("这份快照已过期或当前来源未启用，请重新获取行情后比较。" );
        if (response.status === 401 || response.status === 403) throw new Error("研究服务拒绝当前访问，请检查私有访问配置。" );
        throw new Error("研究服务暂不可用，请稍后重试。" );
      }
      return validate(value);
    })();
    return await Promise.race([request, timeout]);
  } finally { if (timer !== undefined) clearTimeout(timer); }
}

export async function discoverDesk(asset: DeskAsset, criteria: DeskCriteria, mode: DeskMode): Promise<DecisionDesk> {
  const result = await post("/desk/discover", { asset, criteria, mode }, validateDecisionDesk);
  if (result.asset !== asset || result.source.mode !== mode || Object.entries(criteria).some(([key, value]) => result.criteria[key as keyof DeskCriteria] !== value)) fail();
  return result;
}
export async function compareDesk(snapshot_id: string, candidate_ids: string[], scenario: DeskScenario, analysis_id: string): Promise<DeskComparison> {
  const result = await post("/desk/compare", { snapshot_id, analysis_id, candidate_ids, scenario }, validateDeskComparison);
  if (result.snapshot_id !== snapshot_id || result.analysis_id !== analysis_id || result.members.length !== candidate_ids.length || result.members.some((member) => !candidate_ids.includes(member.candidate_id)) || Object.entries(scenario).some(([key, value]) => result.scenario[key as keyof DeskScenario] !== value)) fail();
  return result;
}
export async function reviewObservation(record: { desk: DecisionDesk; candidate_id: string }): Promise<DeskReview> {
  const result = await post("/desk/review", { original_desk: record.desk, candidate_id: record.candidate_id }, validateDeskReview);
  if (result.original_snapshot_id !== record.desk.snapshot_id || result.original_candidate_id !== record.candidate_id) fail();
  return result;
}
