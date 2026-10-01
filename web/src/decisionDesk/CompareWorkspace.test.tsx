import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CompareWorkspace, type CompareWorkspaceProps } from "./CompareWorkspace";
import { observeComparisonFixture, observeDeskFixture } from "./observeFixtures";
import type { DeskCandidate } from "./types";

const originalMatchMedia = window.matchMedia;
const writeText = vi.fn(async (_text: string) => undefined);

function setWideLayout(wide: boolean): void {
  Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn((query: string) => ({
    matches: query.includes("min-width") ? wide : !wide, media: query,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })) });
}

function comparisonProps(): CompareWorkspaceProps {
  const desk = observeDeskFixture();
  const condor: DeskCandidate = {
    ...structuredClone(desk.candidates[0]), candidate_id: "fixture-condor", structure: "IRON_CONDOR", viewpoint: "range",
    legs: [...structuredClone(desk.candidates[0].legs), ...structuredClone(desk.candidates[1].legs)],
    economics: { ...desk.candidates[0].economics, entry_cash: 1100, entry_fees: 4, net_entry_cash: 1096,
      mid_to_touch_drag: 100, option_payoff_loss_bound: 3900 },
  };
  desk.candidates.push(condor);
  const comparison = observeComparisonFixture(desk);
  return { desk, candidates: desk.candidates, comparison, scenario: comparison.scenario,
    busy: false, nowMs: Date.now(), onScenarioChange: vi.fn(), onRunComparison: vi.fn(),
    onRemove: vi.fn(), onSave: vi.fn(), onBack: vi.fn() };
}

beforeEach(() => {
  setWideLayout(false);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
});
afterEach(() => {
  Object.defineProperty(window, "matchMedia", { configurable: true, value: originalMatchMedia });
  writeText.mockClear();
});

describe("CompareWorkspace decision focus", () => {
  it("places shared inputs and aligned outcomes before the chart and disclosure, while retaining exact evidence behind mobile disclosures", async () => {
    const props = comparisonProps();
    const { container, rerender } = render(<CompareWorkspace {...props} />);
    const controls = container.querySelector(".desk-scenario-controls")!;
    const table = screen.getByRole("table", { name: "共同情景下的结构参考 · USDC" });
    const chart = screen.getByRole("img", { name: /条件到期损益/ });
    const decision = container.querySelector(".desk-decision-panel")!;
    const evidence = container.querySelector(".desk-comparison-evidence")!;
    const before = (left: Node, right: Node) => (left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect(before(controls, table)).toBe(true);
    expect(before(table, chart)).toBe(true);
    expect(before(chart, decision)).toBe(true);
    expect(before(decision, evidence)).toBe(true);
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    const disclosures = container.querySelectorAll<HTMLDetailsElement>(".desk-comparison-leg-details");
    expect(disclosures).toHaveLength(3);
    expect([...disclosures].every((item) => !item.open)).toBe(true);
    await act(async () => { disclosures[2].open = true; fireEvent(disclosures[2], new Event("toggle")); });
    const exactLegs = within(disclosures[2]).getAllByRole("listitem");
    expect(exactLegs).toHaveLength(4);
    props.candidates[2].legs.forEach((leg) => expect(within(disclosures[2]).getByText(leg.instrument_name)).toBeVisible());
    expect(within(disclosures[2]).getByText("fixture-fees")).toBeVisible();
    rerender(<CompareWorkspace {...props} nowMs={props.nowMs + 1000} />);
    expect(disclosures[2]).toHaveAttribute("open");
  });

  it("copies all four protected legs without requiring expanded disclosures and retains research-only source, fees and clocks", async () => {
    const props = comparisonProps();
    const { container } = render(<CompareWorkspace {...props} />);
    fireEvent.click(screen.getByRole("radio", { name: /3 · 铁鹰区间结构/ }));
    fireEvent.click(screen.getByRole("button", { name: "复制研究复核" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const copy = writeText.mock.calls[0][0];
    props.candidates[2].legs.forEach((leg) => expect(copy).toContain(`LEG: ${leg.side} ${leg.instrument_name}`));
    for (const token of ["execution_allowed=false", "SYNTHETIC OFFLINE EXAMPLE", "QUOTED AT ", "CONTRACT SIZE 1",
      "ENTRY FEES: 4", "EXCLUDES ENTRY, EXIT AND DELIVERY FEES", "RECHECK AT:"])
      expect(copy).toContain(token);
    expect([...container.querySelectorAll<HTMLDetailsElement>(".desk-comparison-leg-details")].every((item) => !item.open)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "保存到本地观察" }));
    expect(props.onSave).toHaveBeenCalledWith("fixture-condor", "");
  });

  it("keeps unavailable model evidence explicit and pauses historical results after the candidate deadline", () => {
    const props = comparisonProps();
    props.comparison!.members[2].stress = null;
    props.comparison!.members[2].stress_reason = "缺少报价 IV，未估算退出值";
    props.candidates[0].recheck_at = new Date(props.nowMs - 1).toISOString();
    render(<CompareWorkspace {...props} />);
    const row = screen.getByRole("row", { name: /模型压力损益/ });
    expect(within(row).getByText("不可计算")).toBeVisible();
    expect(within(row).getByText("缺少报价 IV，未估算退出值")).toBeVisible();
    expect(screen.getByText("当前比较已暂停")).toBeVisible();
    fireEvent.click(screen.getByRole("radio", { name: /3 · 铁鹰区间结构/ }));
    expect(screen.getByRole("button", { name: "复制研究复核" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存到本地观察" })).toBeDisabled();
    expect(screen.getByRole("img", { name: /条件到期损益/ })).toBeVisible();
  });

  it("keeps desktop quote evidence expanded and binds the time control to the exact frozen expiry limit and actual scenario", () => {
    setWideLayout(true);
    const props = comparisonProps();
    props.candidates.forEach((candidate) => {
      candidate.expiration_timestamp = Date.parse(props.desk.generated_at) + 13.99999 * 86_400_000;
      candidate.dte_days = 14;
    });
    props.scenario = { ...props.scenario, time_days: 13 };
    props.scenarioNotice = "所选到期日已调整：经过时间从 20 天改为 13 天。";
    const { container } = render(<CompareWorkspace {...props} />);
    expect([...container.querySelectorAll<HTMLDetailsElement>(".desk-comparison-leg-details")].every((item) => item.open)).toBe(true);
    const time = screen.getByRole("slider", { name: "经过时间天数" });
    expect(time).toHaveAttribute("max", "13");
    expect(time).toHaveValue("13");
    expect(screen.getByText("13 天")).toBeVisible();
    expect(screen.getByText(props.scenarioNotice)).toBeVisible();
  });
});
