import { describe, expect, it } from "vitest";

import type { ResearchReport } from "../../contracts";
import {
  readReasonCode,
  resolveExchangeEventEvidence,
} from "./reasonCodes";

function eventReport(
  eventScore: number | null,
  eventFeed: Record<string, unknown> | null,
): ResearchReport {
  return {
    schema_version: "research_report.v1",
    data_status: {
      feed_coverage: {
        feeds: {
          events: eventFeed,
        },
      },
    },
    strategy_research: {
      schema_version: "strategy_research.v1",
      analysis: { market: { event_score: eventScore } },
    },
  };
}

const currentEventFeed = {
  freshness_status: "fresh",
  reason_code: null,
  scope: "exchange_native_only",
  source_endpoint: "public/status",
  status: "available",
};

describe("exchange event evidence readings", () => {
  it.each([
    [0, "normal", "0.00", "EXCHANGE_NO_ACTIVE_LOCKS", false],
    [0.8, "partial", "0.80", "EXCHANGE_PARTIAL_LOCK", true],
    [1, "full", "1.00", "EXCHANGE_FULL_LOCK", true],
  ] as const)(
    "distinguishes exchange lock score %s as %s",
    (score, state, scoreLabel, reasonCode, blocked) => {
      const reading = resolveExchangeEventEvidence(
        eventReport(score, currentEventFeed),
      );

      expect(reading.state).toBe(state);
      expect(reading.scoreLabel).toBe(scoreLabel);
      expect(reading.reasonCode).toBe(reasonCode);
      expect(reading.blocked).toBe(blocked);
      expect(reading.sourceLabel).toContain("Deribit public/status");
      expect(reading.sourceLabel).toContain("不含宏观事件日历");
    },
  );

  it("keeps missing, stale, and non-canonical event evidence fail closed", () => {
    const missing = resolveExchangeEventEvidence(
      eventReport(0, {
        freshness_status: "unknown",
        reason_code: "EVENTS_MISSING",
        scope: null,
        source_endpoint: null,
        status: "missing",
      }),
    );
    const stale = resolveExchangeEventEvidence(
      eventReport(0, {
        ...currentEventFeed,
        freshness_status: "stale",
        reason_code: "EVENTS_FEED_STALE",
        status: "blocked",
      }),
    );
    const nonCanonical = resolveExchangeEventEvidence(
      eventReport(0.5, currentEventFeed),
    );

    expect(missing).toMatchObject({
      blocked: true,
      reasonCode: "EVENTS_MISSING",
      scoreLabel: "不可用",
      state: "unknown",
    });
    expect(stale).toMatchObject({
      blocked: true,
      reasonCode: "EVENTS_FEED_STALE",
      scoreLabel: "不可用",
      state: "unknown",
    });
    expect(nonCanonical).toMatchObject({
      blocked: true,
      reasonCode: "EVENT_SCORE_NOT_EXCHANGE_LOCK_STATE",
      scoreLabel: "不可用",
      state: "unknown",
    });
  });
});

describe("reason-code readings", () => {
  it("does not hard-code the VRP minimum and never drops unknown codes", () => {
    const insufficient = readReasonCode("INSUFFICIENT_VRP_HISTORY");
    const unknown = readReasonCode("UNKNOWN_PUBLIC_BLOCKER");

    expect(insufficient.detail).toContain("报告声明的最少有效读数");
    expect(insufficient.detail).not.toContain("1000");
    expect(unknown.title).toBe("未收录的阻断原因");
    expect(unknown.detail).toContain("机器码仍会原样展示");
  });
});
