import type { DeribitContext } from "./messages";

const INSTRUMENT_PATTERN = /\b([A-Z]{2,6}-\d{1,2}[A-Z]{3}\d{2}-\d+(?:\.\d+)?-[CP])\b/;
const UNDERLYING_PATTERN = /\b(?:options|futures|perpetuals)\/([A-Z]{2,6})\b/i;
const QUERY_KEYS = ["instrument", "instrument_name", "instrumentName", "name"];

function normalizeInstrument(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const match = value.toUpperCase().match(INSTRUMENT_PATTERN);
  return match?.[1] ?? null;
}

function underlyingFromInstrument(instrument: string | null): string | null {
  if (!instrument) {
    return null;
  }
  return instrument.split("-")[0] ?? null;
}

function underlyingFromUrl(url: URL): string | null {
  const match = url.pathname.match(UNDERLYING_PATTERN);
  return match?.[1]?.toUpperCase() ?? null;
}

function scanInstrument(...candidates: Array<string | null | undefined>): string | null {
  for (const candidate of candidates) {
    const instrument = normalizeInstrument(candidate);
    if (instrument) {
      return instrument;
    }
  }
  return null;
}

export function detectDeribitContext({
  href,
  documentTitle,
  structuralText,
  bodyText,
  nowMs = Date.now(),
}: {
  href: string;
  documentTitle?: string;
  /** Text scraped from selectors Deribit marks as instrument-identifying
   * (e.g. `[data-instrument-name]`). Treated as higher confidence than a
   * generic heading/body-text scan. */
  structuralText?: string;
  bodyText?: string;
  nowMs?: number;
}): DeribitContext {
  const url = new URL(href);
  const queryInstrument = scanInstrument(
    ...QUERY_KEYS.map((key) => url.searchParams.get(key)),
    url.hash,
    url.pathname,
  );

  if (queryInstrument) {
    return {
      href: url.href,
      route: url.pathname,
      source: "url",
      confidence: "url",
      instrument: queryInstrument,
      underlying: underlyingFromInstrument(queryInstrument),
      detectedAt: nowMs,
    };
  }

  const urlUnderlying = underlyingFromUrl(url);
  const structuralInstrument = scanInstrument(structuralText);
  const heuristicInstrument = structuralInstrument
    ? null
    : scanInstrument(documentTitle, bodyText);

  let instrument = structuralInstrument ?? heuristicInstrument;
  let confidence: DeribitContext["confidence"] = structuralInstrument
    ? "dom_structural"
    : heuristicInstrument
      ? "dom_heuristic"
      : "none";
  let underlying =
    (instrument && underlyingFromInstrument(instrument)) ?? urlUnderlying;

  if (instrument && urlUnderlying && underlying !== urlUnderlying) {
    // The scraped DOM text disagrees with the underlying the URL itself
    // names. The URL is the more reliable signal for the underlying, so it
    // wins outright; the instrument's own confidence is demoted one tier
    // rather than published at full trust, and a heuristic-tier disagreement
    // is untrustworthy enough to drop the instrument outright.
    underlying = urlUnderlying;
    if (confidence === "dom_structural") {
      confidence = "dom_heuristic";
    } else {
      confidence = "none";
      instrument = null;
    }
  }

  return {
    href: url.href,
    route: url.pathname,
    source: instrument ? "dom" : "unknown",
    confidence,
    instrument,
    underlying,
    detectedAt: nowMs,
  };
}
