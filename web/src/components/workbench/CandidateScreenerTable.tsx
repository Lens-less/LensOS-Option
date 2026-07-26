import { useEffect, useRef, useState } from "react";

import { dte as formatDteValue, instrumentOf, money, signTone } from "../candidate/format";
import {
  EV_UNAVAILABLE,
  structureLabel,
  tierLabel,
  tierTone,
} from "../candidate/vocabulary";
import type { CandidateViewRow, SortKey, SortState } from "./candidateModel";

const COLUMNS: Array<{ key: SortKey; label: string }> = [
  { key: "structureType", label: "合约 / 结构" },
  { key: "action", label: "研究分层" },
  { key: "dteDays", label: "DTE" },
  { key: "executableCreditUsdc", label: "可成交信用" },
  { key: "evAfterCostUsdc", label: "税后 EV" },
  { key: "rankingScore", label: "排序分" },
];

/**
 * Rendering every row of a live chain produced a page tens of thousands of
 * pixels tall. The cap is generous enough that sorting still reaches what the
 * reader is looking for, and the remainder is always announced rather than
 * dropped.
 */
const INITIAL_ROW_CAP = 60;


function evCellContent(row: CandidateViewRow): React.JSX.Element {
  if (!row.hasValidatedEv) {
    return <span className="ev-unavailable">{EV_UNAVAILABLE}</span>;
  }
  return <>{money(row.evAfterCostUsdc)}</>;
}

function evSign(row: CandidateViewRow): "positive" | "negative" | undefined {
  return row.hasValidatedEv ? signTone(row.evAfterCostUsdc) : undefined;
}

export function CandidateScreenerTable({
  onSelect,
  onSortChange,
  rows,
  selectedId,
  sort,
}: {
  onSelect: (id: string) => void;
  onSortChange: (key: SortKey) => void;
  rows: CandidateViewRow[];
  selectedId: string | null;
  sort: SortState | null;
}): React.JSX.Element {
  const [activeIndex, setActiveIndex] = useState(0);
  const [cap, setCap] = useState(INITIAL_ROW_CAP);
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([]);

  const visibleRows = rows.slice(0, cap);
  const hiddenCount = rows.length - visibleRows.length;

  useEffect(() => {
    setCap(INITIAL_ROW_CAP);
  }, [rows]);

  useEffect(() => {
    if (activeIndex >= visibleRows.length) {
      setActiveIndex(Math.max(0, visibleRows.length - 1));
    }
  }, [activeIndex, visibleRows.length]);

  const focusRow = (index: number) => {
    const clamped = Math.max(0, Math.min(visibleRows.length - 1, index));
    setActiveIndex(clamped);
    rowRefs.current[clamped]?.focus();
  };

  const handleRowKeyDown = (
    event: React.KeyboardEvent<HTMLTableRowElement>,
    index: number,
  ) => {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusRow(index + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        focusRow(index - 1);
        break;
      case "Home":
        event.preventDefault();
        focusRow(0);
        break;
      case "End":
        event.preventDefault();
        focusRow(rows.length - 1);
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        onSelect(rows[index].id);
        break;
      default:
        break;
    }
  };

  return (
    <div
      aria-label="研究候选筛选表格"
      className="candidate-screener-table-scroll"
      role="region"
    >
      <table className="candidate-screener-table">
        <thead>
          <tr>
            {COLUMNS.map((column) => {
              const isSorted = sort !== null && sort.key === column.key;
              return (
                <th
                  aria-sort={
                    isSorted && sort
                      ? sort.direction === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                  key={column.key}
                  scope="col"
                >
                  <button
                    className="sortable-column-button"
                    onClick={() => onSortChange(column.key)}
                    type="button"
                  >
                    {column.label}
                    <span aria-hidden="true">
                      {isSorted && sort
                        ? sort.direction === "asc"
                          ? " ▲"
                          : " ▼"
                        : ""}
                    </span>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {visibleRows.map((row, index) => (
            <tr
              aria-selected={row.id === selectedId}
              data-tier={row.action}
              key={row.id}
              onClick={() => {
                setActiveIndex(index);
                onSelect(row.id);
              }}
              onKeyDown={(event) => handleRowKeyDown(event, index)}
              ref={(element) => {
                rowRefs.current[index] = element;
              }}
              tabIndex={index === activeIndex ? 0 : -1}
            >
              <td className="instrument-cell">
                <strong>{instrumentOf(row.id)}</strong>
                <small>{structureLabel(row.structureType)}</small>
              </td>
              <td>
                <span className="tier-badge" data-tone={tierTone(row.action)}>
                  {tierLabel(row.action)}
                </span>
              </td>
              <td className="numeric-cell">{formatDteValue(row.dteDays)}</td>
              <td className="numeric-cell">
                {money(row.executableCreditUsdc)}
              </td>
              <td className="numeric-cell" data-sign={evSign(row)}>
                {evCellContent(row)}
              </td>
              <td className="numeric-cell">
                {row.rankingScore === null ? "—" : row.rankingScore.toFixed(3)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {hiddenCount > 0 ? (
        <div className="table-more">
          <p>
            另有 {hiddenCount.toLocaleString("zh-CN")} 行未显示
          </p>
          <button onClick={() => setCap((current) => current + INITIAL_ROW_CAP)} type="button">
            再显示 {Math.min(hiddenCount, INITIAL_ROW_CAP)} 行
          </button>
        </div>
      ) : null}
    </div>
  );
}
