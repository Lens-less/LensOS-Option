import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DecisionDeskApp } from "./DecisionDeskApp";
import { buildDeskResearchCopy, CompareWorkspace } from "./CompareWorkspace";
import { DiscoverWorkspace } from "./DiscoverWorkspace";
import { observeComparisonFixture, observeDeskFixture, observeReviewFixture } from "./observeFixtures";
import { OBSERVE_STORAGE_KEY } from "./observeStore";
import type { DecisionDesk, DeskAsset, DeskComparison, DeskCriteria, DeskMode, DeskScenario } from "./types";

const clipboard = vi.fn(async (_text: string) => undefined);

function comparisonFor(desk: DecisionDesk, ids: string[], scenario: DeskScenario): DeskComparison {
  const comparison = observeComparisonFixture(desk);
  return { ...comparison, scenario: { iv_shift_points: scenario.iv_shift_points, price_change_pct: scenario.price_change_pct,
    time_days: scenario.time_days }, members: comparison.members.filter((member) => ids.includes(member.candidate_id)) };
}

function readyApp(desk = observeDeskFixture()) {
  // The API uses sort_keys=True. Equal DTO values must remain equal after wire serialization.
  desk.criteria = { dte_max: desk.criteria.dte_max, dte_min: desk.criteria.dte_min,
    max_spread_ratio: desk.criteria.max_spread_ratio, max_width_pct: desk.criteria.max_width_pct, viewpoint: desk.criteria.viewpoint };
  const loadDesk = vi.fn(async (_asset: DeskAsset, _criteria: DeskCriteria, _mode: DeskMode) => desk);
  const loadComparison = vi.fn(async (_snapshot: string, ids: string[], scenario: DeskScenario, _analysis: string) => comparisonFor(desk, ids, scenario));
  const reviewRecord = vi.fn(async (_record: { desk: DecisionDesk; candidate_id: string }) => observeReviewFixture(desk));
  render(<DecisionDeskApp loadDesk={loadDesk} loadComparison={loadComparison} reviewRecord={reviewRecord} />);
  return { desk, loadDesk, loadComparison, reviewRecord };
}

async function chooseAndCompare(): Promise<void> {
  await screen.findAllByRole("button", { name: "加入比较" });
  const buttons = screen.getAllByRole("button", { name: "加入比较" });
  fireEvent.click(buttons[0]); fireEvent.click(buttons[1]);
  fireEvent.click(screen.getByRole("button", { name: "比较这些结构" }));
  await screen.findByRole("img", { name: /条件到期损益/ });
}

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, "", "/?view=desk&mode=demo");
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: clipboard } });
});
afterEach(() => { vi.restoreAllMocks(); clipboard.mockClear(); localStorage.clear(); });

describe("DecisionDesk core journey", () => {
  it("discovers complete structures, compares one analysis, copies and saves immutable research, then reviews the same legs", async () => {
    const { desk, loadDesk, loadComparison, reviewRecord } = readyApp();
    await screen.findAllByRole("button", { name: "加入比较" });
    expect(screen.queryByText("筛选有变更，应用后重新发现结构。")).not.toBeInTheDocument();
    const conditions = screen.getByText("到期与报价条件").closest("details")!;
    expect(conditions).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("到期与报价条件"));
    // jsdom does not apply the native details toggle; the exact fields still retain the default guards.
    expect(screen.getByLabelText("最短到期天数")).toHaveAttribute("min", "0");
    await chooseAndCompare();
    expect(loadDesk).toHaveBeenCalledWith("BTC", desk.criteria, "demo");
    expect(loadComparison).toHaveBeenCalledWith(desk.snapshot_id, desk.candidates.map((candidate) => candidate.candidate_id),
      { price_change_pct: 0, time_days: 0, iv_shift_points: 0 }, desk.analysis_id);
    expect(screen.getByText(/使用本次结构比例与双边报价，按列明入场费与标准交割费计算/)).toBeVisible();
    fireEvent.click(screen.getByRole("radio", { name: /1 · 牛市看跌信用价差/ }));
    fireEvent.change(screen.getByRole("textbox", { name: /选择依据/ }), { target: { value: "先观察保护翼和报价时效" } });
    fireEvent.click(screen.getByRole("button", { name: "复制研究复核" }));
    await waitFor(() => expect(clipboard).toHaveBeenCalledTimes(1));
    expect(clipboard.mock.calls[0][0]).toContain(`ANALYSIS ID: ${desk.analysis_id}`);
    expect(clipboard.mock.calls[0][0]).toContain("SYNTHETIC OFFLINE EXAMPLE");
    expect(clipboard.mock.calls[0][0]).toContain("RESEARCH_ONLY / execution_allowed=false");
    fireEvent.click(screen.getByRole("button", { name: "保存到本地观察" }));
    expect(await screen.findByRole("heading", { name: "保留当时的判断，复核同一组合" })).toBeVisible();
    const saved = JSON.parse(localStorage.getItem(OBSERVE_STORAGE_KEY)!);
    expect(saved.records[0].desk.snapshot_id).toBe(desk.snapshot_id);
    expect(saved.records[0].comparison.analysis_id).toBe(desk.analysis_id);
    expect(saved.records[0].note).toBe("先观察保护翼和报价时效");
    fireEvent.click(screen.getByRole("button", { name: "复核同一组合" }));
    await screen.findByText("已取得同一合约的新报价");
    expect(reviewRecord.mock.calls[0][0]).toMatchObject({ candidate_id: desk.candidates[0].candidate_id, desk });
    const reviewed = JSON.parse(localStorage.getItem(OBSERVE_STORAGE_KEY)!);
    expect(reviewed.records[0].desk).toEqual(saved.records[0].desk);
    expect(reviewed.reviews).toHaveLength(1);
  });

  it("invalidates model results and ignores an older in-flight result when the common scenario changes", async () => {
    const desk = observeDeskFixture();
    let resolvePending: ((comparison: DeskComparison) => void) | undefined;
    const loadComparison = vi.fn(async (_snapshot: string, ids: string[], scenario: DeskScenario, _analysis: string) => comparisonFor(desk, ids, scenario));
    render(<DecisionDeskApp loadDesk={async () => desk} loadComparison={loadComparison} reviewRecord={async () => observeReviewFixture(desk)} />);
    await chooseAndCompare();
    fireEvent.click(screen.getByRole("radio", { name: /1 · 牛市看跌信用价差/ }));
    loadComparison.mockImplementationOnce(() => new Promise((resolve) => { resolvePending = resolve; }));
    fireEvent.change(screen.getByRole("slider", { name: "标的价格变化百分比" }), { target: { value: "5" } });
    expect(screen.getByText("情景已调整，请重新计算共同情景。")).toBeVisible();
    expect(screen.queryByRole("img", { name: /条件到期损益/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存到本地观察" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "计算共同情景" }));
    fireEvent.change(screen.getByRole("slider", { name: "IV平移百分点" }), { target: { value: "4" } });
    await act(async () => { resolvePending!(comparisonFor(desk, desk.candidates.map((candidate) => candidate.candidate_id),
      { price_change_pct: 5, time_days: 0, iv_shift_points: 0 })); });
    expect(screen.queryByRole("img", { name: /条件到期损益/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存到本地观察" })).toBeDisabled();
  });

  it("applies source mode and viewpoint explicitly and clears prior quotes after a failed refresh", async () => {
    const { desk, loadDesk } = readyApp();
    await screen.findAllByRole("button", { name: "加入比较" });
    fireEvent.click(screen.getByRole("button", { name: "偏多" }));
    expect(loadDesk).toHaveBeenCalledTimes(1);
    expect(screen.getByText("筛选有变更，应用后重新发现结构。")).toBeVisible();
    loadDesk.mockImplementationOnce(async () => ({ ...desk, criteria: { ...desk.criteria, viewpoint: "bullish" } }));
    fireEvent.click(screen.getByRole("button", { name: "应用筛选" }));
    await waitFor(() => expect(loadDesk).toHaveBeenCalledTimes(2));
    await screen.findAllByRole("button", { name: "加入比较" });
    expect(loadDesk.mock.calls[1]).toEqual(["BTC", { ...desk.criteria, viewpoint: "bullish" }, "demo"]);
    loadDesk.mockRejectedValueOnce(new Error("upstream failure"));
    fireEvent.click(screen.getByRole("button", { name: "读取公开行情" }));
    expect(await screen.findByRole("heading", { name: "这次数据尚未读取成功" })).toBeVisible();
    expect(screen.queryByText(desk.candidates[0].legs[0].instrument_name)).not.toBeInTheDocument();
    expect(loadDesk.mock.calls[2][2]).toBe("live");
    fireEvent.click(screen.getByRole("button", { name: /观察复盘/ }));
    expect(screen.getByRole("heading", { name: "从一个看清楚的结构开始" })).toBeVisible();
  });

  it("enforces same expiry and max three selections without hiding complete legs", () => {
    const desk = observeDeskFixture();
    const third = { ...structuredClone(desk.candidates[0]), candidate_id: "fixture-third" };
    const fourth = { ...structuredClone(desk.candidates[1]), candidate_id: "fixture-fourth" };
    const other = { ...structuredClone(desk.candidates[1]), candidate_id: "fixture-other-expiry", expiry_date: "2099-12-31" };
    desk.candidates.push(third, fourth, other);
    const props = { desk, criteria: desk.criteria, selectedIds: [desk.candidates[0].candidate_id], busy: false, nowMs: Date.now(),
      onCriteriaChange: vi.fn(), onApply: vi.fn(), onSelect: vi.fn(), onCompare: vi.fn() };
    const { rerender } = render(<DiscoverWorkspace {...props} />);
    const additions = screen.getAllByRole("button", { name: "加入比较" });
    expect(additions[0]).toBeEnabled();
    expect(additions[3]).toBeDisabled();
    expect(screen.getAllByText(desk.candidates[0].legs[0].instrument_name).length).toBeGreaterThan(0);
    rerender(<DiscoverWorkspace {...props} selectedIds={[desk.candidates[0].candidate_id, desk.candidates[1].candidate_id, third.candidate_id]} />);
    expect(screen.getAllByRole("button", { name: "加入比较" }).every((button) => button.hasAttribute("disabled"))).toBe(true);
    expect(screen.getAllByRole("button", { name: "移出比较" })).toHaveLength(3);
  });

  it("pauses saved/copy actions at the per-structure recheck deadline before the overall desk expires, while preserving the historical chart", () => {
    const desk = observeDeskFixture();
    desk.candidates[0].recheck_at = new Date(Date.now() - 1).toISOString();
    const comparison = comparisonFor(desk, desk.candidates.map((candidate) => candidate.candidate_id),
      { price_change_pct: 0, time_days: 0, iv_shift_points: 0 });
    render(<CompareWorkspace desk={desk} candidates={desk.candidates} comparison={comparison} scenario={comparison.scenario} busy={false} nowMs={Date.now()}
      onScenarioChange={vi.fn()} onRunComparison={vi.fn()} onRemove={vi.fn()} onSave={vi.fn()} onBack={vi.fn()} />);
    fireEvent.click(screen.getByRole("radio", { name: /1 · 牛市看跌信用价差/ }));
    expect(screen.getByText("当前比较已暂停")).toBeVisible();
    expect(screen.getByRole("img", { name: /条件到期损益/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "保存到本地观察" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "复制研究复核" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "更新情景比较" })).toBeDisabled();
  });

  it("copies exact quote precision, fees, source, identities and finite qualification without an order or profit claim", () => {
    const desk = observeDeskFixture();
    desk.candidates[0].legs[0].bid = 300.000000000123;
    const comparison = observeComparisonFixture(desk);
    const copy = buildDeskResearchCopy(desk, desk.candidates[0], comparison);
    for (const expected of ["BID 300.000000000123", "SCENARIO ID: fixture-scenario", "CAPTURED AT:", "VALID UNTIL:",
      "STRUCTURE RATIO 1", "CONTRACT SIZE 1", "EXCLUDES ENTRY, EXIT AND DELIVERY FEES", "RECHECK:", "不是推荐手数或仓位"])
      expect(copy).toContain(expected);
    expect(copy).not.toContain("win_rate");
  });
});
