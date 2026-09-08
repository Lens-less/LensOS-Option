import { useEffect, useMemo, useRef, useState } from "react";

import type { ResearchReport } from "../../contracts";
import { isInformationalReason } from "../../reasonCodes/catalog";
import { Masthead } from "../evidence/Shell";
import {
  finiteNumber,
  friendlySource,
  marketDisplayState,
  reportFreshness,
} from "../evidence/reportModel";
import { CandidateDetailPanel } from "./CandidateDetailPanel";
import { CandidateScreenerTable } from "./CandidateScreenerTable";
import {
  candidateRows,
  evCandidateScannerOf,
  researchRankingValueLabel,
  scannerStatus,
  sortCandidateRows,
  structureTypeOptions,
} from "./candidateModel";
import type { SortKey, SortState } from "./candidateModel";
import {
  applyFilters,
  decodeFilters,
  defaultFilters,
  encodeFilters,
  isDefaultFilters,
} from "./filterModel";
import type { ScreenerFilters } from "./filterModel";
import { ScreenerBlockedState } from "./ScreenerBlockedState";
import { ScreenerControls } from "./ScreenerControls";
import { ScreenerEmptyState } from "./ScreenerEmptyState";
import { ScoreProvenance } from "./ScoreProvenance";
import { ReasonCodeNotice } from "../shell/ReasonCodeNotice";
import { CombinationRiskPanel } from "./CombinationRiskPanel";
import { SiteFooter } from "../shell/SiteFooter";

const FILTER_PARAM_KEYS = [
  "structure",
  "dteMin",
  "dteMax",
  "deltaMin",
  "deltaMax",
  "minCredit",
  "tiers",
] as const;

function readUrlState(): {
  filters: ScreenerFilters;
  selectedId: string | null;
} {
  if (typeof window === "undefined") {
    return { filters: defaultFilters(), selectedId: null };
  }
  const params = new URLSearchParams(window.location.search);
  return {
    filters: decodeFilters(params),
    selectedId: params.get("candidate"),
  };
}

function writeUrlState(filters: ScreenerFilters, selectedId: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  const params = new URLSearchParams(window.location.search);
  for (const key of FILTER_PARAM_KEYS) {
    params.delete(key);
  }
  for (const [key, value] of encodeFilters(filters).entries()) {
    params.set(key, value);
  }
  if (selectedId) {
    params.set("candidate", selectedId);
  } else {
    params.delete("candidate");
  }
  params.set("view", "workbench");
  const query = params.toString();
  const nextUrl = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  window.history.replaceState(window.history.state, "", nextUrl);
}

export interface ResearchWorkbenchProps {
  nowMs: number;
  onRefresh?: () => void;
  receivedAtMs: number;
  refreshing?: boolean;
  report: ResearchReport;
  /** Rendered inside `AppShell`, which already carries the chrome. */
  embedded?: boolean;
}

export function ResearchWorkbench({
  report,
  receivedAtMs,
  nowMs,
  onRefresh,
  refreshing = false,
  embedded = false,
}: ResearchWorkbenchProps): React.JSX.Element {
  const initialUrlState = useMemo(() => readUrlState(), []);
  const [filters, setFilters] = useState<ScreenerFilters>(
    initialUrlState.filters,
  );
  const [selectedId, setSelectedId] = useState<string | null>(
    initialUrlState.selectedId,
  );
  const [sort, setSort] = useState<SortState | null>(null);
  const [announcedCount, setAnnouncedCount] = useState<string>("");

  const lastFocusedRef = useRef<HTMLElement | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const mainHeadingRef = useRef<HTMLHeadingElement>(null);
  const previousSelectionRef = useRef<string | null>(null);

  const status = scannerStatus(report);
  const scanner = evCandidateScannerOf(report);
  const freshness = reportFreshness(report, receivedAtMs, nowMs);
  const displayState = marketDisplayState(report, freshness);
  const isBlockedStatus =
    displayState !== "available" || status === "unavailable" || status === "blocked";
  const isPublished = report.runtime_context?.mode === "published";
  const source = friendlySource(report.data_status?.source);
  const spotUsdc = finiteNumber(report.strategy_research?.analysis?.market?.spot_usd);

  const allRows = useMemo(
    () => isBlockedStatus ? [] : candidateRows(report),
    [report, isBlockedStatus],
  );
  const structureOptions = useMemo(
    () => structureTypeOptions(allRows),
    [allRows],
  );
  const filteredRows = useMemo(
    () => applyFilters(allRows, filters),
    [allRows, filters],
  );
  const visibleRows = useMemo(
    () => (sort ? sortCandidateRows(filteredRows, sort) : filteredRows),
    [filteredRows, sort],
  );

  const selectedRow = filteredRows.find((row) => row.id === selectedId) ?? null;
  const visibleSelectedId = selectedRow?.id ?? null;

  useEffect(() => {
    const handlePopState = () => {
      const next = readUrlState();
      setFilters(next.filters);
      setSelectedId(next.selectedId);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    writeUrlState(filters, visibleSelectedId);
  }, [filters, visibleSelectedId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAnnouncedCount(
        `${filteredRows.length} / ${allRows.length} 个候选通过当前筛选`,
      );
    }, 300);
    return () => {
      window.clearTimeout(timer);
    };
  }, [filteredRows.length, allRows.length]);

  useEffect(() => {
    const previousSelection = previousSelectionRef.current;
    previousSelectionRef.current = visibleSelectedId;
    if (visibleSelectedId) {
      headingRef.current?.focus();
    } else if (previousSelection) {
      // A removed detail leaves focus on body. Preserve a user's focus in
      // filters or navigation, and fall back when its original row is gone.
      if (document.activeElement === document.body) {
        const returnTarget = lastFocusedRef.current?.isConnected
          ? lastFocusedRef.current
          : mainHeadingRef.current;
        returnTarget?.focus();
      }
      lastFocusedRef.current = null;
    }
  }, [visibleSelectedId]);

  useEffect(() => {
    if (selectedId && !visibleSelectedId) {
      setSelectedId(null);
    }
  }, [selectedId, visibleSelectedId]);

  const handleSelect = (id: string, source: HTMLElement) => {
    lastFocusedRef.current = source;
    setSelectedId(id);
  };

  const handleClose = () => {
    setSelectedId(null);
  };

  const handleSortChange = (key: SortKey) => {
    setSort((current) => {
      if (!current || current.key !== key) {
        return { key, direction: "asc" };
      }
      if (current.direction === "asc") {
        return { key, direction: "desc" };
      }
      return null;
    });
  };

  const resetFilters = () => {
    setFilters(defaultFilters());
  };

  const blockedScannerStatus: "blocked" | "unavailable" =
    status === "blocked" ? "blocked" : "unavailable";
  const staleReasonCode = isPublished
    ? "PUBLISHED_EDITION_STALE"
    : "MARKET_DATA_AGE_EXCEEDED";
  const marketBlockingReasonCode = displayState === "stale"
    ? staleReasonCode
    : displayState === "quality_blocked"
      ? (report.data_status?.reason_code || "MISSING_VALIDATED_MARKET_DATA")
      : null;

  const hiddenByTier = allRows.filter(
    (row) => !filters.actionTiers.includes(row.action),
  ).length;

  const reasonCodes = Array.from(
    new Set([
      ...(marketBlockingReasonCode ? [marketBlockingReasonCode] : []),
      ...(report.data_status?.reason_code ? [report.data_status.reason_code] : []),
      ...(scanner?.reason_code ? [scanner.reason_code] : []),
      ...(report.reason_codes ?? []),
    ].filter(Boolean)),
  );
  const informationalCodes = reasonCodes.filter(isInformationalReason);

  const body = (
    <main className="workbench-console" id={embedded ? "surface-main" : "workbench-main"}>
      {/* The table is the product, so everything that is not the table is
          compressed into one line above it or folded away below it. The page
          used to spend roughly 700px on headings and status strips before the
          first candidate, which put every row below the fold on a laptop. */}
      <div className="workbench-bar">
        <div>
          <p className="section-kicker">EV candidate scanner / 候选工作台</p>
          <h1 ref={mainHeadingRef} tabIndex={-1}>候选筛选</h1>
        </div>
        <p className="workbench-bar-note">
          分层由服务端判定；筛选只缩小范围，不改变分层。排序先看前沿位置，再按支配轴细排。
        </p>
      </div>

      {isBlockedStatus ? (
        <>
          <ScreenerControls
            disabled
            filters={filters}
            onChange={setFilters}
            onReset={resetFilters}
            structureOptions={structureOptions}
          />
          <ScreenerBlockedState
            reasonCode={marketBlockingReasonCode ?? scanner?.reason_code ?? null}
            status={displayState !== "available" ? "blocked" : blockedScannerStatus}
          />
          {freshness.phase === "unavailable" ? (
            <p>
              无法核验行情时效：本次报告未提供有效的行情年龄。请重新获取完整报告；无法确定时效的快照不会用于候选展示。
            </p>
          ) : null}
          <ReasonCodeNotice
            codes={reasonCodes.filter((code) => !isInformationalReason(code))}
            heading="需要补齐什么"
            showNextSteps
          />
          {informationalCodes.length > 0 ? (
            <details>
              <summary>正常状态（{informationalCodes.length} 项）</summary>
              <ReasonCodeNotice codes={informationalCodes} heading="正常状态说明" />
            </details>
          ) : null}
        </>
      ) : (
        <>
          <ScreenerControls
            filters={filters}
            onChange={setFilters}
            onReset={resetFilters}
            structureOptions={structureOptions}
          />
          <p aria-live="polite" className="screener-result-count" role="status">
            <strong>{visibleRows.length.toLocaleString("zh-CN")}</strong> /{" "}
            {allRows.length.toLocaleString("zh-CN")} 个候选
            {hiddenByTier > 0 ? (
              <span className="screener-hidden-note">
                · 已按分层隐藏 {hiddenByTier.toLocaleString("zh-CN")} 个
              </span>
            ) : null}
            <span className="visually-hidden">{announcedCount}</span>
          </p>
          {visibleRows.length === 0 ? (
            <ScreenerEmptyState
              onReset={resetFilters}
              showReset={!isDefaultFilters(filters)}
              totalCount={allRows.length}
              visibleCount={visibleRows.length}
            />
          ) : (
            <CandidateScreenerTable
              onSelect={handleSelect}
              onSortChange={handleSortChange}
              rows={visibleRows}
              selectedId={selectedId}
              sort={sort}
            />
          )}
          {selectedRow ? (
            <CandidateDetailPanel
              headingRef={headingRef}
              hideExecutionDetails={isPublished}
              onClose={handleClose}
              report={report}
              row={selectedRow}
              spotUsdc={spotUsdc}
            />
          ) : null}

          <CombinationRiskPanel report={report} spotUsdc={spotUsdc} />

          {/* Provenance belongs with the ranking it qualifies, but it is read
              once and then trusted, so it sits below the table rather than
              between the reader and it. */}
          <details className="workbench-provenance">
            <summary>
              排序口径与打分状态
              <span>{researchRankingValueLabel(scanner?.score_status)}</span>
            </summary>
            <ScoreProvenance scanner={scanner} />
          </details>
        </>
      )}
    </main>
  );

  if (embedded) {
    return body;
  }

  return (
    <div className="app-shell workbench-shell">
      <a className="skip-link" href="#workbench-main">
        跳到主要内容
      </a>
      <Masthead
        freshness={freshness}
        onRefresh={onRefresh}
        refreshing={refreshing}
        source={source}
      />
      {/* Embedded, `AppShell` states this once for both views. Mounted alone,
          the workbench must still carry it: this is where ranked candidates
          and expected values are read, and a boundary that depends on the
          mounting context is not a boundary. */}
      <section className="truth-strip" aria-label="三项运行边界">
        <dl>
          <div data-tone="danger">
            <dt>执行边界</dt>
            <dd>RESEARCH_ONLY · NO_TRADE</dd>
          </div>
          <div data-tone="warning">
            <dt>排序口径</dt>
            <dd>{researchRankingValueLabel(scanner?.score_status)}</dd>
          </div>
        </dl>
      </section>
      {body}
      <SiteFooter />
    </div>
  );
}
