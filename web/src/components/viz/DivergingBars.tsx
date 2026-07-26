import { useId, useState } from "react";

import { MARK, VIZ, toneFor } from "./tokens";

export interface DivergingRow {
  key: string;
  label: string;
  value: number | null;
  /** Shown in the tooltip and the table view; never required to read the bar. */
  note?: string;
}

function niceBound(rows: DivergingRow[]): number {
  const magnitudes = rows
    .map((row) => (row.value === null ? 0 : Math.abs(row.value)))
    .filter((value) => Number.isFinite(value));
  const peak = Math.max(...magnitudes, 0);
  if (peak <= 0) {
    return 1;
  }
  const exponent = Math.floor(Math.log10(peak));
  const step = 10 ** exponent;
  return Math.ceil(peak / step) * step;
}

/**
 * Signed values against a zero baseline.
 *
 * Everything this product charts is a polarity question — is this expected
 * value above or below zero, is this book long or short vega — so the bars grow
 * from a centred baseline and the diverging pair carries the sign. The sign is
 * also printed on every label, because a reader who cannot separate the two
 * hues still has to be able to read the chart.
 *
 * A row whose value is unavailable renders as an explicit gap with its reason,
 * never as a zero-length bar, which would read as "zero".
 */
export function DivergingBars({
  ariaLabel,
  format,
  referenceLines = [],
  rows,
  unit,
}: {
  ariaLabel: string;
  format: (value: number) => string;
  /** Thresholds the reader is judging against, drawn as hairlines. */
  referenceLines?: Array<{ value: number; label: string }>;
  rows: DivergingRow[];
  unit?: string;
}): React.JSX.Element {
  const titleId = useId();
  const [hovered, setHovered] = useState<string | null>(null);

  const bound = Math.max(
    niceBound(rows),
    ...referenceLines.map((line) => Math.abs(line.value)),
  );
  const rowHeight = 34;
  const barThickness = Math.min(MARK.maxBarThickness, 18);
  // Sized to the longest label rather than fixed. These labels are snake_case
  // identifiers, and a fixed column silently clipped the longest of them — the
  // reader then sees a name that does not exist.
  const longestLabel = rows.reduce(
    (longest, row) => Math.max(longest, row.label.length),
    0,
  );
  const labelWidth = Math.min(Math.max(longestLabel * 7.2 + 24, 140), 300);
  const valueWidth = 104;
  const plotWidth = 320;
  const width = labelWidth + plotWidth + valueWidth;
  const height = rows.length * rowHeight + 24;
  const centre = labelWidth + plotWidth / 2;

  const scale = (value: number) => (value / bound) * (plotWidth / 2);

  return (
    <figure className="viz-figure">
      <svg
        aria-labelledby={titleId}
        className="viz-svg"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <title id={titleId}>{ariaLabel}</title>

        {/* Hairline, solid, recessive. */}
        <line
          stroke={VIZ.axis}
          strokeWidth={1}
          x1={centre}
          x2={centre}
          y1={4}
          y2={height - 20}
        />

        {referenceLines.map((line) => (
          <g key={line.label}>
            <line
              stroke={VIZ.grid}
              strokeWidth={1}
              x1={centre + scale(line.value)}
              x2={centre + scale(line.value)}
              y1={4}
              y2={height - 20}
            />
            <text
              fill={VIZ.muted}
              fontSize={10}
              textAnchor="middle"
              x={centre + scale(line.value)}
              y={height - 6}
            >
              {line.label}
            </text>
          </g>
        ))}

        {rows.map((row, index) => {
          const y = index * rowHeight + 8;
          const midline = y + rowHeight / 2 - 4;
          if (row.value === null) {
            return (
              <g key={row.key}>
                <text
                  dominantBaseline="middle"
                  fill={VIZ.inkSoft}
                  fontSize={12}
                  textAnchor="end"
                  x={labelWidth - 12}
                  y={midline}
                >
                  {row.label}
                </text>
                <text
                  dominantBaseline="middle"
                  fill={VIZ.muted}
                  fontSize={11}
                  x={centre + 8}
                  y={midline}
                >
                  {row.note ?? "未评估"}
                </text>
              </g>
            );
          }

          const extent = scale(row.value);
          const x = row.value >= 0 ? centre : centre + extent;
          const barWidth = Math.max(Math.abs(extent), 1);
          return (
            <g
              key={row.key}
              onMouseEnter={() => setHovered(row.key)}
              onMouseLeave={() => setHovered(null)}
            >
              {/* Hit target is the whole band, not the bar. */}
              <rect
                fill="transparent"
                height={rowHeight}
                width={width}
                x={0}
                y={y - 4}
              />
              <text
                dominantBaseline="middle"
                fill={hovered === row.key ? VIZ.ink : VIZ.inkSoft}
                fontSize={12}
                textAnchor="end"
                x={labelWidth - 12}
                y={midline}
              >
                {row.label}
              </text>
              <rect
                fill={toneFor(row.value)}
                height={barThickness}
                rx={MARK.cornerRadius}
                width={barWidth}
                x={x}
                y={midline - barThickness / 2}
              />
              {/* Square the end that meets the baseline: only the data-end is
                  rounded, so the bar reads as growing from zero. */}
              <rect
                fill={toneFor(row.value)}
                height={barThickness}
                width={Math.min(MARK.cornerRadius, barWidth)}
                x={row.value >= 0 ? centre : centre - MARK.cornerRadius}
                y={midline - barThickness / 2}
              />
              <text
                dominantBaseline="middle"
                fill={VIZ.ink}
                fontSize={12}
                style={{ fontVariantNumeric: "tabular-nums" }}
                x={labelWidth + plotWidth + 12}
                y={midline}
              >
                {format(row.value)}
              </text>
            </g>
          );
        })}

        <text fill={VIZ.muted} fontSize={10} x={centre - 4} y={height - 6}>
          0
        </text>
        {unit ? (
          <text
            fill={VIZ.muted}
            fontSize={10}
            textAnchor="end"
            x={width}
            y={height - 6}
          >
            {unit}
          </text>
        ) : null}
      </svg>

      {/* The table twin: every value is reachable without the chart. */}
      <details className="viz-table">
        <summary>表格视图</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">项</th>
              <th scope="col">值</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <th scope="row">{row.label}</th>
                <td>
                  {row.value === null
                    ? (row.note ?? "未评估")
                    : format(row.value)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
