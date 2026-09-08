import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { ResearchReport } from "../../contracts";
import { ResearchWorkbench } from "./ResearchWorkbench";

// The workbench persists filter/selection state into the URL via
// `history.replaceState`. jsdom's `window.location` survives across `it`
// blocks within one test file, so every test must start from a clean URL or
// an earlier test's selection/filter state would leak into the next render.
beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

const baseReport: ResearchReport = {
  schema_version: "research_report.v1",
  generated_at: "2026-07-26T10:00:00Z",
  action: "RESEARCH_ONLY",
  mode: "research_only",
  effective_mode: "research_only",
  data_status: {
    status: "validated",
    source: "deribit_live:https://www.deribit.com",
    validated: true,
    market_data_age_sec: 4,
    quality_gate: {
      thresholds: { market_data_max_age_sec: 60 },
    },
  },
  strategy_research: {
    schema_version: "strategy_research.v1",
    execution_allowed: false,
    analysis: {
      market: { spot_usd: 65_000 },
    },
  },
  full_system_surface: {
    release_readiness: { status: "NO-GO" },
  },
};

const frontierCandidate = {
  candidate_id: "BTC-7AUG26-73000-C:naked",
  structure_type: "naked_short_call",
  action: "RESEARCH_ONLY",
  score_status: "UNCALIBRATED_RESEARCH_ONLY",
  ranking_score: 0.82,
  executable_credit_usdc: 400,
  ev_after_cost_usdc: 55.5,
  dte_days: 13.9,
  model_delta: -0.12,
  kill_conditions: [],
  dominated_by: null,
  losing_axes: [],
  edge_components: {
    theta_efficiency: { value: 1.2, unit: "usdc/day", status: "OK" },
  },
  absolute_ev: {
    status: "validated",
    ev_after_cost_usdc: 55.5,
    entry_credit_usdc: 400,
    expected_payout_usdc: 340,
    modelled_fees_usdc: { total_usdc: 4.5 },
    authoritative_sample_size: 42,
    sample_size_basis: "independent_non_overlapping_windows",
    evidence_class: "paper_reconciled",
  },
};

const dominatedCandidate = {
  candidate_id: "BTC-7AUG26-71000-C:naked",
  structure_type: "naked_short_call",
  action: "RESEARCH_ONLY",
  score_status: "UNCALIBRATED_RESEARCH_ONLY",
  ranking_score: 0.41,
  executable_credit_usdc: 360,
  ev_after_cost_usdc: null,
  dte_days: 13.9,
  model_delta: 0.087,
  kill_conditions: ["NO_VALIDATED_PATH_RISK"],
  dominated_by: "BTC-7AUG26-73000-C:naked",
  losing_axes: ["liquidity_cost_ratio"],
  edge_components: null,
};

const rejectedCandidate = {
  candidate_id: "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
  structure_type: "call_credit_spread",
  action: "REJECT",
  executable_credit_usdc: 162.65,
  ev_after_cost_usdc: null,
  dte_days: 13.9,
  model_delta: 0.087,
  kill_conditions: ["UNCALIBRATED_SCORE_MODEL"],
  dominated_by: null,
  losing_axes: [],
  edge_components: null,
};

function validatedReport(): ResearchReport {
  return {
    ...baseReport,
    ev_candidate_scanner: {
      status: "validated",
      score_status: "UNCALIBRATED_RESEARCH_ONLY",
      ranking_basis: {
        method: "dominance_frontier",
        tie_break_order: ["theta_efficiency", "liquidity_cost_ratio"],
        dominance_scope: "same_expiry_same_structure",
        absolute_ev_available: true,
      },
      dominated_explanations: [
        {
          candidate_id: "BTC-7AUG26-71000-C:naked",
          dominated_by: "BTC-7AUG26-73000-C:naked",
          losing_axes: ["liquidity_cost_ratio"],
        },
      ],
      ranked_candidates: [
        frontierCandidate,
        dominatedCandidate,
        rejectedCandidate,
      ],
    },
  } as unknown as ResearchReport;
}

function blockedReport(): ResearchReport {
  return {
    ...baseReport,
    ev_candidate_scanner: {
      status: "blocked",
      reason_code: "SUSPECT_PRICE_DIVERGENCE",
      ranked_candidates: [],
    },
  } as unknown as ResearchReport;
}

function publishedWorkbenchReport(): ResearchReport {
  const report = validatedReport();
  const scanner = report.ev_candidate_scanner as {
    ranked_candidates?: Array<Record<string, unknown>>;
  };
  const rankedCandidates = scanner.ranked_candidates ?? [];
  const first = rankedCandidates[0] ?? {};
  rankedCandidates[0] = {
    ...first,
    absolute_ev: {
      ...(first.absolute_ev as Record<string, unknown> | undefined),
      execution_sensitivity: {
        ev_after_cost_usdc: {
          sell_at_bid: 42.1,
          sell_at_mid: 55.5,
          buy_at_mid: -12.2,
          buy_at_ask: -20.4,
        },
      },
    },
    margin_snapshot: {
      reference_margin_usdc: 1234.5,
    },
  };
  return {
    ...report,
    runtime_context: {
      mode: "published",
      replay: false,
      evaluation_clock: "2026-07-26T10:00:00Z",
    },
    publish_edition: {
      cadence: "daily",
      captured_at: "2026-07-26T10:00:00Z",
      published_at: "2026-07-26T10:00:02Z",
      next_expected_at: "2026-07-27T10:00:00Z",
      stale_after: "2026-07-28T10:00:00Z",
    },
    full_system_surface: {
      ...report.full_system_surface,
      release_gates: [
        { name: "research_publication", status: "GO", satisfied: true },
        { name: "execution_authorization", status: "NO-GO", satisfied: false },
      ],
    },
  } as unknown as ResearchReport;
}

function missingDteReport(): ResearchReport {
  const report = validatedReport();
  const scanner = report.ev_candidate_scanner as {
    ranked_candidates?: Array<Record<string, unknown>>;
  };
  const rankedCandidates = scanner.ranked_candidates ?? [];
  rankedCandidates[1] = {
    ...(rankedCandidates[1] ?? {}),
    dte_days: null,
  };
  return report;
}

function selectRowByCreditText(creditText: string): void {
  const cell = screen.getByText(creditText);
  const rowElement = cell.closest("tr");
  if (!rowElement) {
    throw new Error(`could not find a table row for ${creditText}`);
  }
  fireEvent.click(rowElement);
}

function renderWorkbench(report: ResearchReport) {
  return render(
    <ResearchWorkbench
      nowMs={Date.parse("2026-07-26T10:00:04Z")}
      receivedAtMs={Date.parse("2026-07-26T10:00:04Z")}
      report={report}
    />,
  );
}

describe("ResearchWorkbench / scanner status", () => {
  it.each([
    {
      name: "failed market quality",
      dataStatus: {
        ...baseReport.data_status,
        validated: false,
        status: "blocked",
        reason_code: "MARKET_DATA_QUALITY_FAIL",
      },
      reasonCode: "MARKET_DATA_QUALITY_FAIL",
      explanation: "市场快照未通过质量门禁",
    },
    {
      name: "missing market age",
      dataStatus: { ...baseReport.data_status, market_data_age_sec: undefined },
      reasonCode: "MISSING_VALIDATED_MARKET_DATA",
      explanation: "无法核验行情时效",
    },
  ])("withdraws candidates, open detail, and combination risk for $name", ({
    dataStatus, reasonCode, explanation,
  }) => {
    const receivedAtMs = Date.parse("2026-07-26T10:00:04Z");
    const report: ResearchReport = {
      ...validatedReport(),
      combination_risk: { status: "evaluated", members: [], book: {} },
    };
    const { rerender } = render(
      <ResearchWorkbench nowMs={receivedAtMs} receivedAtMs={receivedAtMs} report={report} />,
    );
    selectRowByCreditText("$400");
    expect(screen.getByRole("heading", { name: frontierCandidate.candidate_id })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "这几个一起做会怎样" })).toBeInTheDocument();

    rerender(
      <ResearchWorkbench
        nowMs={receivedAtMs}
        receivedAtMs={receivedAtMs}
        report={{ ...report, data_status: dataStatus }}
      />,
    );

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: frontierCandidate.candidate_id })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "这几个一起做会怎样" })).not.toBeInTheDocument();
    expect(document.querySelector("fieldset.screener-controls")).toHaveAttribute("disabled");
    expect(screen.getByRole("status")).toHaveTextContent(reasonCode);
    expect(screen.getByRole("main")).toHaveTextContent(explanation);
    expect(screen.queryByText(/MARKET_DATA_AGE_EXCEEDED|PUBLISHED_EDITION_STALE|快照超过新鲜度上限/)).not.toBeInTheDocument();
  });

  it.each(["live", "replay", "demo", "published"] as const)(
    "expires %s candidates with the matching freshness explanation",
    (mode) => {
      const receivedAtMs = Date.parse("2026-07-26T10:00:04Z");
      const report: ResearchReport = {
        ...validatedReport(),
        runtime_context: {
          mode: mode === "demo" ? "replay" : mode,
          replay: mode === "replay" || mode === "demo",
          demo_mode: mode === "demo",
          ...(mode === "published" ? { evaluation_clock: "2026-07-26T10:00:00Z" } : {}),
        },
        ...(mode === "published" ? {
          publish_edition: {
            cadence: "daily",
            captured_at: "2026-07-26T10:00:00Z",
            published_at: "2026-07-26T10:00:02Z",
            next_expected_at: "2026-07-26T10:00:30Z",
            stale_after: "2026-07-26T10:01:00Z",
          },
          full_system_surface: {
            ...baseReport.full_system_surface,
            release_gates: [
              { name: "research_publication", status: "GO", satisfied: true },
              { name: "execution_authorization", status: "NO-GO", satisfied: false },
            ],
          },
        } : {}),
      };
      const { rerender } = render(
        <ResearchWorkbench nowMs={receivedAtMs} receivedAtMs={receivedAtMs} report={report} />,
      );
      expect(screen.getByText("$400")).toBeInTheDocument();

      rerender(
        <ResearchWorkbench
          nowMs={Date.parse("2026-07-26T10:01:00Z")}
          receivedAtMs={receivedAtMs}
          report={report}
        />,
      );

      expect(screen.queryByText("$400")).not.toBeInTheDocument();
      expect(document.querySelector("fieldset.screener-controls")).toHaveAttribute("disabled");
      const needed = screen.getByRole("region", { name: "需要补齐什么" });
      if (mode === "published") {
        expect(needed).toHaveTextContent("PUBLISHED_EDITION_STALE");
        expect(needed).toHaveTextContent("公开版已超过发布时效上限");
      } else {
        expect(needed).toHaveTextContent("MARKET_DATA_AGE_EXCEEDED");
        expect(needed).toHaveTextContent("快照超过新鲜度上限");
        expect(screen.queryByText(/PUBLISHED_EDITION_STALE/)).not.toBeInTheDocument();
        expect(screen.queryByText(/公开版已超过/)).not.toBeInTheDocument();
      }
    },
  );

  it("separates normal demo states from evidence to collect and retains raw codes", () => {
    renderWorkbench({
      ...blockedReport(),
      reason_codes: [
        "REGIME_ROLLING_HISTORY_INSUFFICIENT",
        "REGIME_TRUST_EVIDENCE_NOT_PROMOTED",
        "NO_OPEN_POSITIONS",
        "SIMULATION_NOT_REQUESTED",
        "PRIMARY_REGIME_RANGE",
        "UNKNOWN_DEMO_BLOCKER",
      ],
    });

    const needed = screen.getByRole("region", { name: "需要补齐什么" });
    expect(needed).toHaveTextContent("REGIME_ROLLING_HISTORY_INSUFFICIENT");
    expect(needed).toHaveTextContent("REGIME_TRUST_EVIDENCE_NOT_PROMOTED");
    expect(needed).toHaveTextContent("系统持续观察");
    expect(needed).toHaveTextContent("UNKNOWN_DEMO_BLOCKER");
    expect(needed).not.toHaveTextContent("NO_OPEN_POSITIONS");
    expect(needed).not.toHaveTextContent("SIMULATION_NOT_REQUESTED");
    expect(needed).not.toHaveTextContent("PRIMARY_REGIME_RANGE");

    const normal = screen.getByRole("region", { name: "正常状态说明", hidden: true });
    expect(normal).toHaveTextContent("NO_OPEN_POSITIONS");
    expect(normal).toHaveTextContent("SIMULATION_NOT_REQUESTED");
    expect(normal).toHaveTextContent("PRIMARY_REGIME_RANGE");
    expect(normal).not.toHaveTextContent("未收录的阻断原因");
    expect(screen.getByText("正常状态（3 项）")).toBeInTheDocument();
  });

  it("presents repair commands as conditional steps without promising validation", () => {
    renderWorkbench({
      ...blockedReport(),
      reason_codes: ["MARKET_DATA_QUALITY_FAIL", "MISSING_VALIDATED_PATH_RISK"],
    });

    const needed = screen.getByRole("region", { name: "需要补齐什么" });
    expect(needed).toHaveTextContent("可尝试的操作");
    expect(needed).toHaveTextContent("不能保证消除所有阻断");
    expect(needed).toHaveTextContent("无法修复报价缺失、倒挂或单位错误");
    expect(needed).toHaveTextContent("完成后仍须重新生成报告并通过校验");
  });

  it("shows a blocked state, keeps controls disabled, and offers no reset CTA", () => {
    renderWorkbench(blockedReport());

    // Exactly one role=status region exists in the blocked branch (the
    // debounced result-count region only renders once the scanner validates).
    const blocked = screen.getByRole("status");
    expect(blocked).toHaveTextContent("候选筛选证据未通过验证");
    expect(blocked).toHaveTextContent("SUSPECT_PRICE_DIVERGENCE");
    expect(screen.queryByRole("button", { name: /重置筛选/ })).not.toBeInTheDocument();

    const fieldset = document.querySelector("fieldset.screener-controls");
    expect(fieldset).toHaveAttribute("disabled");
  });

  it("treats an empty filtered result differently from a blocked scanner", () => {
    const { container } = renderWorkbench(validatedReport());

    // Narrow the minimum credit filter so far above every candidate's
    // executable credit that nothing can possibly remain.
    const minCreditInput = screen.getByLabelText("最低可成交信用（USDC）");
    fireEvent.change(minCreditInput, { target: { value: "999999" } });

    const emptyState = container.querySelector(".screener-empty-state");
    expect(emptyState).not.toBeNull();
    expect(emptyState).toHaveTextContent("当前筛选条件排除了全部候选");
    expect(emptyState).toHaveTextContent("0 / 3");

    // Unlike the blocked state, an empty filtered result offers a reset CTA
    // and the filter controls remain interactive (not disabled).
    const resetCta = screen.getByRole("button", { name: "重置筛选条件" });
    expect(resetCta).toBeInTheDocument();
    const fieldset = document.querySelector("fieldset.screener-controls");
    expect(fieldset).not.toHaveAttribute("disabled");

    fireEvent.click(resetCta);
    expect(container.querySelector(".screener-empty-state")).toBeNull();
  });
});

describe("ResearchWorkbench / candidate detail", () => {
  it("does not draw a naked put as a short call when signed structure legs are missing", () => {
    const report = validatedReport();
    const putId = "BTC-7AUG26-61000-P:naked";
    report.ev_candidate_scanner = {
      status: "validated",
      ranked_candidates: [{ ...frontierCandidate, candidate_id: putId, structure_type: "naked_short_put" }],
    };
    renderWorkbench(report);
    selectRowByCreditText("$400");

    const detail = screen.getByRole("region", { name: "候选详情" });
    expect(within(detail).queryByRole("img", { name: /到期盈亏/ })).not.toBeInTheDocument();
    expect(detail).not.toHaveTextContent("亏损无上限（标的继续上涨）");
    expect(detail).toHaveTextContent("暂时无法绘制到期盈亏图");
  });

  it.each([
    {
      name: "missing entry credit",
      change: {
        executable_credit_usdc: null,
        premium_usdc: null,
        structure_legs: [{ option_type: "call", strike: 73000, quantity: -1 }],
      },
    },
    {
      name: "a malformed explicit leg",
      change: {
        structure_legs: [{ option_type: "unknown", strike: 73000, quantity: -1 }],
      },
    },
    {
      name: "legs with different expiries",
      change: {
        structure_legs: [
          { option_type: "call", strike: 73000, quantity: -1, expiry_date: "2026-08-07" },
          { option_type: "call", strike: 77000, quantity: 1, expiry_date: "2026-08-14" },
        ],
      },
    },
  ])("withholds the payoff for $name without substituting a legacy curve", ({ change }) => {
    const report = validatedReport();
    report.ev_candidate_scanner = {
      status: "validated",
      ranked_candidates: [{ ...frontierCandidate, ...change }],
    };
    window.history.replaceState(null, "", `/?candidate=${encodeURIComponent(frontierCandidate.candidate_id)}`);
    renderWorkbench(report);

    const detail = screen.getByRole("region", { name: "候选详情" });
    expect(within(detail).queryByRole("img", { name: /到期盈亏/ })).not.toBeInTheDocument();
    expect(detail).toHaveTextContent("暂时无法绘制到期盈亏图");
  });

  it("still draws a naked put when its signed leg and credit are provided", () => {
    const report = validatedReport();
    report.ev_candidate_scanner = {
      status: "validated",
      ranked_candidates: [{
        ...frontierCandidate,
        candidate_id: "BTC-7AUG26-61000-P:naked",
        structure_type: "naked_short_put",
        structure_legs: [{ option_type: "put", strike: 61000, quantity: -1, expiry_date: "2026-08-07" }],
      }],
    };
    renderWorkbench(report);
    selectRowByCreditText("$400");

    const detail = screen.getByRole("region", { name: "候选详情" });
    expect(within(detail).getByRole("img", { name: /到期盈亏/ })).toBeInTheDocument();
    expect(detail).not.toHaveTextContent("亏损无上限");
  });

  it("renders a dominance explanation naming the winner and the losing axes", () => {
    renderWorkbench(validatedReport());
    selectRowByCreditText("$360");

    const heading = screen.getByRole("heading", {
      name: "BTC-7AUG26-71000-C:naked",
    });
    expect(heading).toBeInTheDocument();
    expect(document.activeElement).toBe(heading);

    const dominatedNotice = screen.getByText(/该候选被/);
    expect(dominatedNotice).toHaveTextContent("BTC-7AUG26-73000-C:naked");
    expect(dominatedNotice).toHaveTextContent("流动性成本比");
  });

  it("shows an explicit no-validated-path-evidence state instead of 0 or blank", () => {
    renderWorkbench(validatedReport());
    selectRowByCreditText("$360");

    expect(
      screen.getByText(/尚无已验证的路径风险证据/),
    ).toBeInTheDocument();
    // It must never render as a bare zero (scoped to the EV breakdown block
    // itself, since the payoff chart legitimately draws a "$0" axis tick).
    const evBlock = document.querySelector(".absolute-ev-block");
    expect(evBlock).not.toBeNull();
    expect(within(evBlock as HTMLElement).queryByText("$0")).not.toBeInTheDocument();
    expect(
      within(evBlock as HTMLElement).queryByText(/^\$0(\.\d+)?$/),
    ).not.toBeInTheDocument();
  });

  it("renders the full credit-minus-payout-minus-fees breakdown once EV is validated", () => {
    renderWorkbench(validatedReport());
    selectRowByCreditText("$400");

    expect(screen.getByText("入场信用")).toBeInTheDocument();
    expect(screen.getByText(/预期支出/)).toBeInTheDocument();
    expect(screen.getByText(/42/)).toBeInTheDocument();
  });
});

describe("ResearchWorkbench / safety framing", () => {
  it("states the execution boundary on this surface without a release NO-GO banner", () => {
    // The workbench is where ranked candidates and expected values are read,
    // so the boundary must be visible here, not only on the evidence console.
    renderWorkbench(validatedReport());

    expect(screen.getByText("执行边界")).toBeInTheDocument();
    expect(screen.getByText("RESEARCH_ONLY · NO_TRADE")).toBeInTheDocument();
    expect(screen.queryByText("外部发布授权")).not.toBeInTheDocument();
  });

  it("labels the score as uncalibrated so a rank is not read as a verdict", () => {
    renderWorkbench(validatedReport());

    expect(screen.getByText("排序口径")).toBeInTheDocument();
    expect(
      screen.getAllByText("研究排序值（未校准）").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: "研究排序值（未校准）" }),
    ).toBeInTheDocument();
  });
});

describe("ResearchWorkbench / no trading semantics", () => {
  it("never exposes an order, trade, or execution control", () => {
    renderWorkbench(validatedReport());
    selectRowByCreditText("$400");

    expect(
      screen.queryByRole("button", { name: /下单|交易|执行/ }),
    ).not.toBeInTheDocument();
  });

  it("never renders a contract/lot-size count", () => {
    renderWorkbench(validatedReport());
    const main = screen.getByRole("main");
    expect(within(main).queryByText(/\d+\s*张/)).not.toBeInTheDocument();
    expect(within(main).queryByText("手数")).not.toBeInTheDocument();
    expect(within(main).queryByText("数量")).not.toBeInTheDocument();
  });

  it("hides margin and execution detail when the workbench is reused in published mode", () => {
    renderWorkbench(publishedWorkbenchReport());
    selectRowByCreditText("$400");

    expect(screen.queryByText("保证金参考")).not.toBeInTheDocument();
    expect(screen.queryByText("卖出 @ 买价")).not.toBeInTheDocument();
    expect(screen.queryByText("买入 @ 卖价")).not.toBeInTheDocument();
  });

  it("never lets a filter change promote the REJECT-tier candidate into a visible research tier", () => {
    renderWorkbench(validatedReport());
    const minCreditInput = screen.getByLabelText("最低可成交信用（USDC）");
    fireEvent.change(minCreditInput, { target: { value: "0" } });

    // The rejected tier is hidden by default, so this asserts the default
    // rather than reaching for the checkbox to turn it off.
    const rejectTierToggle = screen.getByRole("checkbox", { name: "已拒绝" });
    expect(rejectTierToggle).not.toBeChecked();

    // With the REJECT tier hidden, its credit value must not appear in the
    // table no matter how permissive every other slider is.
    expect(screen.queryByText("$162.65")).not.toBeInTheDocument();

    // And turning it on shows the row without changing its tier.
    fireEvent.click(rejectTierToggle);
    expect(screen.getByText("$162.65")).toBeInTheDocument();
    expect(screen.getAllByText("已拒绝").length).toBeGreaterThan(0);
  });
});

describe("ResearchWorkbench / keyboard and sparse data", () => {
  it("keeps detail controls focused while the clock or report refreshes", () => {
    const now = Date.parse("2026-07-26T10:00:04Z");
    const { rerender } = renderWorkbench(validatedReport());
    selectRowByCreditText("$400");
    const close = screen.getByRole("button", { name: "关闭候选详情" });
    close.focus();

    rerender(
      <ResearchWorkbench nowMs={now + 1000} receivedAtMs={now} report={validatedReport()} />,
    );

    expect(close).toHaveFocus();
  });

  it("closes details with Escape and returns keyboard focus to the selected row", () => {
    renderWorkbench(validatedReport());
    const row = screen.getByText("$400").closest("tr") as HTMLTableRowElement;
    fireEvent.click(row);
    fireEvent.keyDown(screen.getByRole("heading", { name: frontierCandidate.candidate_id }), {
      key: "Escape",
    });

    expect(screen.queryByRole("region", { name: "候选详情" })).not.toBeInTheDocument();
    expect(row).toHaveFocus();
    expect(new URLSearchParams(window.location.search).has("candidate")).toBe(false);
  });

  it("withdraws a selected candidate excluded by filters without stealing filter focus", () => {
    renderWorkbench(validatedReport());
    selectRowByCreditText("$400");
    const input = screen.getByLabelText("最低可成交信用（USDC）");
    input.focus();
    fireEvent.change(input, { target: { value: "500" } });

    expect(screen.queryByRole("region", { name: "候选详情" })).not.toBeInTheDocument();
    expect(input).toHaveFocus();
    expect(new URLSearchParams(window.location.search).has("candidate")).toBe(false);
  });

  it("restores a usable focus target when refresh removes the selected candidate", () => {
    const now = Date.parse("2026-07-26T10:00:04Z");
    const { rerender } = renderWorkbench(validatedReport());
    selectRowByCreditText("$400");
    const next = validatedReport();
    next.ev_candidate_scanner = { status: "validated", ranked_candidates: [dominatedCandidate] };

    rerender(<ResearchWorkbench nowMs={now} receivedAtMs={now} report={next} />);

    expect(screen.queryByRole("region", { name: "候选详情" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "候选筛选" })).toHaveFocus();
    expect(new URLSearchParams(window.location.search).has("candidate")).toBe(false);
  });

  it("restores filters and selection on browser history navigation", () => {
    renderWorkbench(validatedReport());
    window.history.pushState(null, "", `/?view=workbench&minCredit=380&candidate=${encodeURIComponent(frontierCandidate.candidate_id)}&source=shared#results`);
    fireEvent.popState(window);

    expect(screen.getByLabelText("最低可成交信用（USDC）")).toHaveValue(380);
    expect(screen.queryByText("$360")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: frontierCandidate.candidate_id })).toHaveFocus();

    window.history.pushState(null, "", "/?view=workbench&source=shared#results");
    fireEvent.popState(window);
    expect(screen.getByLabelText("最低可成交信用（USDC）")).toHaveValue(null);
    expect(screen.getByText("$360")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "候选详情" })).not.toBeInTheDocument();
    expect(window.location.hash).toBe("#results");
    expect(new URLSearchParams(window.location.search).get("source")).toBe("shared");
  });

  it("clears selected URLs and candidate-derived controls when the scanner is blocked", () => {
    window.history.replaceState(null, "", `/?candidate=${encodeURIComponent(frontierCandidate.candidate_id)}`);
    const report = validatedReport();
    report.ev_candidate_scanner = {
      status: "blocked",
      reason_code: "SUSPECT_PRICE_DIVERGENCE",
      ranked_candidates: [frontierCandidate],
    };
    renderWorkbench(report);

    expect(screen.queryByRole("region", { name: "候选详情" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "naked_short_call" })).not.toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).has("candidate")).toBe(false);
  });

  it("supports keyboard row navigation and enter-to-open on the screener table", () => {
    renderWorkbench(validatedReport());

    const rows = document.querySelectorAll<HTMLTableRowElement>(
      ".candidate-screener-table tbody tr",
    );
    expect(rows).toHaveLength(2);
    rows[0]?.focus();

    fireEvent.keyDown(rows[0] as HTMLTableRowElement, { key: "ArrowDown" });
    expect(document.activeElement).toBe(rows[1]);

    fireEvent.keyDown(rows[1] as HTMLTableRowElement, { key: "Enter" });
    expect(
      screen.getByRole("heading", { name: "BTC-7AUG26-71000-C:naked" }),
    ).toBeInTheDocument();
  });

  it("renders missing DTE as unavailable without breaking rows that still have data", () => {
    renderWorkbench(missingDteReport());

    expect(screen.getByText("13.9 天")).toBeInTheDocument();
    expect(screen.getByText("不可用")).toBeInTheDocument();
  });
});
