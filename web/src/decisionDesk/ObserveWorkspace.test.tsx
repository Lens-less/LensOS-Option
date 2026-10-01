import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ObserveWorkspace } from "./ObserveWorkspace";
import { observeComparisonFixture, observeDeskFixture, observeReviewFixture } from "./observeFixtures";
import { OBSERVE_STORAGE_KEY, appendObservationNote, emptyObserveState, loadObserveState, removeObservation, saveObservation, type ObserveState } from "./observeStore";
import type { DeskReview } from "./types";

function initialState(): ObserveState {
  const desk = observeDeskFixture();
  return saveObservation(emptyObserveState(), {
    desk, candidate_id: desk.candidates[0].candidate_id, comparison: observeComparisonFixture(desk),
    viewpoint: "bullish", note: "等待标的企稳，保护腿不能缺失",
  }).state;
}

function Harness({ initial, review }: { initial: ObserveState; review: (record: ObserveState["records"][number]) => Promise<DeskReview> }): React.JSX.Element {
  const [state, setState] = useState(initial);
  return <ObserveWorkspace state={state} onChange={setState} onReview={review} />;
}

describe("ObserveWorkspace", () => {
  beforeEach(() => localStorage.clear());

  it("explains the private browser empty state without creating an account or backend write", () => {
    const review = vi.fn();
    render(<ObserveWorkspace state={emptyObserveState()} onChange={vi.fn()} onReview={review} />);
    expect(screen.getByRole("heading", { name: "从一个看清楚的结构开始" })).toBeInTheDocument();
    expect(screen.getByText("仅保存在此浏览器 · 无账户同步")).toBeInTheDocument();
    expect(review).not.toHaveBeenCalled();
  });

  it("shows exact original legs, decision and scenario, then stores a separate same-leg review", async () => {
    const state = initialState();
    const original = state.records[0];
    const review = vi.fn(async () => observeReviewFixture(original.desk));
    render(<Harness initial={state} review={review} />);
    expect(screen.getByText(original.desk.candidates[0].legs[0].instrument_name)).toBeInTheDocument();
    expect(screen.getByText("等待标的企稳，保护腿不能缺失")).toBeInTheDocument();
    fireEvent.click(screen.getByText("原始比较假设与证据标识"));
    expect(screen.getByText(/标的变化 -10%/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "复核同一组合" }));
    await screen.findByText("已取得同一合约的新报价");
    expect(screen.getByRole("table")).toHaveAccessibleName("同一合约的双边报价变化 · USDC");
    expect(screen.getByText("325 / 375")).toBeInTheDocument();
    expect(review).toHaveBeenCalledWith(original);
    expect(loadObserveState().state.records[0]).toEqual(original);
    expect(loadObserveState().state.reviews).toHaveLength(1);
  });

  it("preserves the original after missing current quotes and allows a later retry", async () => {
    const state = initialState();
    const review = vi.fn().mockRejectedValueOnce(new Error("network details must not be shown"))
      .mockResolvedValueOnce(observeReviewFixture(state.records[0].desk));
    render(<Harness initial={state} review={review} />);
    fireEvent.click(screen.getByRole("button", { name: "复核同一组合" }));
    await screen.findByText("暂未取得可复核的新报价");
    expect(screen.queryByText(/network details/)).not.toBeInTheDocument();
    expect(screen.getByText(state.records[0].desk.candidates[0].legs[0].instrument_name)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "复核同一组合" }));
    await screen.findByText("已取得同一合约的新报价");
    expect(loadObserveState().state.reviews).toHaveLength(2);
    expect(loadObserveState().state.records).toEqual(state.records);
  });

  it("keeps expired review evidence historical and does not show new quotes as current", async () => {
    const state = initialState();
    const result = observeReviewFixture(state.records[0].desk);
    const evaluatedAtMs = Date.now() - 61_000;
    const evaluatedAt = new Date(evaluatedAtMs).toISOString();
    const validUntil = new Date(evaluatedAtMs + 60_000).toISOString();
    result.reviewed_at = evaluatedAt;
    result.desk!.generated_at = evaluatedAt;
    result.desk!.source.captured_at = evaluatedAt;
    result.desk!.expires_at = validUntil;
    for (const candidate of result.desk!.candidates) {
      candidate.recheck_at = validUntil;
      candidate.dte_days = (candidate.expiration_timestamp - evaluatedAtMs) / 86_400_000;
      for (const leg of candidate.legs) {
        leg.quote_time = evaluatedAt;
        leg.observed_at = evaluatedAt;
      }
    }
    render(<Harness initial={state} review={vi.fn().mockResolvedValue(result)} />);
    fireEvent.click(screen.getByRole("button", { name: "复核同一组合" }));
    await screen.findByText("已到期或本次报价已过复核期限");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(state.records[0].desk.candidates[0].legs[0].instrument_name)).toBeInTheDocument();
    expect(loadObserveState().state.records).toEqual(state.records);
  });

  it("rejects replacement legs returned during a review and keeps the original visible", async () => {
    const state = initialState();
    const result = observeReviewFixture(state.records[0].desk);
    result.desk!.candidates[0].legs[0].instrument_name = "replaced-protective-leg";
    render(<Harness initial={state} review={vi.fn().mockResolvedValue(result)} />);
    fireEvent.click(screen.getByRole("button", { name: "复核同一组合" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("replaced-protective-leg")).not.toBeInTheDocument();
    expect(loadObserveState().state.reviews).toHaveLength(0);
    expect(loadObserveState().state.records).toEqual(state.records);
  });

  it("appends a note and requires the explicit confirm button before deleting its original", async () => {
    const state = initialState();
    render(<Harness initial={state} review={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox", { name: /追加复盘笔记/ }), { target: { value: "价差扩大，等待下次复核" } });
    fireEvent.click(screen.getByRole("button", { name: "保存复盘笔记" }));
    await waitFor(() => expect(loadObserveState().state.reviews).toHaveLength(1));
    expect(loadObserveState().state.records[0].note).toBe("等待标的企稳，保护腿不能缺失");
    fireEvent.click(screen.getByRole("button", { name: "删除此记录" }));
    expect(loadObserveState().state.records).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "保留记录" }));
    expect(loadObserveState().state.records).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "删除此记录" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除记录" }));
    expect(loadObserveState().state).toEqual(emptyObserveState());
    expect(screen.getByRole("heading", { name: "从一个看清楚的结构开始" })).toBeInTheDocument();
  });

  it("explains a stale-page conflict and preserves the unsaved note without restoring deleted private data", () => {
    const state = initialState();
    render(<Harness initial={state} review={vi.fn()} />);
    removeObservation(state, state.records[0].id);
    const note = screen.getByRole("textbox", { name: /追加复盘笔记/ });
    fireEvent.change(note, { target: { value: "旧页面尚未保存的判断" } });
    fireEvent.click(screen.getByRole("button", { name: "保存复盘笔记" }));
    expect(screen.getByRole("alert")).toHaveTextContent("记录已在其他页面更改或删除");
    expect(screen.getByRole("alert")).toHaveTextContent("请重新读取观察列表");
    expect(note).toHaveValue("旧页面尚未保存的判断");
    expect(loadObserveState().state).toEqual(emptyObserveState());
    const deletedStorage = localStorage.getItem(OBSERVE_STORAGE_KEY);
    fireEvent.click(screen.getByRole("button", { name: "重新读取观察" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "从一个看清楚的结构开始" })).toBeInTheDocument();
    expect(localStorage.getItem(OBSERVE_STORAGE_KEY)).toBe(deletedStorage);
  });

  it("reloads newer review events without a write or losing the unsaved note for a surviving record", () => {
    const state = initialState();
    render(<Harness initial={state} review={vi.fn()} />);
    const latest = appendObservationNote(state, state.records[0].id, "另一个页面的新笔记");
    const latestStorage = localStorage.getItem(OBSERVE_STORAGE_KEY);
    const note = screen.getByRole("textbox", { name: /追加复盘笔记/ });
    fireEvent.change(note, { target: { value: "本页未保存的判断" } });
    fireEvent.click(screen.getByRole("button", { name: "保存复盘笔记" }));
    expect(note).toHaveValue("本页未保存的判断");
    fireEvent.click(screen.getByRole("button", { name: "重新读取观察" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /追加复盘笔记/ })).toHaveValue("本页未保存的判断");
    expect(screen.getByText("另一个页面的新笔记")).toBeInTheDocument();
    expect(localStorage.getItem(OBSERVE_STORAGE_KEY)).toBe(latestStorage);
    fireEvent.click(screen.getByRole("button", { name: "保存复盘笔记" }));
    expect(loadObserveState().state.records).toEqual(state.records);
    expect(loadObserveState().state.reviews.slice(1)).toEqual(latest.reviews);
    expect(loadObserveState().state.reviews[0].note).toBe("本页未保存的判断");
    expect(screen.getByRole("textbox", { name: /追加复盘笔记/ })).toHaveValue("");
  });

  it("does not restore an observation deleted elsewhere while its quote review is pending", async () => {
    const state = initialState();
    const record = state.records[0];
    let complete: (review: DeskReview) => void = () => undefined;
    const review = vi.fn(() => new Promise<DeskReview>((resolve) => { complete = resolve; }));
    render(<Harness initial={state} review={review} />);
    fireEvent.click(screen.getByRole("button", { name: "复核同一组合" }));
    removeObservation(state, record.id);
    complete(observeReviewFixture(record.desk));
    expect(await screen.findByRole("alert")).toHaveTextContent("记录已在其他页面更改或删除");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("已取得同一合约的新报价")).not.toBeInTheDocument();
    expect(loadObserveState().state).toEqual(emptyObserveState());
    fireEvent.click(screen.getByRole("button", { name: "重新读取观察" }));
    expect(screen.getByRole("heading", { name: "从一个看清楚的结构开始" })).toBeInTheDocument();
  });
});
