import type { CandidateAction } from "../../contracts";

/**
 * One vocabulary for both surfaces.
 *
 * The workbench and the side panel each carried their own labels, and two of
 * the three tiers disagreed: `RESEARCH_ONLY` read "仅研究" in one and "仅供研究"
 * in the other, `REJECT` read "已拒绝" and "已剔除". These are the same
 * server-assigned tier, seen by the same person switching between two views of
 * one report, so a reader had no way to know whether the difference in wording
 * meant a difference in meaning.
 *
 * Tier names are the product's safety vocabulary. They are defined once here
 * and imported, never re-declared.
 */
export const TIER_LABELS: Record<CandidateAction, string> = {
  RESEARCH_ONLY: "仅研究",
  REVIEW: "待复核",
  REJECT: "已拒绝",
};

export const TIER_TONES: Record<CandidateAction, "safe" | "warning" | "danger"> =
  {
    RESEARCH_ONLY: "safe",
    REVIEW: "warning",
    REJECT: "danger",
  };

/** What each tier permits, stated so the badge is not the only signal. */
export const TIER_MEANINGS: Record<CandidateAction, string> = {
  RESEARCH_ONLY: "通过全部研究门槛；仍不构成任何下单指令。",
  REVIEW: "有分量处于需留意状态，结论需要人工复核。",
  REJECT: "未通过筛选，不参与排序。",
};

export function tierLabel(action: string | null | undefined): string {
  if (action && action in TIER_LABELS) {
    return TIER_LABELS[action as CandidateAction];
  }
  return "未分类";
}

export function tierTone(
  action: string | null | undefined,
): "safe" | "warning" | "danger" | "neutral" {
  if (action && action in TIER_TONES) {
    return TIER_TONES[action as CandidateAction];
  }
  return "neutral";
}

const STRUCTURE_LABELS: Record<string, string> = {
  naked_short_call: "裸卖 CALL",
  call_credit_spread: "CALL 价差",
  put_credit_spread: "PUT 价差",
  iron_condor: "铁鹰",
};

export function structureLabel(structure: string | null | undefined): string {
  if (!structure) {
    return "未知结构";
  }
  return STRUCTURE_LABELS[structure] ?? structure;
}

/**
 * The one sentence used wherever an expected value is absent.
 *
 * It says what is missing rather than printing a dash, because a dash reads as
 * "zero" often enough to matter on a column of money.
 */
export const EV_UNAVAILABLE = "无已验证路径证据";
