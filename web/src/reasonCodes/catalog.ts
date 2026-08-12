import catalogData from "./catalog.json";

export type ReasonQueue = "operator" | "system";

export interface ReasonCodeRemedy {
  label: string;
  command: string;
}

export interface ShellReasonCodeReading {
  title: string;
  detail: string;
  remedy?: ReasonCodeRemedy;
}

export interface PublicReasonCodeReading {
  title: string;
  detail: string;
}

export interface ReportReasonCopy {
  label: string;
  action: string;
  ownerLabel: string;
  queue: ReasonQueue;
}

export interface ReasonCodeCatalogEntry {
  code: string;
  shell?: ShellReasonCodeReading;
  public?: PublicReasonCodeReading;
  report?: ReportReasonCopy;
}

type ReasonCodeCatalogSourceEntry = Omit<ReasonCodeCatalogEntry, "code">;

const CATALOG_ENTRIES = Object.entries(
  catalogData as Record<string, ReasonCodeCatalogSourceEntry>,
);

function buildCodes<K extends keyof ReasonCodeCatalogSourceEntry>(key: K): string[] {
  return CATALOG_ENTRIES.flatMap(([code, entry]) =>
    entry[key] ? [code] : [],
  );
}

function buildProjection<K extends keyof ReasonCodeCatalogSourceEntry>(
  key: K,
): Record<string, NonNullable<ReasonCodeCatalogSourceEntry[K]>> {
  return Object.fromEntries(
    CATALOG_ENTRIES.flatMap(([code, entry]) =>
      entry[key] ? [[code, entry[key]]] : [],
    ),
  ) as Record<string, NonNullable<ReasonCodeCatalogSourceEntry[K]>>;
}

export const REASON_CODE_CATALOG: Record<string, ReasonCodeCatalogEntry> =
  Object.fromEntries(
    CATALOG_ENTRIES.map(([code, entry]) => [code, { code, ...entry }]),
  );

export const SHELL_REASON_CODES = buildCodes("shell");

export const PUBLIC_REASON_CODES = buildCodes("public");

export const REPORT_REASON_CODES = buildCodes("report");

export const SHELL_REASON_CODE_READINGS = buildProjection("shell");

export const PUBLIC_REASON_CODE_READINGS = buildProjection("public");

export const REPORT_REASON_COPY = buildProjection("report");
