import catalogData from "./catalog.json";
import { describe, expect, it } from "vitest";

import {
  PUBLIC_REASON_CODES,
  PUBLIC_REASON_CODE_READINGS,
  REASON_CODE_CATALOG,
  type ReasonCodeCatalogEntry,
  REPORT_REASON_CODES,
  REPORT_REASON_COPY,
  SHELL_REASON_CODES,
  SHELL_REASON_CODE_READINGS,
} from "./catalog";
import { PUBLIC_REASON_CODE_READINGS as GENERATED_PUBLIC_REASON_CODE_READINGS } from "../public/publicReasonCodes.generated";

type CatalogData = Record<string, Omit<ReasonCodeCatalogEntry, "code">>;
type CatalogSurface = keyof CatalogData[string];

const CATALOG = catalogData as CatalogData;
const CATALOG_CODES = Object.keys(CATALOG);
const FAIL_CLOSED_REASON_CODES = [
  "DATA_TRUST_THRESHOLD_EVIDENCE_MISSING",
  "DTE_EVIDENCE_CONFLICT",
  "MARKET_TRUST_THRESHOLD_EVIDENCE_MISSING",
  "TRUST_PROMOTION_MINIMUMS_MISSING",
] as const;

function expectedCodes(surface: CatalogSurface): string[] {
  return CATALOG_CODES.filter((code) => CATALOG[code][surface] !== undefined);
}

describe("reason code catalog", () => {
  it("keeps the canonical catalog keyed and projected for every surface", () => {
    expect(Object.keys(REASON_CODE_CATALOG)).toEqual(CATALOG_CODES);
    for (const code of CATALOG_CODES) {
      expect(REASON_CODE_CATALOG[code]).toEqual({ code, ...CATALOG[code] });
    }
  });

  it("keeps shell, public, and report projections complete", () => {
    expect(SHELL_REASON_CODES).toEqual(expectedCodes("shell"));
    expect(PUBLIC_REASON_CODES).toEqual(expectedCodes("public"));
    expect(REPORT_REASON_CODES).toEqual(expectedCodes("report"));

    expect(SHELL_REASON_CODE_READINGS).toEqual(
      Object.fromEntries(SHELL_REASON_CODES.map((code) => [code, CATALOG[code].shell])),
    );
    expect(PUBLIC_REASON_CODE_READINGS).toEqual(
      Object.fromEntries(PUBLIC_REASON_CODES.map((code) => [code, CATALOG[code].public])),
    );
    expect(REPORT_REASON_COPY).toEqual(
      Object.fromEntries(REPORT_REASON_CODES.map((code) => [code, CATALOG[code].report])),
    );
  });

  it("keeps the generated public projection in sync", () => {
    expect(GENERATED_PUBLIC_REASON_CODE_READINGS).toEqual(
      PUBLIC_REASON_CODE_READINGS,
    );
  });

  it("publishes copy for every new fail-closed reason code", () => {
    for (const code of FAIL_CLOSED_REASON_CODES) {
      expect(REASON_CODE_CATALOG[code]?.shell).toBeDefined();
      expect(REASON_CODE_CATALOG[code]?.public).toBeDefined();
      expect(REASON_CODE_CATALOG[code]?.report).toBeDefined();
    }
  });
});
