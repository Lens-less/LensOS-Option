/** Exact expiry arithmetic for same-expiry, European, cash-settled linear options.
 * No probabilities, mark model, future volatility or margin estimates enter this module.
 * Premiums are quote-currency amounts per underlying unit. Fees are cash per contract.
 */
import { isoInstant } from './time';
export interface PayoffLeg {
  instrument: string;
  asset: string;
  currency: string;
  expiry: string;
  optionType: 'call' | 'put';
  strike: number;
  quantity: number; // positive = long; negative = short
  multiplier: number;
  exercise: 'european';
  settlement: 'cash_linear';
}

export interface QuotedLeg extends PayoffLeg { bid: number; ask: number }
export interface PayoffProfile {
  maxLoss: number | null;
  bestPnl: number | null;
  lossBounded: boolean;
  profitBounded: boolean;
  breakevens: number[];
  zeroRanges: { from: number; to: number | null }[];
  entryCash: number;
  fixedExpiryCosts: number;
  upsideSlope: number;
  points: { price: number; pnl: number }[];
}

const EPSILON = 1e-8;
const finite = (n: number): number => {
  if (!Number.isFinite(n)) throw new Error('金额或数量超出可计算范围');
  return n;
};
export const roundCash = (n: number): number => finite(Math.round(finite(n) * 1e8) / 1e8);
const zero = (n: number): boolean => Math.abs(n) < EPSILON;

export function validatePayoffLegs(legs: readonly PayoffLeg[]): void {
  if (!legs.length || legs.length > 20) throw new Error('需要 1–20 条完整合约腿');
  const first = legs[0];
  const names = new Set<string>();
  for (const leg of legs) {
    if (!leg.instrument || names.has(leg.instrument)) throw new Error('合约标识缺失或重复');
    names.add(leg.instrument);
    if (!leg.asset || !leg.currency || !isoInstant(leg.expiry)) {
      throw new Error('标的、币种和带时区的准确到期时刻必须明确');
    }
    if (leg.exercise !== 'european' || leg.settlement !== 'cash_linear') throw new Error('基础计算仅支持欧式、现金线性结算');
    if (!['call', 'put'].includes(leg.optionType) || !Number.isFinite(leg.strike) || leg.strike <= 0
      || !Number.isFinite(leg.quantity) || leg.quantity === 0 || !Number.isFinite(leg.multiplier) || leg.multiplier <= 0) {
      throw new Error('执行价、带方向数量或合约单位无效');
    }
    if (leg.asset !== first.asset || leg.currency !== first.currency || Date.parse(leg.expiry) !== Date.parse(first.expiry)
      || leg.multiplier !== first.multiplier) throw new Error('同一结构的标的、币种、到期时刻与合约单位必须相同');
  }
}

function signedExpiryValue(legs: readonly PayoffLeg[], price: number): number {
  return roundCash(legs.reduce((total, leg) => total + leg.quantity * leg.multiplier
    * (leg.optionType === 'call' ? Math.max(price - leg.strike, 0) : Math.max(leg.strike - price, 0)), 0));
}

export function expiryPnl(legs: readonly PayoffLeg[], price: number, entryCash: number, fixedExpiryCosts = 0): number {
  validatePayoffLegs(legs);
  if (!Number.isFinite(price) || price < 0 || !Number.isFinite(fixedExpiryCosts) || fixedExpiryCosts < 0) {
    throw new Error('到期价格与固定费用须为非负有限值');
  }
  return roundCash(finite(entryCash) + signedExpiryValue(legs, price) - fixedExpiryCosts);
}

export function entryCashAtTouch(legs: readonly QuotedLeg[], feePerContract: number): { gross: number; fees: number; net: number } {
  validatePayoffLegs(legs);
  if (!Number.isFinite(feePerContract) || feePerContract < 0) throw new Error('每张合约入场费必须为非负现金金额');
  let gross = 0; let contracts = 0;
  for (const leg of legs) {
    if (!Number.isFinite(leg.bid) || !Number.isFinite(leg.ask) || leg.bid < 0 || leg.ask <= 0 || leg.bid > leg.ask) {
      throw new Error('每条腿必须提供未交叉的有效 Bid / Ask');
    }
    gross -= leg.quantity * leg.multiplier * (leg.quantity > 0 ? leg.ask : leg.bid);
    contracts += Math.abs(leg.quantity);
  }
  const fees = roundCash(contracts * feePerContract);
  return { gross: roundCash(gross), fees, net: roundCash(gross - fees) };
}

/** Complete extrema use spot=0, every strike and the unbounded call-tail slope.
 * A fixed cash cost shifts the curve. Variable delivery/slippage/early exercise
 * costs are deliberately outside this conditional mathematical bound.
 */
export function payoffProfile(legs: readonly PayoffLeg[], entryCash: number, fixedExpiryCosts = 0): PayoffProfile {
  validatePayoffLegs(legs);
  const strikes = [...new Set(legs.map((leg) => leg.strike))].sort((a, b) => a - b);
  const prices = [0, ...strikes];
  const points = prices.map((price) => ({ price, pnl: expiryPnl(legs, price, entryCash, fixedExpiryCosts) }));
  const upsideSlope = finite(legs.reduce((sum, leg) => sum + (leg.optionType === 'call' ? leg.quantity * leg.multiplier : 0), 0));
  const lossBounded = upsideSlope >= 0;
  const profitBounded = upsideSlope <= 0;
  const roots: number[] = [];
  const zeroRanges: PayoffProfile['zeroRanges'] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i]; const b = points[i + 1];
    if (zero(a.pnl) && zero(b.pnl)) zeroRanges.push({ from: a.price, to: b.price });
    else if (zero(a.pnl)) roots.push(a.price);
    else if (zero(b.pnl)) roots.push(b.price);
    else if (Math.sign(a.pnl) !== Math.sign(b.pnl)) roots.push(a.price - a.pnl * (b.price - a.price) / (b.pnl - a.pnl));
  }
  const last = points[points.length - 1];
  if (upsideSlope === 0) {
    if (zero(last.pnl)) zeroRanges.push({ from: last.price, to: null });
  } else {
    const root = last.price - last.pnl / upsideSlope;
    if (root >= last.price) roots.push(root);
  }
  const merged: PayoffProfile['zeroRanges'] = [];
  for (const range of zeroRanges) {
    const previous = merged[merged.length - 1];
    if (previous && previous.to === range.from) previous.to = range.to;
    else merged.push({ ...range });
  }
  const breakevens = [...new Set(roots.filter((root) => !merged.some((range) => root >= range.from && (range.to === null || root <= range.to)))
    .map((root) => Math.round(root * 1e6) / 1e6))].sort((a, b) => a - b);
  return {
    maxLoss: lossBounded ? roundCash(Math.max(0, -Math.min(...points.map((point) => point.pnl)))) : null,
    bestPnl: profitBounded ? Math.max(...points.map((point) => point.pnl)) : null,
    lossBounded, profitBounded, breakevens, zeroRanges: merged, entryCash, fixedExpiryCosts, upsideSlope, points,
  };
}

/** Buy-to-close short legs at ask, sell-to-close long legs at bid. This is a
 * quotation-based liquidation reference, never an executed or realized P&L.
 */
export function closeCashAtTouch(legs: readonly QuotedLeg[], feePerContract: number): number {
  return entryCashAtTouch(legs.map((leg) => ({ ...leg, quantity: -leg.quantity })), feePerContract).net;
}
