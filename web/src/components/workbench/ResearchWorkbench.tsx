import { useEffect, useMemo, useRef, useState } from "react";

import type { ResearchReport } from "../../contracts";
import { Masthead } from "../evidence/Shell";
import {
  finiteNumber,
  friendlySource,
  reportFreshness,
} from "../evidence/reportModel";
import { CandidateDetailPanel } from "./CandidateDetailPanel";
import { CandidateScreenerTable } from "./CandidateScreenerTable";
import {
  candidateById,
  candidateRows,
  evCandidateScannerOf,
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
}

export function ResearchWorkbench({
  report,
  receivedAtMs,
  nowMs,
  onRefresh,
  refreshing = false,
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

  const status = scannerStatus(report);
  const scanner = evCandidateScannerOf(report);
  const freshness = reportFreshness(report, receivedAtMs, nowMs);
  const source = friendlySource(report.data_status?.source);
  const spotUsdc = finiteNumber(report.strategy_research?.analysis?.market?.spot_usd);

  const allRows = useMemo(() => candidateRows(report), [report]);
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

  const selectedRow = selectedId ? candidateById(report, selectedId) : null;

  useEffect(() => {
    writeUrlState(filters, selectedId);
  }, [filters, selectedId]);

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
    if (selectedRow && headingRef.current) {
      headingRef.current.focus();
    } else if (!selectedRow && lastFocusedRef.current) {
      lastFocusedRef.current.focus();
      lastFocusedRef.current = null;
    }
  }, [selectedRow]);

  useEffect(() => {
    if (selectedId && !candidateById(report, selectedId)) {
      setSelectedId(null);
    }
  }, [report, selectedId]);

  const handleSelect = (id: string) => {
    lastFocusedRef.current = document.activeElement as HTMLElement | null;
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

  const isBlockedStatus = status === "unavailable" || status === "blocked";

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
      <main className="workbench-console" id="workbench-main">
        <header className="research-section-heading workbench-heading">
          <div>
            <p className="section-kicker">EV candidate scanner / 研究工作台</p>
            <h1>候选筛选研究工作台</h1>
          </div>
          <p>
            所有分层由服务端判定；本页筛选器只能在同一分层内缩小范围，不能把候选提升为更高研究等级。
          </p>
        </header>

        {/* This is the surface where ranked candidates and expected values are
            read, so the release state and execution boundary must be visible
            here too — not only on the evidence console. */}
        <section className="truth-strip" aria-label="三项运行边界">
          <dl>
            <div data-tone="danger">
              <dt>外部发布授权</dt>
              <dd>
                {report.full_system_surface?.release_readiness?.status ??
                  "NO-GO"}
              </dd>
            </div>
            <div data-tone="danger">
              <dt>执行边界</dt>
              <dd>RESEARCH_ONLY · NO_TRADE</dd>
            </div>
            <div data-tone="warning">
              <dt>打分状态</dt>
              <dd>{scanner?.score_status ?? "UNAVAILABLE"}</dd>
            </div>
          </dl>
        </section>

        <ScoreProvenance scanner={scanner} />

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
              reasonCode={scanner?.reason_code ?? null}
              status={status}
            />
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
              {announcedCount}
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
                onClose={handleClose}
                report={report}
                row={selectedRow}
                spotUsdc={spotUsdc}
              />
            ) : null}
          </>
        )}
      </main>
      <footer className="page-footer">
        <span>LensOS Option · research only</span>
        <p>真实市场数据用于研究阅读；页面不连接下单与自动执行。</p>
      </footer>
    </div>
  );
}
