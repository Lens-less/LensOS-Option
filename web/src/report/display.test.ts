import { describe, expect, it } from "vitest";

import { formatDvol, formatFractionAsPercent, formatPercent } from "./display";

// The two percent formatters exist so unit semantics are carried by the call
// site instead of guessed from magnitude. These tests pin the regression that
// motivated the split: a 1.5% strike distance must never render as "150.00%".
describe("percent formatting carries unit semantics", () => {
  it("renders already-percent values without rescaling", () => {
    expect(formatPercent(1.5, 2)).toBe("1.50%");
    expect(formatPercent(45.2, 1)).toBe("45.2%");
    expect(formatPercent(null)).toBe("—");
  });

  it("rescales fraction values exactly once", () => {
    expect(formatFractionAsPercent(0.015, 2)).toBe("1.50%");
    expect(formatFractionAsPercent(0.13, 1)).toBe("13.0%");
    expect(formatFractionAsPercent(null)).toBe("—");
  });

  it("renders DVOL points as percentages without rescaling", () => {
    expect(formatDvol(45.23)).toBe("45.23%");
    expect(formatDvol(0.85)).toBe("0.85%");
    expect(formatDvol(null)).toBe("不可用");
  });
});
