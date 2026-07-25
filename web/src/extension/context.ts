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
  bodyText,
  nowMs = Date.now(),
}: {
  href: string;
  documentTitle?: string;
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
      instrument: queryInstrument,
      underlying: underlyingFromInstrument(queryInstrument),
      detectedAt: nowMs,
    };
  }

  const domInstrument = scanInstrument(documentTitle, bodyText);
  return {
    href: url.href,
    route: url.pathname,
    source: domInstrument ? "dom" : "unknown",
    instrument: domInstrument,
    underlying: underlyingFromInstrument(domInstrument) ?? underlyingFromUrl(url),
    detectedAt: nowMs,
  };
}
