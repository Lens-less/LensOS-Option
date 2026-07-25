import type {
  ResearchReport,
  SurfaceExpiry,
  SurfacePoint,
} from "../../contracts";
import { finiteNumber } from "./reportModel";
import type { Tone } from "./reportModel";
import { formatDecimal, formatExpiry } from "./marketModel";
import type { CandidateRow } from "./marketModel";

function surfaceSeries(expiry: SurfaceExpiry): SurfacePoint[] {
  return (expiry.surface_points ?? []).filter(
    (point) =>
      finiteNumber(point.strike_price) !== null &&
      finiteNumber(point.surface_fitted_iv) !== null,
  );
}

function SurfaceChart({
  expiries,
}: {
  expiries: SurfaceExpiry[];
}): React.JSX.Element | null {
  const series = expiries
    .map((expiry) => ({ expiry, points: surfaceSeries(expiry) }))
    .filter(({ points }) => points.length >= 2);
  const allPoints = series.flatMap(({ points }) => points);
  if (allPoints.length < 2) {
    return null;
  }
  const strikes = allPoints
    .map((point) => finiteNumber(point.strike_price))
    .filter((value): value is number => value !== null);
  const ivs = allPoints
    .map((point) => finiteNumber(point.surface_fitted_iv))
    .filter((value): value is number => value !== null);
  const minStrike = Math.min(...strikes);
  const maxStrike = Math.max(...strikes);
  const minIv = Math.min(...ivs);
  const maxIv = Math.max(...ivs);
  const strikeSpan = Math.max(maxStrike - minStrike, 1);
  const ivSpan = Math.max(maxIv - minIv, 1);
  const x = (strike: number) => 64 + ((strike - minStrike) / strikeSpan) * 616;
  const y = (iv: number) => 244 - ((iv - minIv) / ivSpan) * 188;
  const colors = ["#0f62fe", "#8e5b00", "#198038", "#da1e28"];

  return (
    <div className="surface-chart-scroll" aria-label="波动率曲面图区域">
      <svg
        className="surface-chart"
        viewBox="0 0 744 292"
        role="img"
        aria-label="BTC 波动率曲面"
      >
        <title>BTC 波动率曲面</title>
        <desc>按到期日展示执行价与拟合隐含波动率的关系。</desc>
        <defs>
          <pattern
            id="surface-grid"
            width="77"
            height="47"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 77 0 L 0 0 0 47"
              fill="none"
              stroke="#e0e0e0"
              strokeWidth="1"
            />
          </pattern>
        </defs>
        <rect x="64" y="56" width="616" height="188" fill="url(#surface-grid)" />
        <line x1="64" y1="244" x2="680" y2="244" stroke="#8d8d8d" />
        <line x1="64" y1="56" x2="64" y2="244" stroke="#8d8d8d" />
        <text x="64" y="269" className="chart-axis-label">
          {Math.round(minStrike / 1_000)}K
        </text>
        <text x="646" y="269" className="chart-axis-label">
          {Math.round(maxStrike / 1_000)}K
        </text>
        <text x="18" y="63" className="chart-axis-label">
          {maxIv.toFixed(1)}%
        </text>
        <text x="18" y="247" className="chart-axis-label">
          {minIv.toFixed(1)}%
        </text>
        {series.map(({ expiry, points }, index) => {
          const color = colors[index % colors.length];
          const line = points
            .map((point) => {
              const strike = finiteNumber(point.strike_price) ?? minStrike;
              const iv = finiteNumber(point.surface_fitted_iv) ?? minIv;
              return `${x(strike)},${y(iv)}`;
            })
            .join(" ");
          return (
            <g key={expiry.expiry_date ?? `expiry-${index}`}>
              <polyline
                points={line}
                fill="none"
                stroke={color}
                strokeWidth={index === 0 ? 3 : 2.25}
                strokeDasharray={index === 0 ? undefined : "7 5"}
              />
              {points.map((point, pointIndex) => {
                const strike = finiteNumber(point.strike_price) ?? minStrike;
                const iv = finiteNumber(point.surface_fitted_iv) ?? minIv;
                return (
                  <circle
                    cx={x(strike)}
                    cy={y(iv)}
                    fill="#ffffff"
                    key={`${expiry.expiry_date}-${point.instrument_name ?? pointIndex}`}
                    r="3.5"
                    stroke={color}
                    strokeWidth="2"
                  />
                );
              })}
            </g>
          );
        })}
        <text x="346" y="288" className="chart-axis-title">
          执行价（USD）
        </text>
        <text
          x="-181"
          y="12"
          className="chart-axis-title"
          transform="rotate(-90)"
        >
          拟合 IV
        </text>
      </svg>
    </div>
  );
}

export function SurfaceResearch({
  report,
}: {
  report: ResearchReport;
}): React.JSX.Element {
  const expiries = report.vol_surface_status?.expiries ?? [];
  const chartAvailable = expiries.some(
    (expiry) => surfaceSeries(expiry).length >= 2,
  );
  return (
    <section
      id="surface"
      className="research-section surface-section"
      aria-labelledby="surface-title"
    >
      <header className="research-section-heading">
        <div>
          <p className="section-kicker">Volatility surface / 证据</p>
          <h2 id="surface-title">波动率曲面证据</h2>
        </div>
        <p>
          拟合质量和无套利检查分开呈现；只有两者都通过，曲面才进入候选研究。
        </p>
      </header>
      {chartAvailable ? (
        <div className="surface-layout">
          <SurfaceChart expiries={expiries} />
          <div className="surface-expiries" aria-label="到期曲面质量">
            {expiries.map((expiry) => {
              const tone: Tone = expiry.candidate_eligible
                ? "safe"
                : expiry.fit_quality_pass
                  ? "warning"
                  : "danger";
              return (
                <article
                  className="surface-expiry"
                  data-tone={tone}
                  key={expiry.expiry_date ?? String(expiry.dte_days)}
                >
                  <div>
                    <span>{formatExpiry(expiry.expiry_date ?? null)}</span>
                    <strong>
                      {finiteNumber(expiry.dte_days)?.toFixed(1) ?? "—"} DTE
                    </strong>
                  </div>
                  <dl>
                    <div>
                      <dt>拟合质量</dt>
                      <dd>
                        {formatDecimal(
                          finiteNumber(expiry.fit_quality_score),
                          3,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>无套利</dt>
                      <dd>{expiry.no_arb_pass ? "通过" : "未通过"}</dd>
                    </div>
                    <div>
                      <dt>候选资格</dt>
                      <dd>{expiry.candidate_eligible ? "可用" : "不可用"}</dd>
                    </div>
                  </dl>
                  {(expiry.reason_codes ?? []).length > 0 ? (
                    <code>{expiry.reason_codes?.join(" · ")}</code>
                  ) : (
                    <code>NO_ARBITRAGE_PASS</code>
                  )}
                </article>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="section-empty" role="status">
          <strong>没有可验证的曲面数据</strong>
          <p>页面不会根据缺失报价推算曲线；请刷新或检查市场数据来源。</p>
        </div>
      )}
    </section>
  );
}

function CandidateTable({
  candidates,
}: {
  candidates: CandidateRow[];
}): React.JSX.Element {
  return (
    <div
      className="candidate-table-scroll"
      role="region"
      aria-label="研究候选表格"
      tabIndex={0}
    >
      <table className="candidate-table">
        <thead>
          <tr>
            <th scope="col">结构</th>
            <th scope="col">合约</th>
            <th scope="col">到期</th>
            <th scope="col">模型 Delta</th>
            <th scope="col">权利金 / 净信用</th>
            <th scope="col">曲面质量</th>
            <th scope="col">研究状态</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate) => (
            <tr key={candidate.id}>
              <td>
                <span className="structure-label" data-kind={candidate.kind}>
                  {candidate.kind === "spread" ? "CALL 信用价差" : "单腿空头 CALL"}
                </span>
              </td>
              <td className="candidate-contract">{candidate.contract}</td>
              <td>{formatExpiry(candidate.expiry)}</td>
              <td className="numeric-cell">
                {formatDecimal(candidate.delta, 3)}
              </td>
              <td className="numeric-cell">
                {formatDecimal(candidate.premium, 4)} BTC
              </td>
              <td className="numeric-cell">
                {formatDecimal(candidate.quality, 3)}
              </td>
              <td>
                <span
                  className="evidence-state"
                  data-tone={candidate.noArbPass ? "safe" : "warning"}
                >
                  {candidate.noArbPass ? "研究筛选通过" : "仍需复核"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CandidateResearchSection({
  candidates,
  report,
}: {
  candidates: CandidateRow[];
  report: ResearchReport;
}): React.JSX.Element {
  const summary = report.candidate_research?.summary;
  return (
    <section
      id="candidates"
      className="research-section candidates-section"
      aria-labelledby="candidates-title"
    >
      <header className="research-section-heading">
        <div>
          <p className="section-kicker">Candidate research / 只读</p>
          <h2 id="candidates-title">研究候选清单</h2>
        </div>
        <p>
          {summary?.eligible_naked_short_calls ?? 0} 个单腿、{" "}
          {summary?.eligible_call_credit_spreads ?? 0} 个价差通过当前过滤；这不是交易建议。
        </p>
      </header>
      {candidates.length > 0 ? (
        <CandidateTable candidates={candidates} />
      ) : (
        <div className="section-empty" role="status">
          <strong>没有通过筛选的研究候选</strong>
          <p>当前报告没有可验证的候选行；页面不会构造示例策略。</p>
        </div>
      )}
    </section>
  );
}
