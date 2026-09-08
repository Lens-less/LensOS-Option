import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  demoMasqueradingLiveSurface,
  noTradeBriefFixture,
  staleSurface,
  strategyBriefFixture,
  watchOnlyBriefFixture,
} from "./strategyBriefFixtures";
import {
  buildStrategyCombinationCopy,
  deriveStrategyBriefAction,
  projectStrategyBriefForSurface,
  validateStrategyBrief,
  type StrategyBrief,
} from "./strategyBrief";

describe("validateStrategyBrief", () => {
  it("accepts the Python canonical golden without dropping exact fields", () => {
    const golden = JSON.parse(
      readFileSync(
        resolve(
          process.cwd(),
          "../tests/fixtures/strategy_brief/golden_strategy_brief_v1.json",
        ),
        "utf8",
      ),
    ) as unknown;

    const brief = validateStrategyBrief(golden);

    expect(brief.brief_id).toBe((golden as { brief_id: string }).brief_id);
    expect(brief.strategies[0].expiry_date).toBe("2026-09-25");
    expect(brief.strategies[0].history.scope?.structure_type).toBe(
      "BEAR_CALL_CREDIT_SPREAD",
    );
    expect(brief.evidence_summary.surface?.source_kind).toBe("fallback");
    expect(brief.strategies[0].entry.minimum_net_credit).toBe(298);
    expect(brief.strategies[0].entry.cost_breakdown.settlement_reserve).toBe(40);
    expect(brief.strategies[0].risk.max_loss_per_unit).toBe(3742);
    expect(brief.strategies[0].risk.breakevens).toEqual([128258]);
    expect(brief.strategies.every((strategy) => strategy.recommendation_status === "WATCH")).toBe(true);
  });

  it("accepts the canonical fixture", () => {
    const brief = validateStrategyBrief(strategyBriefFixture);

    expect(brief.schema_version).toBe("strategy_brief.v1");
    expect(brief.strategies).toHaveLength(1);
    expect(brief.execution_allowed).toBe(false);
  });

  it("enforces one-unit legs and null safety", () => {
    expect(() =>
      validateStrategyBrief({
        ...strategyBriefFixture,
        strategies: [
          {
            ...strategyBriefFixture.strategies[0],
            legs: [{ ...strategyBriefFixture.strategies[0].legs[0], quantity: 2 }],
          },
        ],
      }),
    ).toThrow(/exactly 1/i);

    expect(() =>
      validateStrategyBrief({
        ...watchOnlyBriefFixture,
        strategies: [
          {
            ...watchOnlyBriefFixture.strategies[0],
            history: {
              ...watchOnlyBriefFixture.strategies[0].history,
              win_rate: 0.55,
            },
          },
        ],
      }),
    ).toThrow(/history metrics must be null/i);
  });

  it.each([
    ["gross credit presented as net", (brief: StrategyBrief) => { brief.strategies[0].entry.minimum_net_credit = 400; }, /net entry credit/],
    ["settlement reserve omitted from risk", (brief: StrategyBrief) => { brief.strategies[0].risk.max_loss_per_unit = 4635; }, /loss budget/],
    ["settlement reserve omitted from breakeven", (brief: StrategyBrief) => { brief.strategies[0].risk.breakevens = [125365]; }, /breakevens/],
    ["negative costs", (brief: StrategyBrief) => { brief.strategies[0].entry.cost_breakdown.entry_fees = -1; }, /non-negative/],
    ["missing costs", (brief: StrategyBrief) => { Object.assign(brief.strategies[0].entry, { cost_breakdown: undefined }); }, /cost_breakdown/],
    ["incomplete exact legs", (brief: StrategyBrief) => { Object.assign(brief.strategies[0].legs[0], { strike: undefined }); }, /exact strategy legs/],
    ["unverified recommendation", (brief: StrategyBrief) => { brief.strategies[0].recommendation_status = "RECOMMENDED"; }, /remain WATCH/],
    ["invented delivery bound", (brief: StrategyBrief) => { Object.assign(brief.strategies[0].risk, { delivery_fee_upper_bound_verified: true }); }, /delivery fee/],
    ["BTC premiums mixed with USD strikes", (brief: StrategyBrief) => {
      brief.strategies[0].entry.currency = "BTC";
      brief.strategies[0].risk.currency = "BTC";
      brief.strategies[0].legs.forEach((leg) => { leg.premium_currency = "BTC"; });
    }, /USD or USDC/],
  ] as const)("rejects %s", (_name, mutate, expected) => {
    const brief = structuredClone(strategyBriefFixture);
    mutate(brief);
    expect(() => validateStrategyBrief(brief)).toThrow(expected);
  });
});

describe("surface projection", () => {
  it("derives action from cards", () => {
    expect(deriveStrategyBriefAction(strategyBriefFixture.strategies)).toBe(
      "WATCH",
    );
    expect(deriveStrategyBriefAction(watchOnlyBriefFixture.strategies)).toBe(
      "WATCH",
    );
    expect(deriveStrategyBriefAction(noTradeBriefFixture.strategies)).toBe(
      "NO_TRADE",
    );
  });

  it("suppresses stale or masquerading live surfaces", () => {
    expect(
      projectStrategyBriefForSurface(strategyBriefFixture, staleSurface).action,
    ).toBe("NO_TRADE");
    expect(
      projectStrategyBriefForSurface(
        strategyBriefFixture,
        demoMasqueradingLiveSurface,
      ).action,
    ).toBe("NO_TRADE");
  });

  it("fails closed when presentation provenance is omitted", () => {
    expect(projectStrategyBriefForSurface(strategyBriefFixture).action).toBe(
      "NO_TRADE",
    );
  });
});

describe("copy recipe", () => {
  it("reuses the canonical copy text", () => {
    expect(
      buildStrategyCombinationCopy(strategyBriefFixture.strategies[0]),
    ).toContain("RESEARCH_ONLY / MANUAL REVIEW REQUIRED");
  });
});
