import { useId, useState } from "react";

import { VIZ } from "./tokens";

export interface HeatmapCell {
  date: string;
  present: boolean;
  value: number | null;
}

export interface HeatmapRow {
  key: string;
  label: string;
  sublabel?: string;
  cells: HeatmapCell[];
}

/**
 * Instrument by capture date, coloured by standardized residual.
 *
 * The value is signed with a meaningful zero, so the scale is diverging rather
 * than sequential: a strike reading two standard errors rich and one reading two
 * cheap are opposite facts, not two magnitudes.
 *
 * The one trap this form has here is that "we looked and it was about zero" and
 * "we did not look" would both land on the neutral midpoint. They are different
 * facts, and the second is common — the collector selects about a hundred of
 * several hundred listed instruments and which ones move with spot. Absent cells
 * are therefore drawn as empty outlines rather than filled, and the legend names
 * them.
 */
export function ResidualHeatmap({
  ariaLabel,
  dates,
  onSelect,
  rows,
  selectedKey,
}: {
  ariaLabel: string;
  dates: string[];
  onSelect?: (key: string) => void;
  rows: HeatmapRow[];
  selectedKey?: string | null;
}): React.JSX.Element | null {
  const titleId = useId();
  const [hover, setHover] = useState<{
    row: HeatmapRow;
    cell: HeatmapCell;
  } | null>(null);

  if (rows.length === 0 || dates.length === 0) {
    return null;
  }

  const cell = 14;
  const gap = 2;
  const labelWidth = 190;
  const headerHeight = 20;
  const width = labelWidth + dates.length * (cell + gap);
  const height = headerHeight + rows.length * (cell + gap) + 24;

  // Scale is capped rather than fitted to the extreme: one outlier day would
  // otherwise wash every other cell to near-neutral.
  const bound = 2;
  const intensity = (value: number) =>
    Math.min(Math.abs(value) / bound, 1) * 0.85 + 0.15;

  const tickEvery = Math.max(1, Math.ceil(dates.length / 8));

  return (
    <figure className="viz-figure">
      <div className="heatmap-scroll">
        <svg
          aria-labelledby={titleId}
          className="viz-svg heatmap-svg"
          role="img"
          style={{ minWidth: width }}
          viewBox={`0 0 ${width} ${height}`}
        >
          <title id={titleId}>{ariaLabel}</title>

          {dates.map((date, column) =>
            column % tickEvery === 0 ? (
              <text
                fill={VIZ.muted}
                fontSize={9}
                key={date}
                textAnchor="start"
                x={labelWidth + column * (cell + gap)}
                y={headerHeight - 8}
              >
                {date.slice(5)}
              </text>
            ) : null,
          )}

          {rows.map((row, index) => {
            const y = headerHeight + index * (cell + gap);
            const selected = row.key === selectedKey;
            return (
              <g key={row.key}>
                <rect
                  fill={selected ? VIZ.grid : "transparent"}
                  height={cell}
                  onClick={() => onSelect?.(row.key)}
                  style={{ cursor: onSelect ? "pointer" : undefined }}
                  width={width}
                  x={0}
                  y={y}
                />
                <text
                  dominantBaseline="middle"
                  fill={selected ? VIZ.ink : VIZ.inkSoft}
                  fontSize={10}
                  onClick={() => onSelect?.(row.key)}
                  style={{
                    cursor: onSelect ? "pointer" : undefined,
                    fontWeight: selected ? 600 : 400,
                  }}
                  textAnchor="end"
                  x={labelWidth - 10}
                  y={y + cell / 2}
                >
                  {row.label}
                </text>
                {row.cells.map((item, column) => {
                  const x = labelWidth + column * (cell + gap);
                  if (!item.present || item.value === null) {
                    // Not filled: an absent capture must not look like a
                    // reading of zero.
                    return (
                      <rect
                        fill="none"
                        height={cell}
                        key={item.date}
                        stroke={VIZ.grid}
                        strokeWidth={1}
                        width={cell}
                        x={x}
                        y={y}
                      />
                    );
                  }
                  return (
                    <rect
                      fill={item.value >= 0 ? VIZ.positive : VIZ.negative}
                      fillOpacity={intensity(item.value)}
                      height={cell}
                      key={item.date}
                      onMouseEnter={() => setHover({ row, cell: item })}
                      onMouseLeave={() => setHover(null)}
                      width={cell}
                      x={x}
                      y={y}
                    />
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>

      <p className="viz-readout" role="status">
        {hover ? (
          <>
            {hover.row.label} · {hover.cell.date} ·{" "}
            <strong>
              {hover.cell.value === null
                ? "未采集"
                : `${hover.cell.value > 0 ? "+" : ""}${hover.cell.value.toFixed(2)} σ`}
            </strong>
          </>
        ) : (
          <span className="viz-readout-idle">
            悬停读取单个格子，点击行查看该合约的时间序列
          </span>
        )}
      </p>

      <ul className="viz-legend heatmap-legend">
        <li>
          <span style={{ background: VIZ.positive, opacity: 0.9 }} /> 贵（残差为正）
        </li>
        <li>
          <span style={{ background: VIZ.negative, opacity: 0.9 }} /> 便宜
        </li>
        <li>
          <span className="heatmap-legend-absent" /> 未采集
        </li>
        <li className="heatmap-legend-note">色深封顶于 ±2σ</li>
      </ul>
    </figure>
  );
}
