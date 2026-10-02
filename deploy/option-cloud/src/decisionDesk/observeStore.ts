import { previewNow } from "./preview";
import { validateDecisionDesk, validateDeskComparison, validateDeskReview } from "./client";
import type { DecisionDesk, DeskComparison, DeskReview, Viewpoint } from "./types";

export const OBSERVE_STORAGE_KEY = "lensos-option.cloud-preview.observations.v1";
export const OBSERVE_CONFLICT_MESSAGE = "观察记录未保存：此浏览器的记录已在其他页面更改或删除。请重新读取观察列表后再操作；最新记录和删除结果未被覆盖。";
const MAX_RECORDS = 100;
const MAX_EVENTS = 1_000;
const MAX_NOTE_LENGTH = 2_000;
const MAX_STORAGE_BYTES = 4_000_000;

export interface ObservationRecord {
  version: 1;
  id: string;
  saved_at: string;
  desk: DecisionDesk;
  candidate_id: string;
  comparison: DeskComparison | null;
  viewpoint: Viewpoint;
  note: string;
  archived: boolean;
}

/** Follow-up notes and reviews are append-only; the saved research stays intact. */
export interface ObservationReviewEvent {
  version: 1;
  id: string;
  observation_id: string;
  saved_at: string;
  kind: "review" | "note";
  review: DeskReview | null;
  note: string;
}

export interface ObserveState {
  version: 1;
  records: ObservationRecord[];
  reviews: ObservationReviewEvent[];
}

export interface SaveObservationInput {
  desk: DecisionDesk;
  candidate_id: string;
  comparison: DeskComparison | null;
  viewpoint: Viewpoint;
  note: string;
}

export class ObserveStorageError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ObserveStorageError";
  }
}

export class ObserveStorageConflictError extends ObserveStorageError {
  constructor() {
    super(OBSERVE_CONFLICT_MESSAGE);
    this.name = "ObserveStorageConflictError";
  }
}

export function emptyObserveState(): ObserveState {
  return immutableCopy({ version: 1, records: [], reviews: [] });
}

/** Reading never repairs or overwrites an unrecognized browser file. */
export function loadObserveState(storage?: Pick<Storage, "getItem">): { state: ObserveState; error: string | null } {
  try {
    const raw = (storage ?? browserStorage()).getItem(OBSERVE_STORAGE_KEY);
    if (raw === null) return { state: emptyObserveState(), error: null };
    if (raw.length > MAX_STORAGE_BYTES) throw new ObserveStorageError("Saved observations exceed the supported browser storage limit");
    const state = validateObserveState(JSON.parse(raw));
    return { state: immutableCopy(state), error: null };
  } catch {
    return {
      state: emptyObserveState(),
      error: "无法读取此浏览器的观察记录。数据可能损坏、版本不受支持，或浏览器禁止本地存储；原数据未被修改。",
    };
  }
}

/** Persist an unchanged current state; edits must carry their pre-edit base. */
export function persistObserveState(state: ObserveState, storage?: Pick<Storage, "getItem" | "setItem">): void {
  commitObserveState(state, state, storage);
}

function commitObserveState(
  state: ObserveState,
  baseState: ObserveState,
  storage?: Pick<Storage, "getItem" | "setItem">,
  removedObservationIds: string[] = [],
): void {
  try {
    const target = storage ?? browserStorage();
    const raw = target.getItem(OBSERVE_STORAGE_KEY);
    validateObserveState(baseState);
    if (raw !== null) require(raw.length <= MAX_STORAGE_BYTES);
    const previous = raw === null ? emptyObserveState() : validateObserveState(JSON.parse(raw));
    // Check the complete pre-edit state, including absent records and archive
    // flags. Checking only surviving originals lets a stale tab resurrect a
    // deleted observation and all of its private notes. Never merge stale edits.
    // localStorage has no atomic compare-and-swap: this guards changes already
    // visible at commit time, rather than promising cross-tab transactions.
    if (JSON.stringify(previous) !== JSON.stringify(baseState)) {
      throw new ObserveStorageConflictError();
    }
    if (raw !== null) {
      for (const original of previous.records) {
        const next = state.records.find((record) => record.id === original.id);
        if (!next) require(removedObservationIds.includes(original.id));
        else {
          const { archived: _previousArchived, ...originalInput } = original;
          const { archived: _nextArchived, ...nextInput } = next;
          require(JSON.stringify(originalInput) === JSON.stringify(nextInput));
        }
      }
      for (const prior of previous.reviews) {
        const next = state.reviews.find((event) => event.id === prior.id);
        if (!next) require(removedObservationIds.includes(prior.observation_id));
        else require(JSON.stringify(prior) === JSON.stringify(next));
      }
    }
    validateObserveState(state);
    const serialized = JSON.stringify(state);
    if (serialized.length > MAX_STORAGE_BYTES) throw new ObserveStorageError("Browser observation storage is full");
    target.setItem(OBSERVE_STORAGE_KEY, serialized);
  } catch (failure) {
    if (failure instanceof ObserveStorageConflictError) throw failure;
    throw new ObserveStorageError("观察记录未保存。请检查浏览器的本地存储权限或空间；已有记录未被覆盖。");
  }
}

export function saveObservation(
  state: ObserveState,
  input: SaveObservationInput,
  storage?: Pick<Storage, "getItem" | "setItem">,
): { state: ObserveState; record: ObservationRecord } {
  const chosen = input.desk.candidates.find((candidate) => candidate.candidate_id === input.candidate_id);
  const nowMs = previewNow();
  if (!chosen || chosen.status !== "comparable" || Date.parse(chosen.recheck_at) <= nowMs
    || chosen.expiration_timestamp <= nowMs || Date.parse(input.desk.expires_at) <= nowMs) {
    throw new ObserveStorageError("当前选腿已失效，观察记录未保存。请取得新报价后重新比较。");
  }
  if (state.records.length >= MAX_RECORDS) throw new ObserveStorageError("观察记录已达 100 条。请明确删除不再需要的记录后保存。");
  const record: ObservationRecord = immutableCopy({
    version: 1,
    id: createId(),
    saved_at: new Date().toISOString(),
    desk: input.desk,
    candidate_id: input.candidate_id,
    comparison: input.comparison,
    viewpoint: input.viewpoint,
    note: input.note.trim(),
    archived: false,
  });
  const next = immutableCopy({ ...state, records: [record, ...state.records] });
  commitObserveState(next, state, storage);
  return { state: next, record };
}

export function appendObservationReview(
  state: ObserveState,
  observationId: string,
  review: DeskReview,
  storage?: Pick<Storage, "getItem" | "setItem">,
): ObserveState {
  return appendEvent(state, observationId, "review", review, "", storage);
}

export function appendObservationNote(
  state: ObserveState,
  observationId: string,
  note: string,
  storage?: Pick<Storage, "getItem" | "setItem">,
): ObserveState {
  const trimmed = note.trim();
  if (!trimmed) throw new ObserveStorageError("请写下本次复盘的判断，再保存笔记。");
  return appendEvent(state, observationId, "note", null, trimmed, storage);
}

export function archiveObservation(
  state: ObserveState,
  observationId: string,
  archived: boolean,
  storage?: Pick<Storage, "getItem" | "setItem">,
): ObserveState {
  requireRecord(state, observationId);
  const next = immutableCopy({
    ...state,
    records: state.records.map((record) => record.id === observationId ? { ...record, archived } : record),
  });
  commitObserveState(next, state, storage);
  return next;
}

export function removeObservation(
  state: ObserveState,
  observationId: string,
  storage?: Pick<Storage, "getItem" | "setItem">,
): ObserveState {
  requireRecord(state, observationId);
  const next = immutableCopy({
    ...state,
    records: state.records.filter((record) => record.id !== observationId),
    reviews: state.reviews.filter((event) => event.observation_id !== observationId),
  });
  commitObserveState(next, state, storage, [observationId]);
  return next;
}

function appendEvent(
  state: ObserveState,
  observationId: string,
  kind: "review" | "note",
  review: DeskReview | null,
  note: string,
  storage?: Pick<Storage, "getItem" | "setItem">,
): ObserveState {
  requireRecord(state, observationId);
  if (state.reviews.length >= MAX_EVENTS) throw new ObserveStorageError("复盘记录已达浏览器保存上限。请删除不再需要的观察记录后继续。");
  const event: ObservationReviewEvent = {
    version: 1, id: createId(), observation_id: observationId,
    saved_at: new Date().toISOString(), kind, review, note,
  };
  const next = immutableCopy({ ...state, reviews: [event, ...state.reviews] });
  commitObserveState(next, state, storage);
  return next;
}

function requireRecord(state: ObserveState, observationId: string): ObservationRecord {
  const record = state.records.find((item) => item.id === observationId);
  if (!record) throw new ObserveStorageError("该观察记录已不存在。请重新读取观察列表。");
  return record;
}

function browserStorage(): Storage {
  return globalThis.localStorage;
}

function createId(): string {
  return globalThis.crypto.randomUUID();
}

function immutableCopy<T>(value: T): T {
  const copy: T = JSON.parse(JSON.stringify(value));
  const freeze = (item: unknown): void => {
    if (!item || typeof item !== "object" || Object.isFrozen(item)) return;
    Object.values(item).forEach(freeze);
    Object.freeze(item);
  };
  freeze(copy);
  return copy;
}

function validateObserveState(value: unknown): ObserveState {
  const state = object(value);
  exactKeys(state, ["version", "records", "reviews"]);
  require(state.version === 1);
  const records = array(state.records, MAX_RECORDS).map(validateObservation);
  require(new Set(records.map((record) => record.id)).size === records.length);
  const byId = new Map(records.map((record) => [record.id, record]));
  const reviews = array(state.reviews, MAX_EVENTS).map((value) => {
    const event = object(value);
    exactKeys(event, ["version", "id", "observation_id", "saved_at", "kind", "review", "note"]);
    require(event.version === 1 && text(event.id) && text(event.observation_id) && timestamp(event.saved_at));
    require(event.kind === "review" || event.kind === "note");
    require(typeof event.note === "string" && event.note.length <= MAX_NOTE_LENGTH);
    const original = byId.get(String(event.observation_id));
    require(original !== undefined);
    if (event.kind === "note") require(event.review === null && String(event.note).trim().length > 0);
    else {
      require(event.note === "");
      validateReview(event.review, original!);
    }
    return value as ObservationReviewEvent;
  });
  require(new Set(reviews.map((event) => event.id)).size === reviews.length);
  return { version: 1, records, reviews };
}

function validateObservation(value: unknown): ObservationRecord {
  const record = object(value);
  exactKeys(record, ["version", "id", "saved_at", "desk", "candidate_id", "comparison", "viewpoint", "note", "archived"]);
  require(record.version === 1 && text(record.id) && timestamp(record.saved_at));
  require(text(record.candidate_id) && viewpoint(record.viewpoint) && typeof record.archived === "boolean");
  require(typeof record.note === "string" && record.note.length <= MAX_NOTE_LENGTH);
  validateDecisionDesk(record.desk);
  const desk = record.desk as DecisionDesk;
  require(desk.source.mode === "demo" && desk.source.provider === "SYNTHETIC_DEMO");
  require(desk.candidates.some((candidate) => candidate.candidate_id === record.candidate_id));
  if (record.comparison !== null) {
    validateDeskComparison(record.comparison);
    const comparison = record.comparison as DeskComparison;
    require(comparison.snapshot_id === desk.snapshot_id && comparison.asset === desk.asset);
    require(comparison.analysis_id === desk.analysis_id);
    require(comparison.generated_at === desk.generated_at);
    require(comparison.members.some((member) => member.candidate_id === record.candidate_id));
    require(comparison.members.every((member) => desk.candidates.some((candidate) => candidate.candidate_id === member.candidate_id
      && candidate.assumptions_id === comparison.assumptions_id)));
  }
  return value as ObservationRecord;
}

function validateReview(value: unknown, original: ObservationRecord): void {
  validateDeskReview(value);
  const review = object(value);
  require(review.schema_version === "desk_review.v1" && timestamp(review.reviewed_at));
  require(review.original_snapshot_id === original.desk.snapshot_id);
  require(review.original_candidate_id === original.candidate_id);
  // This deployed replay cannot obtain fresh quotes. Never promote a local sample to live evidence.
  require(review.status === "unavailable" && review.desk === null && review.reviewed_candidate_id === null);
  reasons(review.reasons);

}

function object(value: unknown): Record<string, unknown> {
  require(value !== null && typeof value === "object" && !Array.isArray(value));
  return value as Record<string, unknown>;
}
function array(value: unknown, max = 10_000): unknown[] {
  require(Array.isArray(value) && value.length <= max);
  return value as unknown[];
}
function require(condition: unknown): asserts condition {
  if (!condition) throw new ObserveStorageError("Saved observation has an unsupported or malformed shape");
}
function exactKeys(value: Record<string, unknown>, keys: string[]): void {
  require(Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)));
}
function text(value: unknown): value is string { return typeof value === "string" && value.length > 0 && value.length <= 10_000; }
function timestamp(value: unknown): value is string { return text(value) && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value)); }
function viewpoint(value: unknown): value is Viewpoint { return ["all", "bullish", "bearish", "range"].includes(String(value)); }
function reasons(value: unknown): void {
  array(value).forEach((value) => { const reason = object(value); require(text(reason.code) && typeof reason.detail === "string"); });
}
