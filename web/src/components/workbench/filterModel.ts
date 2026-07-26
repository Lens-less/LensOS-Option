import type { CandidateAction } from "../../contracts";
import type { CandidateViewRow } from "./candidateModel";

export const ALL_ACTION_TIERS: readonly CandidateAction[] = [
  "RESEARCH_ONLY",
  "REVIEW",
  "REJECT",
];

export interface ScreenerFilters {
  /** Empty means "no structure filter applied" (all structures pass). */
  structureTypes: string[];
  dteMin: number | null;
  dteMax: number | null;
  absDeltaMin: number | null;
  absDeltaMax: number | null;
  minCreditUsdc: number | null;
  /** Which server-assigned action tiers remain visible. Never used to change a row's tier. */
  actionTiers: CandidateAction[];
}

/**
 * Rejected rows are hidden by default.
 *
 * A live chain produces a few hundred rejected candidates against a handful of
 * research-grade ones — 510 against 8 on the first real snapshot. Showing all of
 * them by default buried the eight rows the page exists for under a page tens of
 * thousands of pixels tall. They remain one checkbox away, and the count of what
 * is hidden is always displayed, because a filter that hides silently is the
 * same failure in the other direction.
 */
export const DEFAULT_ACTION_TIERS: readonly CandidateAction[] = [
  "RESEARCH_ONLY",
  "REVIEW",
];

export function defaultFilters(): ScreenerFilters {
  return {
    structureTypes: [],
    dteMin: null,
    dteMax: null,
    absDeltaMin: null,
    absDeltaMax: null,
    minCreditUsdc: null,
    actionTiers: [...DEFAULT_ACTION_TIERS],
  };
}

export function isDefaultFilters(filters: ScreenerFilters): boolean {
  const base = defaultFilters();
  return (
    filters.structureTypes.length === 0 &&
    filters.dteMin === null &&
    filters.dteMax === null &&
    filters.absDeltaMin === null &&
    filters.absDeltaMax === null &&
    filters.minCreditUsdc === null &&
    filters.actionTiers.length === base.actionTiers.length &&
    base.actionTiers.every((tier) => filters.actionTiers.includes(tier))
  );
}

/**
 * Narrows rows within their server-assigned `action` tier. This function must
 * never rewrite `row.action`: it only ever removes rows from the returned
 * array. A REJECT-tier candidate that matches every slider stays REJECT; it
 * can be hidden by unchecking the REJECT tier toggle, but it can never be
 * relabelled RESEARCH_ONLY or REVIEW by any combination of filter values.
 */
export function applyFilters(
  rows: CandidateViewRow[],
  filters: ScreenerFilters,
): CandidateViewRow[] {
  return rows.filter((row) => {
    if (!filters.actionTiers.includes(row.action)) {
      return false;
    }
    if (
      filters.structureTypes.length > 0 &&
      !filters.structureTypes.includes(row.structureType)
    ) {
      return false;
    }
    if (filters.dteMin !== null) {
      if (row.dteDays === null || row.dteDays < filters.dteMin) {
        return false;
      }
    }
    if (filters.dteMax !== null) {
      if (row.dteDays === null || row.dteDays > filters.dteMax) {
        return false;
      }
    }
    if (filters.absDeltaMin !== null) {
      if (row.absDelta === null || row.absDelta < filters.absDeltaMin) {
        return false;
      }
    }
    if (filters.absDeltaMax !== null) {
      if (row.absDelta === null || row.absDelta > filters.absDeltaMax) {
        return false;
      }
    }
    if (filters.minCreditUsdc !== null) {
      if (
        row.executableCreditUsdc === null ||
        row.executableCreditUsdc < filters.minCreditUsdc
      ) {
        return false;
      }
    }
    return true;
  });
}

const PARAM_KEYS = {
  structure: "structure",
  dteMin: "dteMin",
  dteMax: "dteMax",
  deltaMin: "deltaMin",
  deltaMax: "deltaMax",
  minCredit: "minCredit",
  tiers: "tiers",
} as const;

function numberParam(params: URLSearchParams, key: string): number | null {
  const raw = params.get(key);
  if (raw === null || raw === "") {
    return null;
  }
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

export function encodeFilters(filters: ScreenerFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.structureTypes.length > 0) {
    params.set(PARAM_KEYS.structure, filters.structureTypes.join(","));
  }
  if (filters.dteMin !== null) {
    params.set(PARAM_KEYS.dteMin, String(filters.dteMin));
  }
  if (filters.dteMax !== null) {
    params.set(PARAM_KEYS.dteMax, String(filters.dteMax));
  }
  if (filters.absDeltaMin !== null) {
    params.set(PARAM_KEYS.deltaMin, String(filters.absDeltaMin));
  }
  if (filters.absDeltaMax !== null) {
    params.set(PARAM_KEYS.deltaMax, String(filters.absDeltaMax));
  }
  if (filters.minCreditUsdc !== null) {
    params.set(PARAM_KEYS.minCredit, String(filters.minCreditUsdc));
  }
  if (filters.actionTiers.length !== ALL_ACTION_TIERS.length) {
    params.set(PARAM_KEYS.tiers, filters.actionTiers.join(","));
  }
  return params;
}

export function decodeFilters(params: URLSearchParams): ScreenerFilters {
  const structureParam = params.get(PARAM_KEYS.structure);
  const tiersParam = params.get(PARAM_KEYS.tiers);
  const decodedTiers = tiersParam
    ? tiersParam
        .split(",")
        .filter((tier): tier is CandidateAction =>
          (ALL_ACTION_TIERS as string[]).includes(tier),
        )
    : [...DEFAULT_ACTION_TIERS];
  return {
    structureTypes: structureParam
      ? structureParam.split(",").filter(Boolean)
      : [],
    dteMin: numberParam(params, PARAM_KEYS.dteMin),
    dteMax: numberParam(params, PARAM_KEYS.dteMax),
    absDeltaMin: numberParam(params, PARAM_KEYS.deltaMin),
    absDeltaMax: numberParam(params, PARAM_KEYS.deltaMax),
    minCreditUsdc: numberParam(params, PARAM_KEYS.minCredit),
    actionTiers:
      decodedTiers.length > 0 ? decodedTiers : [...DEFAULT_ACTION_TIERS],
  };
}
