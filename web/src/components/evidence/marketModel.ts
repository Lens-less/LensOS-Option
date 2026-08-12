import type {
  CallCreditSpreadCandidate,
  NakedCallCandidate,
  ResearchReport,
} from "../../contracts";
import {
  formatDecimal,
  formatDvol,
  formatExpiry,
  formatPercent,
  formatTimestamp,
  formatUsd,
  friendlySource,
} from "../../report/display";
import { finiteNumber } from "../../report/numbers";

type CandidateKind = "naked" | "spread";

export interface MarketFacts {
  dvol: number | null;
  eligibleExpiries: number | null;
  evaluatedExpiries: number | null;
  coverageRatio: number | null;
  nakedCandidates: number | null;
  selectedInstruments: number | null;
  source: string;
  spreadCandidates: number | null;
  upstreamInstruments: number | null;
  volIndexAgeSec: number | null;
  volIndexName: string | null;
  volIndexStatus: string | null;
  totalQuotes: number | null;
  underlyingPrice: number | null;
  validQuotes: number | null;
}

export interface CandidateRow {
  contract: string;
  delta: number | null;
  expiry: string | null;
  id: string;
  kind: CandidateKind;
  premium: number | null;
  quality: number | null;
  noArbPass: boolean | null;
}

export { formatDecimal, formatDvol, formatExpiry, formatPercent, formatTimestamp, formatUsd };

export function marketFacts(report: ResearchReport): MarketFacts {
  const expiries = report.vol_surface_status?.expiries ?? [];
  const collectionScope = report.data_status?.collection_scope;
  const volIndex =
    report.data_status?.public_response_contract?.endpoints?.vol_index;
  const underlyingPrice =
    finiteNumber(report.strategy_research?.analysis?.market?.spot_usd) ??
    expiries
      .flatMap((expiry) => expiry.surface_points ?? [])
      .map((point) => finiteNumber(point.underlying_price))
      .find((value): value is number => value !== null) ??
    null;
  const qualitySummary = report.data_status?.quality_gate?.summary;
  const candidateSummary = report.candidate_research?.summary;
  return {
    dvol: finiteNumber(
      report.data_status?.public_response_contract?.endpoints?.vol_index
        ?.volatility ?? report.vrp_status?.current_dvol_percent,
    ),
    coverageRatio: finiteNumber(collectionScope?.coverage_ratio),
    eligibleExpiries: finiteNumber(
      report.vol_surface_status?.summary?.eligible_expiries ??
        candidateSummary?.eligible_expiries,
    ),
    evaluatedExpiries: finiteNumber(
      report.vol_surface_status?.summary?.expiries_evaluated ??
        candidateSummary?.expiries_considered ??
        qualitySummary?.expiries_evaluated,
    ),
    nakedCandidates: finiteNumber(
      candidateSummary?.eligible_naked_short_calls,
    ),
    selectedInstruments: finiteNumber(
      collectionScope?.selected_instrument_count,
    ),
    source: friendlySource(report.data_status?.source),
    spreadCandidates: finiteNumber(
      candidateSummary?.eligible_call_credit_spreads,
    ),
    upstreamInstruments: finiteNumber(
      collectionScope?.upstream_instrument_count,
    ),
    volIndexAgeSec: finiteNumber(volIndex?.age_sec),
    volIndexName: volIndex?.index_name ?? null,
    volIndexStatus: volIndex?.status ?? null,
    totalQuotes: finiteNumber(qualitySummary?.total_quotes),
    underlyingPrice,
    validQuotes: finiteNumber(qualitySummary?.valid_quotes),
  };
}

function spreadToRow(candidate: CallCreditSpreadCandidate): CandidateRow {
  return {
    contract:
      candidate.sell_leg_instrument_name && candidate.buy_leg_instrument_name
        ? `${candidate.sell_leg_instrument_name} → ${candidate.buy_leg_instrument_name}`
        : candidate.candidate_id ?? "价差合约未提供",
    delta: finiteNumber(candidate.model_delta),
    expiry: candidate.expiry_date ?? null,
    id:
      candidate.candidate_id ??
      `spread:${candidate.sell_leg_instrument_name ?? "unknown"}:${candidate.buy_leg_instrument_name ?? "unknown"}:${candidate.expiry_date ?? "unknown"}`,
    kind: "spread",
    premium: finiteNumber(candidate.net_credit),
    quality: finiteNumber(candidate.surface_quality?.fit_quality_score),
    noArbPass:
      typeof candidate.surface_quality?.no_arb_pass === "boolean"
        ? candidate.surface_quality.no_arb_pass
        : null,
  };
}

function nakedToRow(candidate: NakedCallCandidate): CandidateRow {
  return {
    contract:
      candidate.instrument_name ??
      candidate.candidate_id ??
      "单腿合约未提供",
    delta: finiteNumber(candidate.model_delta),
    expiry: candidate.expiry_date ?? null,
    id:
      candidate.candidate_id ??
      `naked:${candidate.instrument_name ?? "unknown"}:${candidate.expiry_date ?? "unknown"}`,
    kind: "naked",
    premium: finiteNumber(candidate.market_mid),
    quality: finiteNumber(candidate.surface_quality?.fit_quality_score),
    noArbPass:
      typeof candidate.surface_quality?.no_arb_pass === "boolean"
        ? candidate.surface_quality.no_arb_pass
        : null,
  };
}

export function researchCandidates(report: ResearchReport): CandidateRow[] {
  const spreads =
    report.candidate_research?.call_credit_spreads?.eligible?.map(
      spreadToRow,
    ) ?? [];
  const naked =
    report.candidate_research?.naked_short_calls?.eligible?.map(nakedToRow) ??
    [];
  return [...spreads, ...naked];
}
