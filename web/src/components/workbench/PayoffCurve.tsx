import type { StructureKind } from "./candidateModel";

export interface PayoffCurveProps {
  structureKind: StructureKind;
  shortStrikeUsdc: number | null;
  longStrikeUsdc: number | null;
  creditUsdc: number | null;
  spotUsdc: number | null;
}

function formatAxisUsdc(value: number): string {
  const rounded = Math.round(value);
  const sign = rounded < 0 ? "-" : "";
  return `${sign}$${Math.abs(rounded).toLocaleString("en-US")}`;
}

const MARGIN_LEFT = 60;
const MARGIN_RIGHT = 24;
const MARGIN_TOP = 20;
const MARGIN_BOTTOM = 40;
const CHART_WIDTH = 640 - MARGIN_LEFT - MARGIN_RIGHT;
const CHART_HEIGHT = 260;
const VIEW_HEIGHT = MARGIN_TOP + CHART_HEIGHT + MARGIN_BOTTOM;

export function PayoffCurve({
  structureKind,
  shortStrikeUsdc,
  longStrikeUsdc,
  creditUsdc,
  spotUsdc,
}: PayoffCurveProps): React.JSX.Element {
  if (shortStrikeUsdc === null || creditUsdc === null) {
    return (
      <div className="payoff-unavailable" role="status">
        缺少行权价或实得信用数据，暂时无法绘制到期盈亏图。
      </div>
    );
  }

  const isSpread = structureKind === "spread" && longStrikeUsdc !== null;
  const spreadWidth = isSpread ? (longStrikeUsdc as number) - shortStrikeUsdc : null;
  const breakevenUsdc = shortStrikeUsdc + creditUsdc;
  const maxLossUsdc =
    isSpread && spreadWidth !== null ? spreadWidth - creditUsdc : null;

  const span = Math.max(
    shortStrikeUsdc * 0.22,
    creditUsdc * 12,
    isSpread && spreadWidth !== null ? spreadWidth * 2 : 0,
    400,
  );
  let xMin = shortStrikeUsdc - span;
  let xMax = shortStrikeUsdc + span;
  if (isSpread && longStrikeUsdc !== null) {
    xMax = Math.max(xMax, longStrikeUsdc + span * 0.5);
  }
  if (spotUsdc !== null) {
    xMin = Math.min(xMin, spotUsdc - span * 0.3);
    xMax = Math.max(xMax, spotUsdc + span * 0.3);
  }

  const yMax = Math.max(creditUsdc * 1.4, 1);
  const drawnFloorLoss =
    maxLossUsdc !== null ? maxLossUsdc : Math.max(creditUsdc * 5, span * 0.6);
  const yMin = -Math.max(drawnFloorLoss * 1.15, 1);

  const xScale = (x: number) =>
    MARGIN_LEFT + ((x - xMin) / (xMax - xMin)) * CHART_WIDTH;
  const yScale = (y: number) =>
    MARGIN_TOP + (1 - (y - yMin) / (yMax - yMin)) * CHART_HEIGHT;
  const zeroY = yScale(0);

  let solidPoints: Array<[number, number]>;
  let unboundedTail: { fromPx: [number, number]; toPx: [number, number] } | null =
    null;

  if (isSpread && longStrikeUsdc !== null && maxLossUsdc !== null) {
    solidPoints = [
      [xMin, creditUsdc],
      [shortStrikeUsdc, creditUsdc],
      [longStrikeUsdc, -maxLossUsdc],
      [xMax, -maxLossUsdc],
    ];
  } else {
    const declineAtXMax = creditUsdc - (xMax - shortStrikeUsdc);
    if (declineAtXMax >= yMin) {
      solidPoints = [
        [xMin, creditUsdc],
        [shortStrikeUsdc, creditUsdc],
        [xMax, declineAtXMax],
      ];
    } else {
      const xAtFloor = shortStrikeUsdc + (creditUsdc - yMin);
      solidPoints = [
        [xMin, creditUsdc],
        [shortStrikeUsdc, creditUsdc],
        [xAtFloor, yMin],
      ];
      const from: [number, number] = [xScale(xAtFloor), yScale(yMin)];
      const sx = xScale(shortStrikeUsdc);
      const sy = yScale(creditUsdc);
      const slope = (from[1] - sy) / (from[0] - sx || 1);
      const runPx = 46;
      unboundedTail = {
        fromPx: from,
        toPx: [from[0] + runPx, from[1] + slope * runPx],
      };
    }
  }

  const solidPx = solidPoints
    .map(([x, y]) => `${xScale(x)},${yScale(y)}`)
    .join(" ");

  const breakevenVisible = breakevenUsdc >= xMin && breakevenUsdc <= xMax;
  const spotVisible = spotUsdc !== null && spotUsdc >= xMin && spotUsdc <= xMax;

  return (
    <div className="payoff-curve-block">
      <div className="payoff-chart-scroll" aria-label="到期盈亏图区域">
        <svg
          className="payoff-chart"
          viewBox={`0 0 640 ${VIEW_HEIGHT + (unboundedTail ? 24 : 0)}`}
          role="img"
          aria-label="单份合约到期盈亏图"
        >
          <title>单份合约到期盈亏图</title>
          <desc>
            横轴为到期时标的价格，纵轴为单份合约到期盈亏（USDC）。
            {isSpread
              ? "价差结构在两个行权价之间形成有限的最大损失。"
              : "单腿结构在标的涨破行权价后亏损没有上限；虚线段表示图表右侧之外盈亏继续恶化。"}
          </desc>
          <line
            stroke="#c6c6c6"
            x1={MARGIN_LEFT}
            x2={640 - MARGIN_RIGHT}
            y1={zeroY}
            y2={zeroY}
          />
          <text className="chart-axis-label" x={8} y={zeroY + 4}>
            $0
          </text>
          <line
            stroke="#8d8d8d"
            x1={MARGIN_LEFT}
            x2={640 - MARGIN_RIGHT}
            y1={MARGIN_TOP + CHART_HEIGHT}
            y2={MARGIN_TOP + CHART_HEIGHT}
          />
          <text
            className="chart-axis-label"
            x={MARGIN_LEFT}
            y={MARGIN_TOP + CHART_HEIGHT + 20}
          >
            {formatAxisUsdc(xMin)}
          </text>
          <text
            className="chart-axis-label"
            textAnchor="end"
            x={640 - MARGIN_RIGHT}
            y={MARGIN_TOP + CHART_HEIGHT + 20}
          >
            {formatAxisUsdc(xMax)}
          </text>

          {spotVisible ? (
            <g data-marker="spot">
              <line
                stroke="#0f62fe"
                strokeDasharray="4 4"
                x1={xScale(spotUsdc as number)}
                x2={xScale(spotUsdc as number)}
                y1={MARGIN_TOP}
                y2={MARGIN_TOP + CHART_HEIGHT}
              />
              <text
                className="chart-axis-label payoff-spot-label"
                x={xScale(spotUsdc as number) + 4}
                y={MARGIN_TOP + 12}
              >
                现价
              </text>
            </g>
          ) : null}

          {breakevenVisible ? (
            <g data-marker="breakeven">
              <line
                stroke="#8e5b00"
                strokeDasharray="2 3"
                x1={xScale(breakevenUsdc)}
                x2={xScale(breakevenUsdc)}
                y1={MARGIN_TOP}
                y2={MARGIN_TOP + CHART_HEIGHT}
              />
              <circle
                cx={xScale(breakevenUsdc)}
                cy={zeroY}
                fill="#fff1c2"
                r="4"
                stroke="#8e5b00"
                strokeWidth="1.5"
              />
              <text
                className="chart-axis-label payoff-breakeven-label"
                x={xScale(breakevenUsdc) + 4}
                y={MARGIN_TOP + CHART_HEIGHT - 6}
              >
                盈亏平衡
              </text>
            </g>
          ) : null}

          <polyline fill="none" points={solidPx} stroke="#161616" strokeWidth="2.5" />

          {unboundedTail ? (
            <g data-marker="unbounded-tail">
              <line
                stroke="#da1e28"
                strokeDasharray="5 4"
                strokeWidth="2.5"
                x1={unboundedTail.fromPx[0]}
                x2={unboundedTail.toPx[0]}
                y1={unboundedTail.fromPx[1]}
                y2={unboundedTail.toPx[1]}
              />
              <text
                className="chart-axis-label payoff-unbounded-label"
                x={Math.min(unboundedTail.toPx[0] + 4, 640 - 120)}
                y={Math.min(unboundedTail.toPx[1] + 4, VIEW_HEIGHT + 18)}
              >
                亏损无上限（标的继续上涨）
              </text>
            </g>
          ) : null}

          <text
            className="chart-axis-title"
            x={320}
            y={VIEW_HEIGHT + (unboundedTail ? 22 : -4)}
          >
            到期标的价格（USDC）
          </text>
        </svg>
      </div>
      <dl className="payoff-summary" aria-label="到期盈亏关键点">
        <div>
          <dt>最大收益（信用）</dt>
          <dd>{formatAxisUsdc(creditUsdc)}</dd>
        </div>
        <div>
          <dt>盈亏平衡</dt>
          <dd>{formatAxisUsdc(breakevenUsdc)}</dd>
        </div>
        <div>
          <dt>最大损失</dt>
          <dd>{maxLossUsdc === null ? "无上限" : formatAxisUsdc(-maxLossUsdc)}</dd>
        </div>
      </dl>
    </div>
  );
}
