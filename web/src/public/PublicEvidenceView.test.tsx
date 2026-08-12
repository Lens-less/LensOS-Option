import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ResearchReport, VrpStatusPoint } from "../contracts";
import { PublicEvidenceView } from "./PublicEvidenceView";
import { PublicShell } from "./PublicShell";
import type { PublicReleaseSummary } from "./loadPublicReport";
import type { PublicFreshness } from "./publicModel";

const freshness: PublicFreshness = {
  ageSec: 28_480,
  capturedAt: "2026-08-03T00:00:00Z",
  maxAgeSec: 48 * 60 * 60,
  mode: "published",
  phase: "current",
  publishedAt: "2026-08-03T00:05:00Z",
  staleAfter: "2026-08-05T00:00:00Z",
};

const series: VrpStatusPoint[] = [
  {
    band: "P30-P70",
    dvol_percent: 34.2,
    observed_at: "2024-08-03T08:00:00Z",
    percentile: 0.45,
    rv30_percent: 27.3,
    vrp_percent_points: 6.9,
  },
  {
    band: "P30-P70",
    dvol_percent: 35.5,
    observed_at: "2026-08-01T08:00:00Z",
    percentile: 0.52,
    rv30_percent: 27.3,
    vrp_percent_points: 8.2,
  },
];

function report(): ResearchReport {
  return {
    schema_version: "research_report.v1",
    generated_at: "2026-08-03T00:00:00Z",
    runtime_context: { mode: "published" },
    publish_edition: {
      captured_at: "2026-08-03T00:00:00Z",
      stale_after: "2026-08-05T00:00:00Z",
    },
    data_status: {
      source: "deribit_published_snapshot",
      status: "validated",
      validated: true,
    },
    vrp_status: {
      band: "P30-P70",
      current_dvol_percent: 35.5,
      current_rv30_percent: 27.3,
      current_vrp_percent_points: 8.2,
      percentile: 0.52,
      sample_count: 729,
      series,
      status: "available",
      window_days: 730,
    },
  };
}

function summary(
  change: PublicReleaseSummary["change"],
): PublicReleaseSummary {
  return {
    change,
    schema_version: "public_summary.v1",
    vrp: {
      band: "P30-P70",
      percentile: 0.52,
      vrp_percent_points: 8.2,
    },
  };
}

describe("PublicEvidenceView public truth labels", () => {
  it("shows sanitized exchange-lock evidence and its narrow source", () => {
    const partialLock = report();
    partialLock.event_status = {
      event_score: 0.8,
      exchange_lock_state: "partial",
      macro_calendar_covered: false,
      reason_code: "EXCHANGE_PARTIAL_LOCK",
      scope: "exchange_native_only",
      source: "deribit_public_status",
      source_status: "available",
    };

    render(
      <PublicEvidenceView
        freshness={freshness}
        report={partialLock}
        summary={null}
      />,
    );

    const evidence = screen.getByRole("region", {
      name: "公开事件源与交易所锁定",
    });
    expect(within(evidence).getByText("0.80")).toBeInTheDocument();
    expect(within(evidence).getByText("部分锁定（阻断）")).toBeInTheDocument();
    expect(within(evidence).getByText("EXCHANGE_PARTIAL_LOCK")).toBeInTheDocument();
    expect(
      within(evidence).getByText(
        "Deribit public/status（仅交易所锁定状态，不含宏观事件日历）",
      ),
    ).toBeInTheDocument();
  });

  it("renders unknown public reason codes instead of silently dropping them", () => {
    const unknownReason = report();
    unknownReason.reason_codes = ["UNKNOWN_PUBLIC_BLOCKER"];

    render(
      <PublicEvidenceView
        freshness={freshness}
        report={unknownReason}
        summary={null}
      />,
    );

    expect(screen.getByText("UNKNOWN_PUBLIC_BLOCKER")).toBeInTheDocument();
    expect(screen.getByText("未收录的阻断原因")).toBeInTheDocument();
    expect(screen.getByText(/机器码仍会原样展示/)).toBeInTheDocument();
  });

  it("renders quality-gate advisories on the public evidence surface", () => {
    const fallbackSelection = report();
    fallbackSelection.data_status!.quality_gate = {
      passed: true,
      reason_codes: [],
      advisory_reason_codes: ["SELECTION_POLICY_FALLBACK_USED"],
    };

    render(
      <PublicEvidenceView
        freshness={freshness}
        report={fallbackSelection}
        summary={null}
      />,
    );

    expect(screen.getByText("SELECTION_POLICY_FALLBACK_USED")).toBeInTheDocument();
    expect(screen.getByText("采集使用了选样回退")).toBeInTheDocument();
  });

  it("uses the report's VRP minimum and explains quarantined quotes", () => {
    const constrained = report();
    constrained.vrp_status = {
      minimum_series_sample_count: 1_200,
      reason_code: "INSUFFICIENT_VRP_HISTORY",
      sample_count: 365,
      status: "insufficient_history",
    };
    constrained.data_status!.quality_gate = {
      passed: true,
      summary: {
        invalid_quotes: 2,
        total_quotes: 10,
        valid_quotes: 8,
      },
    };
    constrained.strategy_research = {
      schema_version: "strategy_research.v1",
      analysis: { market: { spot_usd: 63_139.06 } },
    };

    render(
      <PublicEvidenceView
        freshness={freshness}
        report={constrained}
        summary={null}
      />,
    );

    expect(screen.getAllByText(/365 \/ 1,200/)).toHaveLength(2);
    expect(screen.getByText(/2 条未通过质量门的报价已隔离/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("最少 1000");
  });

  it("shows the daily change under the headline without inventing a comparison", () => {
    const { rerender } = render(
      <PublicEvidenceView
        freshness={freshness}
        report={report()}
        summary={summary({
          band_changed: false,
          current_observed_at: "2026-08-01T08:00:00Z",
          prior_observed_at: "2026-07-31T08:00:00Z",
          status: "available",
          vrp_percent_points_delta: 1.320205,
        })}
      />,
    );

    expect(screen.getByText("较昨日 +1.3 pt，仍为中性")).toBeInTheDocument();

    rerender(
      <PublicEvidenceView
        freshness={freshness}
        report={report()}
        summary={summary({
          band_changed: null,
          status: "unavailable",
          vrp_percent_points_delta: null,
        })}
      />,
    );

    expect(screen.getByText("上一观察日对比不可用")).toBeInTheDocument();
  });

  it("derives the disclosed VRP window and metric basis from public data", () => {
    render(
      <PublicEvidenceView freshness={freshness} report={report()} summary={null} />,
    );

    expect(screen.getByText("730 日经验百分位")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "VRP 730 日时序" })).toBeInTheDocument();
    expect(screen.queryByText("三年经验百分位")).not.toBeInTheDocument();
    expect(
      screen.getByText(/DVOL 为 Deribit 前瞻隐含波动率指数/),
    ).toBeInTheDocument();
    expect(screen.getByText(/RV30 为向后 30 日已实现波动率/)).toBeInTheDocument();
    expect(
      screen.getByText(/源时间戳与日结边界以公开 API 字段为准/),
    ).toBeInTheDocument();
  });

  it("uses readable hours and states the capture and evaluation clock semantics", () => {
    render(
      <PublicEvidenceView freshness={freshness} report={report()} summary={null} />,
    );

    expect(screen.getByText("数据采集距今")).toBeInTheDocument();
    expect(screen.getByText("距今 7.9 小时")).toBeInTheDocument();
    expect(screen.getByText("发布失效边界")).toBeInTheDocument();
    expect(screen.getByText("48 小时")).toBeInTheDocument();
    expect(
      screen.getByText("以快照采集时间为起点，按浏览器当前时钟评估。"),
    ).toBeInTheDocument();
  });

  it("places signal validation before the final limitations act", () => {
    const { container } = render(
      <PublicEvidenceView
        freshness={freshness}
        report={report()}
        signalSection={<section id="signal">信号验证</section>}
        summary={null}
      />,
    );

    const acts = Array.from(
      container.querySelectorAll("#surface-main > [id]"),
      (element) => element.id,
    );
    expect(acts.indexOf("signal")).toBeGreaterThanOrEqual(0);
    expect(acts.indexOf("signal")).toBeLessThan(acts.indexOf("limitations"));
  });
});

describe("PublicShell static navigation", () => {
  it("keeps all five acts on one evidence page and names the static reload action honestly", () => {
    render(
      <PublicShell
        freshness={freshness}
        onRefresh={vi.fn()}
        refreshing={false}
        report={report()}
        view="evidence"
      >
        <main>内容</main>
      </PublicShell>,
    );

    const expectedLinks = {
      "现在贵不贵": "./index.html#vrp",
      "曲面贵在哪里": "./index.html#surface",
      "卖它值不值": "./index.html#framework",
      "这套排序灵不灵": "./index.html#signal",
      "凭什么信": "./index.html#limitations",
    };
    for (const [name, href] of Object.entries(expectedLinks)) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    }
    expect(document.body.innerHTML).not.toContain("?view=signal");
    expect(screen.getByRole("button", { name: "重新读取静态快照" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新" })).not.toBeInTheDocument();
  });
});
