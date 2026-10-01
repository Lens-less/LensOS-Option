import { beforeEach, describe, expect, it, vi } from "vitest";

import { observeComparisonFixture, observeDeskFixture, observeReviewFixture } from "./observeFixtures";
import {
  OBSERVE_STORAGE_KEY, ObserveStorageConflictError, appendObservationNote, appendObservationReview, archiveObservation,
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

  it.each(["note", "archive", "review", "persist"] as const)("does not resurrect a deleted observation or private notes through a stale %s", (action) => {
    const saved = save();
    const tabA = appendObservationNote(saved.state, saved.record.id, "删除后不能恢复的私密笔记");
    const tabB = loadObserveState().state;
    removeObservation(tabA, saved.record.id);
    const deletedStorage = localStorage.getItem(OBSERVE_STORAGE_KEY);
    const mutate = () => {
      if (action === "note") appendObservationNote(tabB, saved.record.id, "旧页面里的后续判断");
      else if (action === "archive") archiveObservation(tabB, saved.record.id, true);
      else if (action === "review") appendObservationReview(tabB, saved.record.id, observeReviewFixture(saved.record.desk));
      else persistObserveState(tabB);
    };

    expect(mutate).toThrow(ObserveStorageConflictError);
    expect(mutate).toThrow("请重新读取观察列表");
    expect(localStorage.getItem(OBSERVE_STORAGE_KEY)).toBe(deletedStorage);
    expect(loadObserveState().state).toEqual(emptyObserveState());
    expect(deletedStorage).not.toContain("私密笔记");
    expect(deletedStorage).not.toContain(saved.record.id);
  });

  it("keeps cleared private browser data absent when a stale page attempts to save", () => {
    const { state, record } = save();
    localStorage.removeItem(OBSERVE_STORAGE_KEY);
    expect(() => appendObservationNote(state, record.id, "不能恢复已清除的记录")).toThrow(ObserveStorageConflictError);
    expect(localStorage.getItem(OBSERVE_STORAGE_KEY)).toBeNull();
  });

  it("preserves newer records and events during stale edits, then accepts a reloaded base", () => {
    const { input, state, record } = save();
    const tabB = loadObserveState().state;
    const newSave = saveObservation(state, { ...input, note: "另一个页面的新观察" });
    const latest = appendObservationNote(newSave.state, newSave.record.id, "新观察的私密复盘");
    const latestStorage = localStorage.getItem(OBSERVE_STORAGE_KEY);
    const staleActions = [
      () => appendObservationNote(tabB, record.id, "旧页面追加"),
      () => archiveObservation(tabB, record.id, true),
      () => removeObservation(tabB, record.id),
      () => saveObservation(tabB, input),
    ];
    for (const action of staleActions) {
      expect(action).toThrow(ObserveStorageConflictError);
      expect(localStorage.getItem(OBSERVE_STORAGE_KEY)).toBe(latestStorage);
    }
    expect(loadObserveState().state).toEqual(latest);

    const reloaded = loadObserveState().state;
    const recovered = appendObservationNote(reloaded, record.id, "重新读取后保存");
    expect(recovered.records).toEqual(latest.records);
    expect(recovered.reviews.slice(1)).toEqual(latest.reviews);
    expect(recovered.reviews[0].note).toBe("重新读取后保存");
    expect(loadObserveState().state).toEqual(recovered);
  });

  it("does not roll back another page's archive status using a stale base", () => {
    const { state, record } = save();
    const archived = archiveObservation(state, record.id, true);
    expect(() => appendObservationNote(state, record.id, "旧页面的笔记")).toThrow(ObserveStorageConflictError);
    expect(loadObserveState().state).toEqual(archived);
  });

  it("continues to load and append to the unchanged saved v1 format", () => {
    const { state, record } = save();
    localStorage.setItem(OBSERVE_STORAGE_KEY, JSON.stringify({ reviews: state.reviews, records: state.records, version: 1 }));
    const loaded = loadObserveState();
    expect(loaded.error).toBeNull();
    const updated = appendObservationNote(loaded.state, record.id, "旧版本记录继续复盘");
    expect(updated.records[0]).toEqual(record);
    expect(Object.isFrozen(updated.records[0].desk)).toBe(true);
    expect(Object.keys(JSON.parse(localStorage.getItem(OBSERVE_STORAGE_KEY)!)).sort()).toEqual(["records", "reviews", "version"]);
    expect(loadObserveState().state).toEqual(updated);
  });
});
