import { describe, expect, it } from "vitest";

import {
  breakevens,
  lossIsBounded,
  parseLegs,
  payoffPoints,
  pnlAt,
  upsideSlope,
  valueAt,
} from "./payoff";

/**
 * These pin the browser mirror of `structures.py` against the same structures
 * the Python tests pin. A payoff curve has to redraw on hover, so the model has
 * to live in the browser; the price of that is that a divergence must fail here
 * rather than reach a chart.
 */
const shortCall = parseLegs([
  { option_type: "call", strike: 110_000, quantity: -1 },
]);
const callSpread = parseLegs([
  { option_type: "call", strike: 110_000, quantity: -1 },
  { option_type: "call", strike: 120_000, quantity: 1 },
]);
const putSpread = parseLegs([
  { option_type: "put", strike: 90_000, quantity: -1 },
  { option_type: "put", strike: 80_000, quantity: 1 },
]);
const condor = parseLegs([
  { option_type: "put", strike: 85_000, quantity: 1 },
  { option_type: "put", strike: 90_000, quantity: -1 },
  { option_type: "call", strike: 110_000, quantity: -1 },
  { option_type: "call", strike: 115_000, quantity: 1 },
]);
const ratio = parseLegs([
  { option_type: "call", strike: 110_000, quantity: 1 },
  { option_type: "call", strike: 120_000, quantity: -2 },
]);

describe("terminal value", () => {
  it("prices a short call above its strike", () => {
    expect(valueAt(shortCall, 105_000)).toBe(0);
    expect(valueAt(shortCall, 120_000)).toBe(-10_000);
  });

  it("caps a call spread at its width", () => {
    expect(valueAt(callSpread, 115_000)).toBe(-5_000);
    expect(valueAt(callSpread, 500_000)).toBe(-10_000);
  });

  it("puts a put spread's obligation on the downside", () => {
    expect(valueAt(putSpread, 95_000)).toBe(0);
    expect(valueAt(putSpread, 85_000)).toBe(-5_000);
    expect(valueAt(putSpread, 0)).toBe(-10_000);
  });

  it("leaves an iron condor whole between its short strikes", () => {
    expect(valueAt(condor, 100_000)).toBe(0);
    expect(valueAt(condor, 112_000)).toBe(-2_000);
    expect(valueAt(condor, 88_000)).toBe(-2_000);
  });
});

describe("risk bounds", () => {
  it("reports a naked short call as unbounded", () => {
    expect(upsideSlope(shortCall)).toBe(-1);
    expect(lossIsBounded(shortCall)).toBe(false);
  });

  it("reports defined-risk structures as bounded", () => {
    expect(lossIsBounded(callSpread)).toBe(true);
    expect(lossIsBounded(putSpread)).toBe(true);
    expect(lossIsBounded(condor)).toBe(true);
  });

  it("reports a ratio short more calls than it is long as unbounded", () => {
    expect(upsideSlope(ratio)).toBe(-1);
    expect(lossIsBounded(ratio)).toBe(false);
  });
});

describe("profit and breakevens", () => {
  it("breaks even at strike plus credit for a short call", () => {
    const points = payoffPoints(shortCall, { entryCash: 500, spot: 100_000 });
    expect(breakevens(points)).toEqual([110_500]);
  });

  it("breaks even inside the wings of a credit spread", () => {
    const points = payoffPoints(callSpread, { entryCash: 2_400, spot: 100_000 });
    expect(breakevens(points)).toEqual([112_400]);
  });

  it("finds a breakeven on each side of an iron condor", () => {
    const points = payoffPoints(condor, { entryCash: 1_500, spot: 100_000 });
    expect(breakevens(points)).toEqual([88_500, 111_500]);
  });

  it("keeps profit capped at the credit when nothing finishes in the money", () => {
    expect(pnlAt(condor, 100_000, 1_500)).toBe(1_500);
  });
});

describe("sampling", () => {
  it("always samples the kinks, so a strike is never stepped over", () => {
    const points = payoffPoints(condor, { entryCash: 1_500, spot: 100_000 });
    for (const strike of [85_000, 90_000, 110_000, 115_000]) {
      expect(points.some((point) => point.spot === strike)).toBe(true);
    }
  });

  it("never samples a negative spot", () => {
    const points = payoffPoints(putSpread, { entryCash: 2_000, spot: 90_000 });
    expect(points.every((point) => point.spot >= 0)).toBe(true);
  });

  it("returns nothing for a structure with no usable legs", () => {
    expect(payoffPoints(parseLegs([]), { entryCash: 0, spot: 1 })).toEqual([]);
    expect(parseLegs([{ option_type: "call", quantity: 1 }])).toEqual([]);
  });
});
