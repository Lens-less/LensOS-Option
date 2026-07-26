import { useId, useMemo, useState } from "react";

import { MARK, VIZ } from "./tokens";

export interface PayoffSeries {
  key: string;
  label: string;
  points: Array<{ spot: number; pnl: number }>;
  /** Context series are drawn in gray behind the subject. */
  emphasis: "subject" | "context";
}

export interface PayoffMarker {
  spot: number;
  label: string;
}

function extent(values: number[]): [number, number] {
  return [Math.min(...values), Math.max(...values)];
}

/**
 * Profit against terminal spot, for one structure or a whole book.
 *
 * This is the **emphasis** form rather than a categorical one: the combined
 * book is the subject and its members are context, so one hue carries the
 * subject and gray carries the rest. Painting five members in five hues would
 * spend the identity channel on rows the reader is not comparing — they are
 * reading one line and its parts.
 *
 * The zero line is the reference the whole chart is about, so it is drawn as a
 * solid hairline and the fill above/below it uses the diverging pair at a wash.
 */
export function PayoffChart({
  ariaLabel,
  currentSpot,
  formatMoney,
  markers = [],
  series,
}: {
  ariaLabel: string;
  currentSpot?: number | null;
  formatMoney: (value: number) => string;
  markers?: PayoffMarker[];
  series: PayoffSeries[];
}): React.JSX.Element | null {
  const titleId = useId();
  const clipId = useId();
  const aboveId = useId();
  const belowId = useId();
  const [cursor, setCursor] = useState<{ spot: number; x: number } | null>(null);

  const width = 640;
  const height = 260;
  const pad = { top: 16, right: 20, bottom: 34, left: 68 };

  const geometry = useMemo(() => {
    const all = series.flatMap((item) => item.points);
    if (all.length < 2) {
      return null;
    }
    const [minSpot, maxSpot] = extent(all.map((point) => point.spot));
    const [minPnl, maxPnl] = extent(all.map((point) => point.pnl));
    // Zero must be inside the range: this chart exists to show which side of it
    // the position sits on.
    const lowPnl = Math.min(minPnl, 0);
    const highPnl = Math.max(maxPnl, 0);
    const spanPnl = highPnl - lowPnl || 1;
    const spanSpot = maxSpot - minSpot || 1;

    const x = (spot: number) =>
      pad.left + ((spot - minSpot) / spanSpot) * (width - pad.left - pad.right);
    const y = (pnl: number) =>
      pad.top + ((highPnl - pnl) / spanPnl) * (height - pad.top - pad.bottom);
    return { x, y, minSpot, maxSpot, lowPnl, highPnl };
  }, [series]);

  if (!geometry) {
    return null;
  }
  const { x, y, minSpot, maxSpot } = geometry;
  const zeroY = y(0);

  const gridTicks = [geometry.highPnl, 0, geometry.lowPnl].filter(
    (value, index, all) =>
      all.findIndex((other) => Math.abs(y(other) - y(value)) < 14) === index,
  );

  const subject = series.find((item) => item.emphasis === "subject");
  const hovered =
    cursor && subject
      ? subject.points.reduce((best, point) =>
          Math.abs(point.spot - cursor.spot) < Math.abs(best.spot - cursor.spot)
            ? point
            : best,
        )
      : null;

  const path = (points: PayoffSeries["points"]) =>
    points
      .map(
        (point, index) =>
          `${index === 0 ? "M" : "L"}${x(point.spot).toFixed(2)} ${y(point.pnl).toFixed(2)}`,
      )
      .join(" ");

  return (
    <figure className="viz-figure">
      <svg
        aria-labelledby={titleId}
        className="viz-svg"
        onMouseLeave={() => setCursor(null)}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const px = ((event.clientX - rect.left) / rect.width) * width;
          const ratio =
            (px - pad.left) / (width - pad.left - pad.right);
          const spot = minSpot + Math.min(Math.max(ratio, 0), 1) * (maxSpot - minSpot);
          setCursor({ spot, x: px });
        }}
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <title id={titleId}>{ariaLabel}</title>
        <defs>
          <clipPath id={clipId}>
            <rect
              height={height - pad.top - pad.bottom}
              width={width - pad.left - pad.right}
              x={pad.left}
              y={pad.top}
            />
          </clipPath>
          <clipPath id={aboveId}>
            <rect
              height={Math.max(zeroY - pad.top, 0)}
              width={width - pad.left - pad.right}
              x={pad.left}
              y={pad.top}
            />
          </clipPath>
          <clipPath id={belowId}>
            <rect
              height={Math.max(height - pad.bottom - zeroY, 0)}
              width={width - pad.left - pad.right}
              x={pad.left}
              y={zeroY}
            />
          </clipPath>
        </defs>

        {/* Recessive hairline grid; solid, never dashed. Ticks closer than a
            line-height are dropped rather than drawn over each other — a
            collided label is worse than a missing one, and the readout and the
            table carry the value either way. */}
        {gridTicks.map((value) => (
          <g key={value}>
            <line
              stroke={value === 0 ? VIZ.axis : VIZ.grid}
              strokeWidth={1}
              x1={pad.left}
              x2={width - pad.right}
              y1={y(value)}
              y2={y(value)}
            />
            <text
              dominantBaseline="middle"
              fill={VIZ.muted}
              fontSize={10}
              style={{ fontVariantNumeric: "tabular-nums" }}
              textAnchor="end"
              x={pad.left - 8}
              y={y(value)}
            >
              {formatMoney(value)}
            </text>
          </g>
        ))}

        {subject ? (
          <g clipPath={`url(#${clipId})`}>
            {/* A wash, not a saturated block: 10% of the pole's own hue, and
                one pole per side of the baseline. Filling both sides in the
                positive hue would paint a loss the colour of a gain. */}
            <g clipPath={`url(#${aboveId})`}>
              <path
                d={`${path(subject.points)} L${x(maxSpot)} ${zeroY} L${x(minSpot)} ${zeroY} Z`}
                fill={VIZ.positive}
                opacity={0.1}
              />
            </g>
            <g clipPath={`url(#${belowId})`}>
              <path
                d={`${path(subject.points)} L${x(maxSpot)} ${zeroY} L${x(minSpot)} ${zeroY} Z`}
                fill={VIZ.negative}
                opacity={0.1}
              />
            </g>
          </g>
        ) : null}

        {series
          .filter((item) => item.emphasis === "context")
          .map((item) => (
            <path
              clipPath={`url(#${clipId})`}
              d={path(item.points)}
              fill="none"
              key={item.key}
              stroke={VIZ.context}
              strokeWidth={1}
            />
          ))}

        {subject ? (
          <path
            clipPath={`url(#${clipId})`}
            d={path(subject.points)}
            fill="none"
            stroke={VIZ.subject}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={MARK.lineWidth}
          />
        ) : null}

        {markers.map((marker) => (
          <g key={`${marker.label}-${marker.spot}`}>
            <line
              stroke={VIZ.axis}
              strokeWidth={1}
              x1={x(marker.spot)}
              x2={x(marker.spot)}
              y1={pad.top}
              y2={height - pad.bottom}
            />
            <text
              fill={VIZ.muted}
              fontSize={10}
              textAnchor="middle"
              x={x(marker.spot)}
              y={pad.top - 4}
            >
              {marker.label}
            </text>
          </g>
        ))}

        {typeof currentSpot === "number" && Number.isFinite(currentSpot) ? (
          <g>
            <line
              stroke={VIZ.ink}
              strokeWidth={1}
              x1={x(currentSpot)}
              x2={x(currentSpot)}
              y1={pad.top}
              y2={height - pad.bottom}
            />
            <text
              fill={VIZ.ink}
              fontSize={10}
              textAnchor="middle"
              x={x(currentSpot)}
              y={height - pad.bottom + 14}
            >
              现价
            </text>
          </g>
        ) : null}

        {hovered ? (
          <g>
            <circle
              cx={x(hovered.spot)}
              cy={y(hovered.pnl)}
              fill={VIZ.subject}
              r={MARK.markerRadius}
              stroke={VIZ.surface}
              strokeWidth={MARK.surfaceGap}
            />
          </g>
        ) : null}

        <text fill={VIZ.muted} fontSize={10} x={pad.left} y={height - 8}>
          {Math.round(minSpot).toLocaleString("en-US")}
        </text>
        <text
          fill={VIZ.muted}
          fontSize={10}
          textAnchor="end"
          x={width - pad.right}
          y={height - 8}
        >
          {Math.round(maxSpot).toLocaleString("en-US")}
        </text>
      </svg>

      {hovered ? (
        <p className="viz-readout" role="status">
          到期价 {Math.round(hovered.spot).toLocaleString("en-US")} ·{" "}
          <strong>{formatMoney(hovered.pnl)}</strong>
        </p>
      ) : (
        <p className="viz-readout viz-readout-idle">
          在图上移动以读取任意到期价对应的盈亏
        </p>
      )}

      {series.length > 1 ? (
        <ul className="viz-legend">
          <li>
            <span style={{ background: VIZ.subject }} /> 组合
          </li>
          <li>
            <span style={{ background: VIZ.context }} /> 单个成员
          </li>
        </ul>
      ) : null}
    </figure>
  );
}
