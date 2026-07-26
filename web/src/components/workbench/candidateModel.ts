import type {
  AbsoluteEv,
  CandidateAction,
  CandidatePathRisk,
  DominatedExplanation,
  EdgeComponent,
  EvCandidateScanner,
  FairIvDiagnostics,
  HazardZone,
  MarginSnapshot,
  RankedCandidate,
  RankingBasis,
  ResearchReport,
} from "../../contracts";
import { finiteNumber } from "../../report";

export type ScannerStatus = "unavailable" | "blocked" | "validated";
export type StructureKind = "spread" | "naked" | "unknown";

/** Edge component and dominance-axis names share this vocabulary. */
export const AXIS_LABELS: Record<string, string> = {
  smile_residual_richness: "微笑残差溢价",
  liquidity_cost_ratio: "流动性成本比",
  breakeven_cushion: "盈亏平衡缓冲",
  theta_efficiency: "Theta 效率",
  assignment_cost: "被指派成本",
  return_on_risk: "风险回报比",
};

export interface CandidateLegs {
  shortStrikeUsdc: number | null;
  longStrikeUsdc: number | null;
  kind: StructureKind;
}

export interface CandidateViewRow {
  id: string;
  structureType: string;
  structureKind: StructureKind;
  action: CandidateAction;
  scoreStatus: string | null;
  rankingScore: number | null;
  premiumUsdc: number | null;
  executableCreditUsdc: number | null;
  fairValueUsdc: number | null;
  evAfterCostUsdc: number | null;
  hasValidatedEv: boolean;
  dteDays: number | null;
  absDelta: number | null;
  killConditions: string[];
  reasonCodes: string[];
  dominatedBy: string | null;
  losingAxes: string[];
  legs: CandidateLegs;
  raw: RankedCandidate;
}

/* ------------------------------------------------------------------ */
/* Defensive parsing of the raw, not-yet-formally-contracted scanner    */
/* payload. `ResearchReport.ev_candidate_scanner` is typed `unknown` at */
/* the canonical boundary (see contracts.ts) because a second consumer  */
/* (report/projection.ts, for the side panel) already narrows the same  */
/* field with its own local types; narrowing it again here, locally,    */
/* keeps the two consumers from fighting over one shared type.          */
/* ------------------------------------------------------------------ */

type RawRecord = Record<string, unknown>;

function isRecord(value: unknown): value is RawRecord {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asNumberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function asAction(value: unknown): CandidateAction | null {
  return value === "RESEARCH_ONLY" || value === "REVIEW" || value === "REJECT"
    ? value
    : null;
}

function asScannerStatus(value: unknown): ScannerStatus {
  return value === "validated" || value === "blocked" ? value : "unavailable";
}

function parseRankingBasis(value: unknown): RankingBasis | undefined {
  if (!isRecord(value)) {
    return undefined;
  }
  return {
    method: asString(value.method),
    tie_break_order: asStringArray(value.tie_break_order),
    dominance_scope: asString(value.dominance_scope),
    absolute_ev_available:
      typeof value.absolute_ev_available === "boolean"
        ? value.absolute_ev_available
        : undefined,
  };
}

function parseDominatedExplanation(value: unknown): DominatedExplanation | null {
  if (!isRecord(value)) {
    return null;
  }
  const candidateId = asString(value.candidate_id);
  if (!candidateId) {
    return null;
  }
  return {
    candidate_id: candidateId,
    structure_type: asString(value.structure_type) ?? null,
    dominated_by: asString(value.dominated_by) ?? null,
    losing_axes: asStringArray(value.losing_axes),
  };
}

function parseRankedCandidate(value: unknown): RankedCandidate | null {
  if (!isRecord(value)) {
    return null;
  }
  const candidateId = asString(value.candidate_id);
  const action = asAction(value.action);
  if (!candidateId || !action) {
    return null;
  }
  const edgeComponents =
    value.edge_components === null
      ? null
      : isRecord(value.edge_components)
        ? (value.edge_components as Record<string, EdgeComponent>)
        : undefined;
  return {
    candidate_id: candidateId,
    action,
    structure_type: asString(value.structure_type) ?? null,
    score_status: asString(value.score_status) ?? null,
    ranking_score: asNumberOrNull(value.ranking_score),
    premium_usdc: asNumberOrNull(value.premium_usdc),
    executable_credit_usdc: asNumberOrNull(value.executable_credit_usdc),
    fair_value_usdc: asNumberOrNull(value.fair_value_usdc),
    ev_after_cost_usdc: asNumberOrNull(value.ev_after_cost_usdc),
    dte_days: asNumberOrNull(value.dte_days),
    model_delta: asNumberOrNull(value.model_delta),
    expiry_date: asString(value.expiry_date) ?? null,
    fair_iv_diagnostics: isRecord(value.fair_iv_diagnostics)
      ? (value.fair_iv_diagnostics as FairIvDiagnostics)
      : undefined,
    path_risk: isRecord(value.path_risk)
      ? (value.path_risk as CandidatePathRisk)
      : undefined,
    margin_snapshot: isRecord(value.margin_snapshot)
      ? (value.margin_snapshot as MarginSnapshot)
      : undefined,
    hazard_zone: isRecord(value.hazard_zone)
      ? (value.hazard_zone as HazardZone)
      : undefined,
    // Carried through so the payoff curve can be drawn from the legs rather
    // than reconstructed from a strike pair, which could only ever express the
    // two upside-only shapes the product used to have.
    structure_legs: Array.isArray(value.structure_legs)
      ? (value.structure_legs as unknown[])
      : undefined,
    kill_conditions: asStringArray(value.kill_conditions),
    reason_codes: asStringArray(value.reason_codes),
    edge_components: edgeComponents,
    dominated_by: asString(value.dominated_by) ?? null,
    losing_axes: asStringArray(value.losing_axes),
    absolute_ev: isRecord(value.absolute_ev)
      ? (value.absolute_ev as AbsoluteEv)
      : undefined,
  };
}

export function parseEvCandidateScanner(
  raw: unknown,
): EvCandidateScanner | undefined {
  if (!isRecord(raw)) {
    return undefined;
  }
  return {
    status: asScannerStatus(raw.status),
    score_status: asString(raw.score_status),
    reason_code: asString(raw.reason_code) ?? null,
    ranking_basis: parseRankingBasis(raw.ranking_basis),
    dominated_explanations: Array.isArray(raw.dominated_explanations)
      ? raw.dominated_explanations
          .map(parseDominatedExplanation)
          .filter((item): item is DominatedExplanation => item !== null)
      : [],
    ranked_candidates: Array.isArray(raw.ranked_candidates)
      ? raw.ranked_candidates
          .map(parseRankedCandidate)
          .filter((item): item is RankedCandidate => item !== null)
      : [],
  };
}

export function evCandidateScannerOf(
  report: ResearchReport,
): EvCandidateScanner | undefined {
  return parseEvCandidateScanner(report.ev_candidate_scanner);
}

/**
 * Deribit instrument tokens look like `BTC-7AUG26-71000-C`. Candidate
 * identifiers reuse that convention: a spread joins two legs with `->` and a
 * trailing `:spread` tag; a single leg carries a trailing `:naked` tag. This
 * mirrors the naming already produced by `candidate_research` elsewhere in
 * this report, so payoff geometry can be derived without a second network
 * round trip.
 */
function stripTag(token: string): string {
  return token.split(":")[0] ?? token;
}

function extractStrike(instrumentName: string): number | null {
  const parts = instrumentName.split("-");
  if (parts.length < 4) {
    return null;
  }
  const strikeToken = parts[parts.length - 2];
  const strike = Number(strikeToken);
  return Number.isFinite(strike) ? strike : null;
}

export function parseCandidateLegs(candidateId: string): CandidateLegs {
  if (candidateId.includes("->")) {
    const [shortRaw, longRaw] = candidateId.split("->");
    return {
      shortStrikeUsdc: extractStrike(stripTag(shortRaw ?? "")),
      longStrikeUsdc: extractStrike(stripTag(longRaw ?? "")),
      kind: "spread",
    };
  }
  const strike = extractStrike(stripTag(candidateId));
  if (strike === null) {
    return { shortStrikeUsdc: null, longStrikeUsdc: null, kind: "unknown" };
  }
  return { shortStrikeUsdc: strike, longStrikeUsdc: null, kind: "naked" };
}

export function scannerStatus(report: ResearchReport): ScannerStatus {
  return evCandidateScannerOf(report)?.status ?? "unavailable";
}

function toRow(candidate: RankedCandidate): CandidateViewRow {
  const legs = parseCandidateLegs(candidate.candidate_id);
  const delta = finiteNumber(candidate.model_delta);
  return {
    id: candidate.candidate_id,
    structureType: candidate.structure_type ?? "UNKNOWN",
    structureKind: legs.kind,
    action: candidate.action,
    scoreStatus: candidate.score_status ?? null,
    rankingScore: finiteNumber(candidate.ranking_score),
    premiumUsdc: finiteNumber(candidate.premium_usdc),
    executableCreditUsdc: finiteNumber(candidate.executable_credit_usdc),
    fairValueUsdc: finiteNumber(candidate.fair_value_usdc),
    evAfterCostUsdc: finiteNumber(candidate.ev_after_cost_usdc),
    hasValidatedEv: finiteNumber(candidate.ev_after_cost_usdc) !== null,
    dteDays: finiteNumber(candidate.dte_days),
    absDelta: delta === null ? null : Math.abs(delta),
    killConditions: candidate.kill_conditions ?? [],
    reasonCodes: candidate.reason_codes ?? [],
    dominatedBy: candidate.dominated_by ?? null,
    losingAxes: candidate.losing_axes ?? [],
    legs,
    raw: candidate,
  };
}

export function candidateRows(report: ResearchReport): CandidateViewRow[] {
  return (evCandidateScannerOf(report)?.ranked_candidates ?? []).map(toRow);
}

export function structureTypeOptions(rows: CandidateViewRow[]): string[] {
  return [...new Set(rows.map((row) => row.structureType))].sort();
}

export function dominanceExplanationFor(
  report: ResearchReport,
  candidateId: string,
): DominatedExplanation | null {
  return (
    evCandidateScannerOf(report)?.dominated_explanations?.find(
      (explanation) => explanation.candidate_id === candidateId,
    ) ?? null
  );
}

export type SortKey =
  | "structureType"
  | "action"
  | "dteDays"
  | "executableCreditUsdc"
  | "evAfterCostUsdc"
  | "rankingScore";

export interface SortState {
  key: SortKey;
  direction: "asc" | "desc";
}

function compareNullable(
  left: number | string | null,
  right: number | string | null,
): number {
  if (left === null && right === null) {
    return 0;
  }
  if (left === null) {
    return 1;
  }
  if (right === null) {
    return -1;
  }
  if (typeof left === "string" || typeof right === "string") {
    return String(left).localeCompare(String(right));
  }
  return left - right;
}

/**
 * Sorts within the rows given. This never changes `action`; it only orders
 * the array the caller already narrowed by `applyFilters`.
 */
export function sortCandidateRows(
  rows: CandidateViewRow[],
  sort: SortState,
): CandidateViewRow[] {
  const sorted = [...rows].sort((left, right) => {
    const comparison = compareNullable(left[sort.key], right[sort.key]);
    return sort.direction === "asc" ? comparison : -comparison;
  });
  return sorted;
}

export function candidateById(
  report: ResearchReport,
  candidateId: string,
): CandidateViewRow | null {
  return candidateRows(report).find((row) => row.id === candidateId) ?? null;
}
