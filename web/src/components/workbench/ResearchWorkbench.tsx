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
import { ReasonCodeNotice } from "../shell/ReasonCodeNotice";
import { CombinationRiskPanel } from "./CombinationRiskPanel";

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

  const hiddenByTier = allRows.filter(
    (row) => !filters.actionTiers.includes(row.action),
  ).length;

  const body = (
    <main className="workbench-console" id={embedded ? "surface-main" : "workbench-main"}>
      {/* The table is the product, so everything that is not the table is
          compressed into one line above it or folded away below it. The page
          used to spend roughly 700px on headings and status strips before the
          first candidate, which put every row below the fold on a laptop. */}
      <div className="workbench-bar">
        <div>
          <p className="section-kicker">EV candidate scanner / 候选工作台</p>
          <h1>候选筛选</h1>
        </div>
        <p className="workbench-bar-note">
          分层由服务端判定；筛选只缩小范围，不改变分层。
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
            reasonCode={scanner?.reason_code ?? null}
            status={status}
          />
          <ReasonCodeNotice
            codes={[
              ...(scanner?.reason_code ? [scanner.reason_code] : []),
              ...(report.reason_codes ?? []),
            ]}
            heading="需要补齐什么"
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
              <span>{scanner?.score_status ?? "UNAVAILABLE"}</span>
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
            <dt>外部发布授权</dt>
            <dd>
              {report.full_system_surface?.release_readiness?.status ?? "NO-GO"}
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
      {body}
      <footer className="page-footer">
        <span>LensOS Option · research only</span>
        <p>真实市场数据用于研究阅读；页面不连接下单与自动执行。</p>
      </footer>
    </div>
  );
}
