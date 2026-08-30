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

    expect(brief.brief_id).toBe(
      "brief:39c3dfb9d44e98b3564edca7ff661d2e0b5bf322d2f0cfe9cd41237e1c3a264c",
    );
    expect(brief.strategies[0].expiry_date).toBe("2026-09-25");
    expect(brief.strategies[0].history.scope?.structure_type).toBe(
      "BEAR_CALL_CREDIT_SPREAD",
    );
    expect(brief.evidence_summary.surface?.source_kind).toBe("fallback");
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
});

describe("surface projection", () => {
  it("derives action from cards", () => {
    expect(deriveStrategyBriefAction(strategyBriefFixture.strategies)).toBe(
      "STRATEGIES_AVAILABLE",
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
