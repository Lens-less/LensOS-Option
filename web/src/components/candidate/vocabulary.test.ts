import { describe, expect, it } from "vitest";

import { money, signed, signedMoney, instrumentOf } from "./format";
import { TIER_LABELS, tierLabel, tierTone } from "./vocabulary";

/**
 * The workbench and the side panel each used to carry their own labels, and two
 * of the three tiers disagreed: `RESEARCH_ONLY` read "仅研究" in one and
 * "仅供研究" in the other, `REJECT` read "已拒绝" and "已剔除". Same
 * server-assigned tier, same report, same person switching between two views —
 * with no way to tell whether the different wording meant a different thing.
 */
describe("one tier vocabulary", () => {
  it("names every tier exactly once", () => {
    expect(Object.keys(TIER_LABELS).sort()).toEqual([
      "REJECT",
      "RESEARCH_ONLY",
      "REVIEW",
    ]);
    expect(new Set(Object.values(TIER_LABELS)).size).toBe(3);
  });

  it("resolves a tier the same way from either surface", () => {
    expect(tierLabel("RESEARCH_ONLY")).toBe("仅研究");
    expect(tierLabel("REJECT")).toBe("已拒绝");
  });

  it("does not invent a label for an unknown tier", () => {
    expect(tierLabel("SOMETHING_NEW")).toBe("未分类");
    expect(tierTone("SOMETHING_NEW")).toBe("neutral");
  });

  it("keeps the rejected tone distinct from the research tone", () => {
    expect(tierTone("RESEARCH_ONLY")).toBe("safe");
    expect(tierTone("REJECT")).toBe("danger");
  });
});

describe("one number vocabulary", () => {
  it("puts the sign outside the currency symbol", () => {
    // The workbench rendered `$-120` and the side panel `-120.00 USDC`; money
    // that changes shape between two views of one report makes a reader check
    // whether the number changed too.
    expect(money(-120)).toBe("-$120");
    expect(money(120)).toBe("$120");
  });

  it("says what is missing instead of printing a zero-looking dash", () => {
    expect(money(null)).toBe("—");
    expect(signed(null)).toBe("未评估");
  });

  it("always makes a signed quantity explicit", () => {
    expect(signed(1.5, { digits: 1 })).toBe("+1.5");
    expect(signed(-1.5, { digits: 1 })).toBe("-1.5");
    expect(signed(0)).toBe("±0");
    expect(signedMoney(0)).toBe("±$0");
  });

  it("separates the instrument from the structure suffix", () => {
    expect(instrumentOf("BTC-7AUG26-72000-C:naked")).toBe("BTC-7AUG26-72000-C");
    expect(instrumentOf("no-suffix")).toBe("no-suffix");
  });
});
