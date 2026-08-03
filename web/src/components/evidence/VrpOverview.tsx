import type { ResearchReport, VrpStatusPoint } from "../../contracts";
import { formatPercent, formatTimestamp } from "./marketModel";
import {
  formatPublishedAge,
  marketDisplayState,
  type Freshness,
} from "./reportModel";
import { ReasonCodeNotice } from "../shell/ReasonCodeNotice";

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatPoints(value: number | null): string {
  return value === null ? "不可用" : `${value.toFixed(1)} pt`;
}

function percentileLabel(
  value: number | null,
  fallback = "不可用",
): string {
  if (value === null) {
    return fallback;
  }
  return `P${Math.round(value * 100)}`;
}

function formatWindowLabel(windowDays: number | null): string {
  if (windowDays === null) {
    return "历史窗口";
  }
  const years = windowDays / 365;
  return `约 ${years.toLocaleString("zh-CN", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })} 年（${windowDays.toLocaleString("zh-CN")} 天）窗口`;
}

function bandTone(band: string | null | undefined): "danger" | "warning" | "safe" {
  if (!band) {
    return "warning";
  }
  if (band.includes("P90") || band.includes("P10")) {
    return "danger";
  }
  if (band.includes("P70") || band.includes("P30")) {
    return "warning";
  }
  return "safe";
}

function isValidatedVrpStatus(status: string | undefined): boolean {
  return status === "validated" || status === "available";
}

function VrpSeriesChart({
  points,
  windowLabel,
}: {
  points: VrpStatusPoint[];
  windowLabel: string;
}): React.JSX.Element | null {
  const values = points
    .map((point) => finite(point.vrp_percent_points))
    .filter((value): value is number => value !== null);
  if (values.length < 2) {
    return null;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(1, max - min);
  const lastIndex = Math.max(1, points.length - 1);
  const polyline = points
    .map((point, index) => {
      const value = finite(point.vrp_percent_points) ?? min;
      const x = 24 + (index / lastIndex) * 552;
      const y = 170 - ((value - min) / span) * 132;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <figure className="vrp-series-figure">
      <svg
        className="vrp-series-chart"
        viewBox="0 0 600 200"
        role="img"
        aria-label={`VRP ${windowLabel}时序`}
      >
        <title>{`VRP ${windowLabel}时序`}</title>
        <rect x="24" y="24" width="552" height="146" fill="#f4f4f4" />
        <line x1="24" y1="170" x2="576" y2="170" stroke="#8d8d8d" />
        <line x1="24" y1="24" x2="24" y2="170" stroke="#8d8d8d" />
        <polyline fill="none" points={polyline} stroke="#0f62fe" strokeWidth="3" />
        <text className="chart-axis-label" x="12" y="30">
          {max.toFixed(1)} pt
        </text>
        <text className="chart-axis-label" x="12" y="174">
          {min.toFixed(1)} pt
        </text>
        <text className="chart-axis-title" x="248" y="194">
          观测日
        </text>
      </svg>
      <details className="viz-table">
        <summary>表格 fallback</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">日期</th>
              <th scope="col">VRP</th>
              <th scope="col">DVOL</th>
              <th scope="col">RV30</th>
              <th scope="col">百分位</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.observed_at ?? String(point.vrp_percent_points)}>
                <td>{formatTimestamp(point.observed_at)}</td>
                <td>{formatPoints(finite(point.vrp_percent_points))}</td>
                <td>{formatPercent(finite(point.dvol_percent), 1)}</td>
                <td>{formatPercent(finite(point.rv30_percent), 1)}</td>
                <td>{percentileLabel(finite(point.percentile), "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

export function VrpOverview({
  freshness,
  report,
}: {
  freshness: Freshness;
  report: ResearchReport;
}): React.JSX.Element {
  const vrp = report.vrp_status;
  const state = marketDisplayState(report, freshness);
  const currentVrp = finite(vrp?.current_vrp_percent_points);
  const currentDvol = finite(vrp?.current_dvol_percent);
  const currentRv30 = finite(vrp?.current_rv30_percent);
  const percentile = finite(vrp?.percentile);
  const windowDays = finite(vrp?.window_days);
  const windowLabel = formatWindowLabel(windowDays);
  const currentBand = vrp?.band;
  const series = (vrp?.series ?? []).filter(
    (point) => finite(point.vrp_percent_points) !== null,
  );
  const sampleCount = vrp?.sample_count;
  const minimumSampleCount = vrp?.minimum_series_sample_count;
  const isInsufficientHistory =
    vrp?.status === "insufficient_history" ||
    vrp?.reason_code === "INSUFFICIENT_VRP_HISTORY";
  const unavailableCode =
    vrp?.reason_code ??
    (isInsufficientHistory
      ? "INSUFFICIENT_VRP_HISTORY"
      : "MISSING_DVOL_HISTORY");
  const insufficientHistoryDetail =
    sampleCount !== null &&
    sampleCount !== undefined &&
    minimumSampleCount !== null &&
    minimumSampleCount !== undefined
      ? `当前仅累计 ${sampleCount} / ${minimumSampleCount} 个有效 VRP 读数，头条数字保持隐藏。`
      : "VRP 有效样本还不够，头条数字保持隐藏，只提供补齐命令。";

  return (
    <section
      id="vrp"
      className="research-section vrp-section"
      aria-label="现在贵不贵"
    >
      <header className="research-section-heading vrp-heading">
        <div>
          <p className="section-kicker">VRP thermometer / 头条</p>
          <h1>现在贵不贵</h1>
        </div>
        <p>
          VRP 为正不等于机会。它同样可能反映一段即将到来的高波动，事后看是买方的钱。
        </p>
      </header>
      {state === "stale" ? (
        <div className="section-empty published-stop-state" role="status">
          <strong>发布已停摆</strong>
          <p>
            这版公开稿已超过发布时效上限；VRP、DVOL、曲面与候选数字全部收起，
            直到下一版发布。
          </p>
          <small>{formatPublishedAge(freshness.ageSec)}</small>
        </div>
      ) : isValidatedVrpStatus(vrp?.status) && currentVrp !== null ? (
        <div className="vrp-layout">
          <div className="vrp-hero">
            <span className="vrp-label">BTC 卖方溢价</span>
            <strong>{formatPoints(currentVrp)}</strong>
            <p>
              DVOL {formatPercent(currentDvol, 1)} - RV30{" "}
              {formatPercent(currentRv30, 1)}
            </p>
          </div>
          <div className="vrp-scale" data-tone={bandTone(currentBand)}>
            <div className="vrp-scale-copy">
              <span>{windowLabel}经验百分位</span>
              <strong aria-label={percentile === null ? "百分位不可用" : undefined}>
                {percentileLabel(percentile, "")}
              </strong>
              <small>{currentBand ?? ""}</small>
            </div>
            <ol aria-label="VRP 刻度带">
              {["P90", "P70", "P30", "P10"].map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </div>
          <VrpSeriesChart points={series} windowLabel={windowLabel} />
          <p className="section-note">
            图中 DVOL 代表 forward-implied volatility，RV30 代表 trailing-realized volatility。
          </p>
        </div>
      ) : (
        <div className="vrp-unavailable">
          <div className="section-empty" role="status">
            <strong>{isInsufficientHistory ? "样本不足" : "不可用"}</strong>
            <p>
              {isInsufficientHistory
                ? insufficientHistoryDetail
                : "缺少可复算的 DVOL 历史或 VRP 时序，页面不会显示 0 或占位数。"}
            </p>
          </div>
          <ReasonCodeNotice
            codes={[unavailableCode]}
            heading="补齐命令"
          />
        </div>
      )}
    </section>
  );
}
