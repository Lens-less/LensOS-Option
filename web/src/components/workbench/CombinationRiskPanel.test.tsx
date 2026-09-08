import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ResearchReport } from "../../contracts";
import { VIZ } from "../viz/tokens";
import { CombinationRiskPanel } from "./CombinationRiskPanel";

const expiry = "2026-09-25";
const nextExpiry = "2026-10-30";

function legs(date: string = expiry): Array<Record<string, unknown>> {
  return [
    { option_type: "call", strike: 71_000, quantity: -1, expiry_date: date },
    { option_type: "call", strike: 73_000, quantity: 1, expiry_date: date },
  ];
}

function fixture(): {
  members: Array<Record<string, unknown>>;
  candidates: Array<Record<string, unknown>>;
} {
  return {
    members: [
      { candidate_id: "first", expiry_date: expiry, credit_usdc: 100 },
      { candidate_id: "second", expiry_date: expiry, credit_usdc: 200 },
    ],
    candidates: [
      { candidate_id: "first", structure_legs: legs() },
      { candidate_id: "second", structure_legs: legs() },
    ],
  };
}

function renderCombination(
  data: ReturnType<typeof fixture>,
  book: Record<string, unknown> = {},
) {
  const report: ResearchReport = {
    schema_version: "research_report.v1",
    ev_candidate_scanner: { ranked_candidates: data.candidates },
    combination_risk: { status: "evaluated", members: data.members, book },
  };
  return render(<CombinationRiskPanel report={report} spotUsdc={70_000} />);
}

function expectNoJointCurve(container: HTMLElement) {
  expect(
    screen.queryByRole("img", { name: "组合与各成员的到期盈亏曲线" }),
  ).not.toBeInTheDocument();
  expect(container.querySelectorAll(`path[stroke="${VIZ.subject}"]`)).toHaveLength(0);
}

describe("CombinationRiskPanel payoff completeness", () => {
  it("draws both members and their joint curve when every input is complete", () => {
    const { container } = renderCombination(fixture());
    expect(
      screen.getByRole("img", { name: "组合与各成员的到期盈亏曲线" }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll(`path[stroke="${VIZ.context}"]`)).toHaveLength(2);
    expect(container.querySelectorAll(`path[stroke="${VIZ.subject}"]`)).toHaveLength(1);
    expect(screen.queryByText(/无法绘制联合曲线/)).not.toBeInTheDocument();
  });

  it("does not relabel one surviving member as the whole combination", () => {
    const data = fixture();
    delete data.candidates[1].structure_legs;
    const { container } = renderCombination(data);
    expectNoJointCurve(container);
    expect(screen.getByText(/1 个成员.*不完整或不一致/)).toBeInTheDocument();
    expect(container.querySelectorAll(`path[stroke="${VIZ.context}"]`)).toHaveLength(1);
  });

  it.each([undefined, null, NaN, Infinity])(
    "does not replace an unavailable credit (%s) with zero",
    (credit) => {
      const data = fixture();
      data.members[1].credit_usdc = credit;
      const { container } = renderCombination(data);
      expectNoJointCurve(container);
      expect(screen.getByText(/1 个成员.*不完整或不一致/)).toBeInTheDocument();
      expect(container.querySelectorAll(`path[stroke="${VIZ.context}"]`)).toHaveLength(1);
    },
  );

  it("keeps an explicitly zero credit evaluable", () => {
    const data = fixture();
    data.members[1].credit_usdc = 0;
    renderCombination(data);
    expect(
      screen.getByRole("img", { name: "组合与各成员的到期盈亏曲线" }),
    ).toBeInTheDocument();
  });

  it("does not treat two missing expiry dates as a shared settlement date", () => {
    const data = fixture();
    for (const member of data.members) {
      delete member.expiry_date;
    }
    for (const candidate of data.candidates) {
      candidate.structure_legs = legs().map(({ expiry_date: _date, ...leg }) => leg);
    }
    const { container } = renderCombination(data);
    expectNoJointCurve(container);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText(/2 个成员.*不完整或不一致/)).toBeInTheDocument();
  });

  it("keeps complete cross-expiry members separate", () => {
    const data = fixture();
    data.members[1].expiry_date = nextExpiry;
    data.candidates[1].structure_legs = legs(nextExpiry);
    const { container } = renderCombination(data);
    expectNoJointCurve(container);
    expect(screen.getByRole("img", { name: "各成员的到期盈亏曲线" })).toBeInTheDocument();
    expect(screen.getByText(/成员分属不同到期日/)).toBeInTheDocument();
    expect(container.querySelectorAll(`path[stroke="${VIZ.context}"]`)).toHaveLength(2);
  });

  it("rejects a member whose leg expiry disagrees with its declared expiry", () => {
    const data = fixture();
    data.candidates[1].structure_legs = [legs()[0], legs(nextExpiry)[1]];
    const { container } = renderCombination(data);
    expectNoJointCurve(container);
    expect(screen.getByText(/1 个成员.*不完整或不一致/)).toBeInTheDocument();
    expect(container.querySelectorAll(`path[stroke="${VIZ.context}"]`)).toHaveLength(1);
  });

  it.each([
    { option_type: "unknown" },
    { option_type: undefined },
    { strike: NaN },
    { strike: -1 },
    { quantity: 0 },
    { expiry_date: "" },
  ])("rejects an entire member when one supplied leg is invalid: %j", (override) => {
    const data = fixture();
    data.candidates[1].structure_legs = [legs()[0], { ...legs()[1], ...override }];
    const { container } = renderCombination(data);
    expectNoJointCurve(container);
    expect(container.querySelectorAll(`path[stroke="${VIZ.context}"]`)).toHaveLength(1);
    expect(screen.getByText(/1 个成员.*不完整或不一致/)).toBeInTheDocument();
  });
});

describe("CombinationRiskPanel maximum-loss evidence", () => {
  it("identifies an evaluated unbounded loss instead of a cross-expiry limitation", () => {
    renderCombination(fixture(), {
      joint_terminal_risk: { status: "evaluated", loss_is_bounded: false, max_loss_usdc: null },
      max_loss_upper_bound_usdc: null,
      loss_is_bounded: false,
    });
    expect(screen.getByText("无上限", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("含无界成员", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("跨到期日不可计算", { exact: true })).not.toBeInTheDocument();
  });

  it("identifies a cross-expiry joint limitation without inventing unbounded members", () => {
    renderCombination(fixture(), {
      joint_terminal_risk: { status: "not_jointly_evaluable", max_loss_usdc: null },
      max_loss_upper_bound_usdc: null,
      loss_is_bounded: true,
      unbounded_members: [],
    });
    expect(screen.getByText("跨到期日不可计算", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("证据不可用", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("含无界成员", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("无上限", { exact: true })).not.toBeInTheDocument();
  });

  it("keeps both missing risk values unavailable when no evidence explains them", () => {
    renderCombination(fixture());
    expect(screen.getAllByText("证据不可用", { exact: true })).toHaveLength(2);
    expect(screen.queryByText("跨到期日不可计算", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("含无界成员", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("无上限", { exact: true })).not.toBeInTheDocument();
  });

  it("accepts an explicit unbounded-member list as upper-bound evidence", () => {
    renderCombination(fixture(), { unbounded_members: ["first"] });
    expect(screen.getByText("含无界成员", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("证据不可用", { exact: true })).toBeInTheDocument();
  });
});
