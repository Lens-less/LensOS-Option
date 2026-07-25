import { describe, expect, it } from "vitest";
import { detectDeribitContext } from "./context";

describe("detectDeribitContext", () => {
  it("prefers an explicit instrument found in the URL", () => {
    const context = detectDeribitContext({
      href: "https://www.deribit.com/options/BTC?instrument=BTC-29AUG26-112000-C",
      nowMs: 1721865600000,
    });

    expect(context.instrument).toBe("BTC-29AUG26-112000-C");
    expect(context.underlying).toBe("BTC");
    expect(context.source).toBe("url");
  });

  it("falls back to a bounded DOM/title scan when the URL has no instrument", () => {
    const context = detectDeribitContext({
      href: "https://www.deribit.com/options/ETH",
      documentTitle: "Deribit Options - ETH-30AUG26-3800-C",
      bodyText: "Selected contract ETH-30AUG26-3800-C mark IV 64.2%",
      nowMs: 1721865600000,
    });

    expect(context.instrument).toBe("ETH-30AUG26-3800-C");
    expect(context.underlying).toBe("ETH");
    expect(context.source).toBe("dom");
  });

  it("keeps the underlying even when no contract can be detected", () => {
    const context = detectDeribitContext({
      href: "https://www.deribit.com/options/SOL",
      nowMs: 1721865600000,
    });

    expect(context.instrument).toBeNull();
    expect(context.underlying).toBe("SOL");
  });
});
