import { beforeEach, describe, expect, it, vi } from "vitest";

import { observeComparisonFixture, observeDeskFixture, observeReviewFixture } from "./observeFixtures";
import {
  OBSERVE_STORAGE_KEY, appendObservationNote, appendObservationReview, archiveObservation,
  emptyObserveState, loadObserveState, persistObserveState, removeObservation, saveObservation,
} from "./observeStore";

function save() {
  const desk = observeDeskFixture();
  const comparison = observeComparisonFixture(desk);
  const input = { desk, candidate_id: desk.candidates[0].candidate_id, comparison, viewpoint: desk.criteria.viewpoint, note: " 等待价差缩小 " };
  return { input, ...saveObservation(emptyObserveState(), input) };
}

describe("private browser observation storage", () => {
  beforeEach(() => localStorage.clear());

  it("freezes independent original inputs and restores them without contacting a backend", () => {
    const { input, state, record } = save();
    input.desk.candidates[0].legs[0].bid = 1;
    input.comparison.scenario.price_change_pct = 30;
    expect(record.desk.candidates[0].legs[0].bid).toBe(300);
    expect(record.comparison?.scenario.price_change_pct).toBe(-10);
    expect(Object.isFrozen(record.desk.candidates[0].legs[0])).toBe(true);
    expect(record.note).toBe("等待价差缩小");
    expect(loadObserveState()).toEqual({ state, error: null });
  });

  it("appends quotes and decision notes without changing the saved research", () => {
    const { state, record } = save();
    const original = JSON.stringify(record);
    const reviewed = appendObservationReview(state, record.id, observeReviewFixture(record.desk));
    const noted = appendObservationNote(reviewed, record.id, "保护腿报价改善，观点不变");
    expect(JSON.stringify(noted.records[0])).toBe(original);
    expect(noted.reviews.map((event) => event.kind)).toEqual(["note", "review"]);
    expect(noted.reviews[1].review?.desk?.candidates[0].legs[0].bid).toBe(325);
    expect(noted.reviews[1].review?.reviewed_candidate_id).not.toBe(record.candidate_id);
    expect(loadObserveState().state).toEqual(noted);
  });

  it.each(["unavailable", "expired"] as const)("preserves exact original legs when review is %s", (status) => {
    const { state, record } = save();
    const next = appendObservationReview(state, record.id, {
      schema_version: "desk_review.v1", reviewed_at: new Date().toISOString(),
      original_snapshot_id: record.desk.snapshot_id, original_candidate_id: record.candidate_id,
      reviewed_candidate_id: null, desk: null, status,
      reasons: [{ code: "QUOTE_UNAVAILABLE", detail: "原合约报价不可用" }],
    });
    expect(next.records[0]).toEqual(record);
    expect(next.reviews[0].review?.desk).toBeNull();
  });

  it("rejects a substituted review structure and leaves browser data intact", () => {
    const { state, record } = save();
    const originalStorage = localStorage.getItem(OBSERVE_STORAGE_KEY);
    const review = observeReviewFixture(record.desk);
    review.desk!.candidates[0].legs[0].instrument_name = "different-contract";
    expect(() => appendObservationReview(state, record.id, review)).toThrow("未保存");
    expect(localStorage.getItem(OBSERVE_STORAGE_KEY)).toBe(originalStorage);
  });

  it("refuses to rewrite original judgement, comparison, or immutable inputs through persistence", () => {
    const { state } = save();
    const changed = structuredClone(state);
    changed.records[0].note = "rewritten original";
    expect(() => persistObserveState(changed)).toThrow("未保存");
    expect(loadObserveState().state).toEqual(state);
  });

  it.each([
    "not json",
    JSON.stringify({ version: 2, records: [], reviews: [] }),
    JSON.stringify({ version: 1, records: [{ version: 1, id: "broken" }], reviews: [] }),
  ])("rejects malformed or unknown stored state without silently replacing it", (raw) => {
    localStorage.setItem(OBSERVE_STORAGE_KEY, raw);
    expect(loadObserveState().error).toContain("原数据未被修改");
    expect(() => save()).toThrow("未保存");
    expect(localStorage.getItem(OBSERVE_STORAGE_KEY)).toBe(raw);
  });

  it("reports a quota failure instead of returning a phantom saved observation", () => {
    const desk = observeDeskFixture();
    const storage = { getItem: vi.fn().mockReturnValue(null), setItem: vi.fn(() => { throw new DOMException("full", "QuotaExceededError"); }) };
    expect(() => saveObservation(emptyObserveState(), {
      desk, candidate_id: desk.candidates[0].candidate_id, comparison: null, viewpoint: "all", note: "",
    }, storage)).toThrow("未保存");
    expect(storage.setItem).toHaveBeenCalledOnce();
    expect(localStorage.getItem(OBSERVE_STORAGE_KEY)).toBeNull();
  });

  it("archives reversibly and removes records and their reviews only through the explicit remove action", () => {
    const { state, record } = save();
    const noted = appendObservationNote(state, record.id, "第一次复盘");
    const archived = archiveObservation(noted, record.id, true);
    expect(archived.records[0].archived).toBe(true);
    expect(archived.reviews).toEqual(noted.reviews);
    const restored = archiveObservation(archived, record.id, false);
    expect(restored.records[0]).toEqual(record);
    expect(() => persistObserveState(emptyObserveState())).toThrow("未保存");
    expect(removeObservation(restored, record.id)).toEqual(emptyObserveState());
  });

  it("does not overwrite another tab's new review using a stale state", () => {
    const { state, record } = save();
    const changedElsewhere = appendObservationNote(state, record.id, "另一个页面的复盘");
    expect(() => archiveObservation(state, record.id, true)).toThrow("未保存");
    expect(loadObserveState().state).toEqual(changedElsewhere);
  });
});
