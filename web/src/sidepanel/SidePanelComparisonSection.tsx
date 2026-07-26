import React from "react";
import type { ContractComparison, ContractComparisonRow } from "../report";
import { signed as signedNumber } from "../components/candidate/format";
import { tierLabel as actionLabel } from "../components/candidate/vocabulary";

const MAX_VISIBLE_ROWS = 8;


function arrowFor(value: number | null): string {
  if (value === null || value === 0) {
    return "→";
  }
  return value > 0 ? "▲" : "▼";
}


function formatEv(value: number | null): string {
  if (value === null) {
    return "未评估（缺少已验证路径风险）";
  }
  return `${signedNumber(value, { digits: 2 })} USDC`;
}

function formatReferenceCredit(value: number | null): string {
  if (value === null) {
    return "未知";
  }
  return `${value.toFixed(0)} USDC 参考信用`;
}

interface DeltaMetric {
  key: string;
  label: string;
  value: number | null;
  unit: string;
}

/** At most 3 signed deltas, and only for metrics both rows actually have. */
function buildDeltas(
  current: ContractComparisonRow | undefined,
  alternative: ContractComparisonRow,
): DeltaMetric[] {
  if (!current) {
    return [];
  }
  const candidates: DeltaMetric[] = [
    {
      key: "ranking_score",
      label: "相对价值",
      value:
        current.rankingScore !== null && alternative.rankingScore !== null
          ? alternative.rankingScore - current.rankingScore
          : null,
      unit: "IV pts",
    },
    {
      key: "ev",
      label: "税费后期望值",
      value: alternative.deltaVsCurrent,
      unit: "USDC",
    },
    {
      key: "credit",
      label: "参考信用",
      value:
        current.executableCreditUsdc !== null &&
        alternative.executableCreditUsdc !== null
          ? alternative.executableCreditUsdc - current.executableCreditUsdc
          : null,
      unit: "USDC",
    },
  ];
  return candidates.filter((delta) => delta.value !== null).slice(0, 3);
}

/**
 * "Does the contract I'm looking at have edge, and is there a better one on
 * this chain?" This section only ever answers with a research rank: no row
 * carries a quantity, a price to submit, or any control that could be read
 * as an order. Clicking a row re-targets the rest of the panel at that
 * candidate through the existing manual-instrument input; it never messages
 * the engine or a trading surface.
 */
export function SidePanelComparisonSection({
  comparison,
  onSelectInstrument,
}: {
  comparison: ContractComparison | null;
  onSelectInstrument: (instrument: string) => void;
}): React.JSX.Element | null {
  if (!comparison || comparison.rows.length === 0) {
    return null;
  }

  const {
    rows,
    currentRank,
    totalRanked,
    rankingDimensions,
    absoluteEvAvailable,
  } = comparison;
  const currentRow = rows.find((row) => row.isCurrent);
  const topAlternative = rows.find((row) => !row.isCurrent) ?? null;
  const hasCurrent = currentRank !== null;

  const rankLineText = hasCurrent
    ? `当前合约排名 第 ${currentRank} / ${totalRanked}`
    : `尚未定位当前合约 · 本链共 ${totalRanked} 个候选`;

  const deltas = topAlternative ? buildDeltas(currentRow, topAlternative) : [];

  return (
    <section aria-label="同链候选排名对比" className="panel-card panel-comparison">
      <header className="panel-card-header">
        <div>
          <p className="panel-section-kicker">Chain comparison</p>
          <h2>同链排名对比</h2>
        </div>
        {absoluteEvAvailable ? null : (
          <span className="panel-badge panel-badge-muted">
            EV 未验证
          </span>
        )}
      </header>

      <p aria-live="polite" className="panel-rank-line">
        {rankLineText}
      </p>

      {rankingDimensions.length > 0 ? (
        <p className="panel-meta">
          排序依据：{rankingDimensions.join(" · ")}（帕累托前沿 + 字典序打破平局，不做加权求和）
        </p>
      ) : null}

      {topAlternative ? (
        <div className="panel-top-alternative">
          <p className="panel-meta">
            {hasCurrent ? "最佳替代候选" : "当前排名第一的候选"}
          </p>
          <strong className="panel-comparison-label">
            {topAlternative.label}
          </strong>
          <span className="panel-badge">
            {actionLabel(topAlternative.action)}
          </span>
          {deltas.length > 0 ? (
            <ul className="panel-delta-list">
              {deltas.map((delta) => (
                <li key={delta.key}>
                  <span aria-hidden="true">{arrowFor(delta.value)}</span>{" "}
                  <span>
                    {`${delta.label} ${signedNumber(delta.value, { digits: 1 })} ${delta.unit}`}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="panel-meta">
              EV：{formatEv(topAlternative.ev)} · 参考信用：
              {formatReferenceCredit(topAlternative.executableCreditUsdc)}
            </p>
          )}
        </div>
      ) : null}

      <details className="panel-comparison-details" open={!hasCurrent}>
        <summary>
          查看全部 {totalRanked} 个候选（研究排名，非下单指令）
        </summary>
        <ul className="panel-comparison-list" role="list">
          {rows.slice(0, MAX_VISIBLE_ROWS).map((row) => (
            <li key={row.candidateId ?? `rank-${row.rank}`}>
              <button
                className={`panel-comparison-row${
                  row.isCurrent ? " is-current" : ""
                }`}
                disabled={!row.primaryInstrument}
                onClick={() => {
                  if (row.primaryInstrument) {
                    onSelectInstrument(row.primaryInstrument);
                  }
                }}
                type="button"
              >
                <span className="panel-comparison-rank">#{row.rank}</span>
                <span className="panel-comparison-body">
                  <strong>{row.label}</strong>
                  <span className="panel-meta">
                    {actionLabel(row.action)} · EV {formatEv(row.ev)}
                  </span>
                </span>
                {row.isCurrent ? (
                  <span className="panel-chip panel-chip-current">当前</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
