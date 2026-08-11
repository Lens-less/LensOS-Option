import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ResearchReport } from "../../contracts";
import { StrategyFrameworkSection } from "./StrategyFramework";

function report(
  eventScore: number | null,
  eventFeed: Record<string, unknown> | null,
): ResearchReport {
  return {
    schema_version: "research_report.v1",
    action: "RESEARCH_ONLY",
    data_status: {
      validated: true,
      feed_coverage: { feeds: { events: eventFeed } },
    },
    strategy_research: {
      schema_version: "strategy_research.v1",
      advisory_only: true,
      execution_allowed: false,
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

describe("StrategyFrameworkSection exchange event truth", () => {
  it("names the narrow source and never turns missing event evidence into zero", () => {
    const { rerender } = render(
      <StrategyFrameworkSection report={report(0, currentEventFeed)} />,
    );
    const evidence = screen.getByRole("region", {
      name: "事件源与交易所锁定",
    });

    expect(
      within(evidence).getByText(
        "Deribit public/status（仅交易所锁定状态，不含宏观事件日历）",
      ),
    ).toBeInTheDocument();
    expect(within(evidence).getByText("正常（无交易所锁定）")).toBeInTheDocument();
    expect(within(evidence).getByText("0.00")).toBeInTheDocument();
    expect(within(evidence).getByText("EXCHANGE_NO_ACTIVE_LOCKS")).toBeInTheDocument();

    rerender(
      <StrategyFrameworkSection
        report={report(0, {
          freshness_status: "unknown",
          reason_code: "EVENTS_MISSING",
          scope: null,
          source_endpoint: null,
          status: "missing",
        })}
      />,
    );

    const missing = screen.getByRole("region", {
      name: "事件源与交易所锁定",
    });
    expect(within(missing).getByText("未知（按阻断处理）")).toBeInTheDocument();
    expect(within(missing).getByText("不可用")).toBeInTheDocument();
    expect(within(missing).getByText("EVENTS_MISSING")).toBeInTheDocument();
    expect(within(missing).queryByText("0.00")).not.toBeInTheDocument();
  });
});
