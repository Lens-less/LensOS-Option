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
  it("states the release authorization and execution boundary on this surface", () => {
    // The workbench is where ranked candidates and expected values are read,
    // so the boundary must be visible here, not only on the evidence console.
    renderWorkbench(validatedReport());

    expect(screen.getByText("外部发布授权")).toBeInTheDocument();
    expect(screen.getByText("NO-GO")).toBeInTheDocument();
    expect(screen.getByText("执行边界")).toBeInTheDocument();
    expect(screen.getByText("RESEARCH_ONLY · NO_TRADE")).toBeInTheDocument();
  });

  it("labels the score as uncalibrated so a rank is not read as a verdict", () => {
    renderWorkbench(validatedReport());

    expect(screen.getByText("打分状态")).toBeInTheDocument();
    expect(
      screen.getAllByText("UNCALIBRATED_RESEARCH_ONLY").length,
    ).toBeGreaterThan(0);
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
