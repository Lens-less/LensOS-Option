import { describe, expect, it } from 'vitest';
import oracle from './payoff-oracle.json';
import { closeCashAtTouch, entryCashAtTouch, expiryPnl, payoffProfile, validatePayoffLegs, type PayoffLeg } from './payoff';

describe('exact expiry arithmetic against unchanged Python structures.py', () => {
  it('matches 60 independently generated structures, costs, quantities and multipliers', () => {
    for (const row of oracle) {
      const legs = row.legs as PayoffLeg[];
      const profile = payoffProfile(legs, row.entryCash, row.fixedExpiryCosts);
      expect(profile.maxLoss).toBeCloseTo(row.expected.max_loss!, 6);
      expect(profile.bestPnl).toBeCloseTo(row.expected.max_profit!, 6);
      expect(profile.breakevens).toEqual(row.expected.breakevens);
      expect(profile.lossBounded).toBe(row.expected.loss_is_bounded);
      for (const point of row.points) expect(expiryPnl(legs, point.price, row.entryCash, row.fixedExpiryCosts)).toBeCloseTo(point.pnl, 6);
    }
  });
  it('uses sell bid / buy ask and pays entry or close cash fees exactly once', () => {
    const template = oracle[0].legs[0] as PayoffLeg;
    const legs = [{ ...template, instrument: 'long', quantity: 2, multiplier: 100, bid: 2, ask: 3 },
      { ...template, instrument: 'short', quantity: -2, multiplier: 100, bid: 5, ask: 6 }];
    expect(entryCashAtTouch(legs, 1)).toEqual({gross:400,fees:4,net:396});
    expect(closeCashAtTouch(legs, 1)).toBe(-804);
  });
  it('detects an unbounded call tail and exact zero-profit ranges', () => {
    const template = { ...(oracle[0].legs[0] as PayoffLeg), optionType:'call' as const, strike:100, multiplier:1, quantity:-1 };
    expect(payoffProfile([template],10).maxLoss).toBeNull();
    expect(payoffProfile([template],10).breakevens).toEqual([110]);
    const flat=payoffProfile([{...template,quantity:1}],0);
    expect(flat.zeroRanges).toEqual([{from:0,to:100}]);
    expect(flat.breakevens).toEqual([]);
  });
  it('rejects inconsistent contract definitions, duplicate legs and unsafe numbers', () => {
    const legs=oracle[0].legs as PayoffLeg[];
    for (const change of [{currency:'USD'},{multiplier:999},{expiry:'2027-02-15T08:00:00Z'},
      {expiry:'2027-01-15 08:00:00'},{exercise:'american'},{settlement:'inverse'},{quantity:0},{strike:NaN}]) {
      expect(() => validatePayoffLegs([legs[0],{...legs[1],...change} as PayoffLeg])).toThrow();
    }
    expect(() => validatePayoffLegs([legs[0],legs[0]])).toThrow();
    expect(() => expiryPnl(legs,Infinity,10)).toThrow();
    expect(() => expiryPnl(legs,-1,10)).toThrow();
    expect(() => payoffProfile(legs,1e308)).toThrow();
  });
});
