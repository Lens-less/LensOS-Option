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

  it("marks url-derived instruments as the highest confidence tier", () => {
    const context = detectDeribitContext({
      href: "https://www.deribit.com/options/BTC?instrument=BTC-29AUG26-112000-C",
      nowMs: 1721865600000,
    });

    expect(context.confidence).toBe("url");
  });

  it("marks a structured-selector match as dom_structural", () => {
    const context = detectDeribitContext({
      href: "https://www.deribit.com/options/ETH",
      structuralText: "ETH-30AUG26-3800-C",
      nowMs: 1721865600000,
    });

    expect(context.instrument).toBe("ETH-30AUG26-3800-C");
    expect(context.confidence).toBe("dom_structural");
  });

  it("marks a heading/body fallback match as dom_heuristic", () => {
    const context = detectDeribitContext({
      href: "https://www.deribit.com/options/ETH",
      documentTitle: "Deribit Options - ETH-30AUG26-3800-C",
      bodyText: "Selected contract ETH-30AUG26-3800-C mark IV 64.2%",
      nowMs: 1721865600000,
    });

    expect(context.confidence).toBe("dom_heuristic");
  });

  it("demotes dom_structural to dom_heuristic when it disagrees with the URL underlying", () => {
    const context = detectDeribitContext({
      href: "https://www.deribit.com/options/ETH",
      structuralText: "BTC-29AUG26-112000-C",
      nowMs: 1721865600000,
    });

    expect(context.confidence).toBe("dom_heuristic");
    expect(context.instrument).toBe("BTC-29AUG26-112000-C");
    expect(context.underlying).toBe("ETH");
  });

  it("drops a dom_heuristic instrument entirely when it disagrees with the URL underlying", () => {
    const context = detectDeribitContext({
      href: "https://www.deribit.com/options/ETH",
      documentTitle: "Deribit Options - BTC-29AUG26-112000-C",
      nowMs: 1721865600000,
    });

    expect(context.confidence).toBe("none");
    expect(context.instrument).toBeNull();
    expect(context.underlying).toBe("ETH");
  });
});
