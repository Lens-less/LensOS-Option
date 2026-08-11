import type {
  ResearchReport,
  SurfaceExpiry,
  SurfacePoint,
  VrpStatusPoint,
} from "../contracts";
import {
  finiteNumber,
  formatCutoffTime,
  formatDecimal,
  formatDurationHours,
  formatDvol,
  formatExpiry,
  formatPercent,
  formatPublishedAge,
  formatTimestamp,
  formatUsd,
  marketFacts,
  publicMarketDisplayState,
  publicVrpSeries,
  researchCandidates,
  type CandidateRow,
  type PublicFreshness,
} from "./publicModel";
import type { PublicReleaseSummary } from "./loadPublicReport";
import {
  readPublicReasonCode,
  resolvePublicExchangeEventEvidence,
} from "./publicReasonCodes";

const FRESHNESS_LABELS = {
  current: "当前",
  warning: "预警",
  expired: "已失效",
  unavailable: "不可用",
} as const;

function formatPoints(value: number | null): string {
  return value === null ? "不可用" : `${value.toFixed(1)} pt`;
}

function percentileLabel(value: number | null): string {
  if (value === null) {
    return "不可用";
  }
  return `P${Math.round(value * 100)}`;
}

function vrpWindowLabel(
  windowDays: number | null,
  points: VrpStatusPoint[],
): string {
  if (windowDays !== null && windowDays > 0) {
    return `${Math.round(windowDays).toLocaleString("zh-CN")} 日`;
  }
  const observed = points
    .map((point) => point.observed_at)
    .filter((value): value is string => Boolean(value))
    .map((value) => Date.parse(value))
    .filter(Number.isFinite)
    .sort((left, right) => left - right);
  if (observed.length >= 2) {
    const formatter = new Intl.DateTimeFormat("zh-CN", {
      dateStyle: "medium",
      timeZone: "UTC",
    });
    return `${formatter.format(observed[0])} 至 ${formatter.format(observed.at(-1)!)}`;
  }
  return points.length > 0
    ? `${points.length.toLocaleString("zh-CN")} 个观察日`
    : "可用历史";
}

function publicBandLabel(band: string | null | undefined): string {
  const labels: Record<string, string> = {
    "P10-": "极薄",
    "P30-": "偏薄",
    "P30-P70": "中性",
    "P70+": "偏贵",
    "P90+": "极贵",
  };
  return band ? (labels[band] ?? band) : "刻度带不可用";
}

function VrpChangeLine({
  band,
  summary,
}: {
  band: string | null | undefined;
  summary: PublicReleaseSummary | null;
}): React.JSX.Element {
  const change = summary?.change;
  const delta = finiteNumber(change?.vrp_percent_points_delta);
  if (change?.status !== "available" || delta === null) {
    return <p className="vrp-change">上一观察日对比不可用</p>;
  }
  const signedDelta = `${delta > 0 ? "+" : delta < 0 ? "" : "±"}${delta.toFixed(1)}`;
  const bandCopy = change.band_changed ? "现为" : "仍为";
  const currentObservedAt = Date.parse(change.current_observed_at ?? "");
  const priorObservedAt = Date.parse(change.prior_observed_at ?? "");
  const comparisonCopy =
    Number.isFinite(currentObservedAt) &&
    Number.isFinite(priorObservedAt) &&
    currentObservedAt - priorObservedAt === 24 * 60 * 60 * 1_000
      ? "较昨日"
      : "较上一观察日";
  return (
    <p className="vrp-change">
      {comparisonCopy} {signedDelta} pt，{bandCopy}
      {publicBandLabel(band)}
    </p>
  );
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

function PublicReasonNotice({
  codes,
  detailOverrides = {},
}: {
  codes: string[];
  detailOverrides?: Record<string, string>;
}): React.JSX.Element | null {
  const uniqueCodes = [...new Set(codes.filter(Boolean))];
  if (uniqueCodes.length === 0) {
    return null;
  }
  return (
    <section className="reason-notice" aria-label="原因代码说明">
      <ul>
        {uniqueCodes.map((code) => {
          const reading = readPublicReasonCode(code);
          return (
            <li key={code}>
              <div className="reason-notice-head">
                <strong>{reading.title}</strong>
                <code className="reason-notice-code">{code}</code>
              </div>
              <p>{detailOverrides[code] ?? reading.detail}</p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function VrpSeriesChart({
  points,
  windowLabel,
}: {
  points: VrpStatusPoint[];
  windowLabel: string;
}): React.JSX.Element | null {
  const values = points
    .map((point) => finiteNumber(point.vrp_percent_points))
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
      const value = finiteNumber(point.vrp_percent_points) ?? min;
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
        <title>VRP {windowLabel}时序</title>
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
          观察日
        </text>
      </svg>
      <figcaption>
        DVOL 为 Deribit 前瞻隐含波动率指数；RV30 为向后 30 日已实现波动率，
        二者观察口径不同。源时间戳与日结边界以公开 API 字段为准。
      </figcaption>
    </figure>
  );
}

function PublicVrpOverview({
  freshness,
  report,
  summary,
}: {
  freshness: PublicFreshness;
  report: ResearchReport;
  summary: PublicReleaseSummary | null;
}): React.JSX.Element {
  const vrp = report.vrp_status;
  const state = publicMarketDisplayState(report, freshness);
  const {
    currentBand,
    currentDvol,
    currentRv30,
    currentVrp,
    minimumSampleCount,
    percentile,
    sampleCount,
    series,
    unavailableCode,
    windowDays,
  } = publicVrpSeries(report);
  const windowLabel = vrpWindowLabel(windowDays, series);
  const isInsufficientHistory =
    vrp?.status === "insufficient_history" ||
    vrp?.reason_code === "INSUFFICIENT_VRP_HISTORY";
  const insufficientHistoryDetail =
    sampleCount !== null &&
    sampleCount !== undefined &&
    minimumSampleCount !== null &&
    minimumSampleCount !== undefined
      ? `当前仅累积 ${sampleCount.toLocaleString("zh-CN")} / ${minimumSampleCount.toLocaleString("zh-CN")} 个有效 VRP 读数，头条数字保持隐藏。`
      : "VRP 有效样本还不够，头条数字保持隐藏，只提供补齐进度。";

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
            这版公开稿已超过发布时效上限，VRP、DVOL、曲面与候选数字全部收起，
            直到下一版发布。
          </p>
          <small>{formatPublishedAge(freshness.ageSec)}</small>
        </div>
      ) : isValidatedVrpStatus(vrp?.status) && currentVrp !== null ? (
        <div className="vrp-layout">
          <div className="vrp-hero">
            <span className="vrp-label">BTC 卖方溢价</span>
            <strong>{formatPoints(currentVrp)}</strong>
            <VrpChangeLine band={currentBand} summary={summary} />
            <p>
              DVOL {formatPercent(currentDvol, 1)} - RV30{" "}
              {formatPercent(currentRv30, 1)}
            </p>
          </div>
          <div className="vrp-scale" data-tone={bandTone(currentBand)}>
            <div className="vrp-scale-copy">
              <span>{windowLabel}经验百分位</span>
              <strong>{percentileLabel(percentile)}</strong>
              <small>{currentBand ?? "未分带"}</small>
            </div>
            <ol aria-label="VRP 刻度带">
              {["P90", "P70", "P30", "P10"].map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </div>
          <VrpSeriesChart points={series} windowLabel={windowLabel} />
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
          <PublicReasonNotice
            codes={[unavailableCode]}
            detailOverrides={
              isInsufficientHistory
                ? { INSUFFICIENT_VRP_HISTORY: insufficientHistoryDetail }
                : undefined
            }
          />
        </div>
      )}
    </section>
  );
}

function MarketMetric({
  label,
  tone = "muted",
  value,
}: {
  label: string;
  tone?: "danger" | "muted" | "safe" | "warning";
  value: string;
}): React.JSX.Element {
  return (
    <div className="market-metric" data-tone={tone}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function CandidateBriefRow({
  candidate,
}: {
  candidate: CandidateRow;
}): React.JSX.Element {
  const metric =
    candidate.kind === "spread"
      ? `${formatDecimal(candidate.premium, 4)} BTC`
      : `Δ ${formatDecimal(candidate.delta, 3)}`;
  return (
    <li className="brief-candidate">
      <div>
        <span>{candidate.kind === "spread" ? "CALL 价差" : "单腿 CALL"}</span>
        <strong>{candidate.contract}</strong>
      </div>
      <div>
        <span>{formatExpiry(candidate.expiry)}</span>
        <strong>{metric}</strong>
      </div>
    </li>
  );
}

function PublicMarketBrief({
  freshness,
  report,
}: {
  freshness: PublicFreshness;
  report: ResearchReport;
}): React.JSX.Element {
  const displayState = publicMarketDisplayState(report, freshness);
  const facts = marketFacts(report);
  const candidates = researchCandidates(report);
  const hasMarketEvidence =
    displayState === "available" && facts.underlyingPrice !== null;
  const candidateTotal =
    (facts.nakedCandidates ?? 0) + (facts.spreadCandidates ?? 0);
  const invalidQuotes = finiteNumber(
    report.data_status?.quality_gate?.summary?.invalid_quotes,
  );
  const quarantineCopy =
    invalidQuotes !== null && invalidQuotes > 0
      ? `；${invalidQuotes.toLocaleString("zh-CN")} 条未通过质量门的报价已隔离，不进入研究计算。`
      : "。";
  const narrative =
    displayState === "stale"
      ? "这版公开稿已超过发布时效上限，所有当前市场数字视图已统一收起，等待下一版发布。"
      : !hasMarketEvidence
        ? "当前没有可验证的市场快照，价格、DVOL、曲面与候选不会被估算或补齐。"
        : `${facts.validQuotes ?? "—"} 条报价通过质量门；${facts.eligibleExpiries ?? "—"} 个到期曲面可进入候选研究${quarantineCopy}`;
  const visibleCandidates = hasMarketEvidence ? candidates.slice(0, 4) : [];
  const age =
    freshness.ageSec === null ? "距今时间不可验证" : formatPublishedAge(freshness.ageSec);

  return (
    <section
      id="brief"
      className="market-brief"
      aria-label="实时研究摘要"
    >
      <div className="market-pulse">
        <header className="report-folio">
          <p>BTC options / Deribit research sample</p>
          <dl>
            <div>
              <dt>报告</dt>
              <dd>{report.schema_version}</dd>
            </div>
            <div>
              <dt>生成</dt>
              <dd>{formatTimestamp(report.generated_at)}</dd>
            </div>
          </dl>
        </header>
        <div className="market-lockup">
          <p className="section-kicker">Market pulse / 市场脉搏</p>
          <h2>BTC 市场脉搏</h2>
          {displayState === "quality_blocked" ? (
            <strong className="market-state-title">市场数据当前不可发布</strong>
          ) : null}
          {displayState === "stale" ? (
            <strong className="market-state-title">发布已停摆</strong>
          ) : null}
          <div className="underlying-price" data-available={hasMarketEvidence}>
            {hasMarketEvidence ? formatUsd(facts.underlyingPrice) : "—"}
          </div>
          <div className="dvol-line">
            <span>BTC DVOL</span>
            <strong>
              {displayState === "stale"
                ? "已收起"
                : hasMarketEvidence
                  ? formatDvol(facts.dvol)
                  : "不可用"}
            </strong>
          </div>
          <p className="market-narrative">{narrative}</p>
        </div>
        <section
          className="freshness-status"
          data-state={freshness.phase}
          aria-label="市场证据新鲜度"
        >
          <span className="freshness-dot" aria-hidden="true" />
          <div>
            <span>市场证据</span>
            <strong aria-live="polite">{FRESHNESS_LABELS[freshness.phase]}</strong>
          </div>
          <div>
            <span>数据采集距今</span>
            <strong>{age}</strong>
          </div>
          <div>
            <span>发布失效边界</span>
            <strong>{formatDurationHours(freshness.maxAgeSec)}</strong>
          </div>
          <div className="freshness-source">
            <span>来源与时钟口径</span>
            <strong>{facts.source}</strong>
            <small>以快照采集时间为起点，按浏览器当前时钟评估。</small>
          </div>
        </section>
        <div className="market-metrics" aria-label="实时研究指标">
          <MarketMetric
            label="报价质量"
            value={
              hasMarketEvidence &&
              facts.validQuotes !== null &&
              facts.totalQuotes !== null
                ? `${facts.validQuotes} / ${facts.totalQuotes} 条有效报价`
                : "无可验证报价"
            }
            tone={hasMarketEvidence ? "safe" : "danger"}
          />
          <MarketMetric
            label="曲面覆盖"
            value={
              hasMarketEvidence &&
              facts.eligibleExpiries !== null &&
              facts.evaluatedExpiries !== null
                ? `${facts.eligibleExpiries} / ${facts.evaluatedExpiries} 个到期可用`
                : "无可用曲面"
            }
            tone={
              hasMarketEvidence && (facts.eligibleExpiries ?? 0) > 0
                ? "safe"
                : "warning"
            }
          />
          <MarketMetric
            label="单腿研究"
            value={
              hasMarketEvidence && facts.nakedCandidates !== null
                ? `${facts.nakedCandidates} 个单腿候选`
                : "无候选"
            }
          />
          <MarketMetric
            label="价差研究"
            value={
              hasMarketEvidence && facts.spreadCandidates !== null
                ? `${facts.spreadCandidates} 个价差候选`
                : "无候选"
            }
          />
        </div>
      </div>

      <aside className="candidate-sheet" aria-label="今日研究候选">
        <div className="candidate-sheet-heading">
          <div>
            <p className="section-kicker">Research candidates</p>
            <h2>今日研究候选</h2>
          </div>
          <span>{hasMarketEvidence ? `${candidateTotal} 个通过筛选` : "数据不可用"}</span>
        </div>
        {visibleCandidates.length > 0 ? (
          <ol className="brief-candidate-list">
            {visibleCandidates.map((candidate) => (
              <CandidateBriefRow candidate={candidate} key={candidate.id} />
            ))}
          </ol>
        ) : (
          <div className="brief-empty">
            <strong>没有可展示的研究候选</strong>
            <p>只有在当前市场证据与曲面质量均可验证时，候选才会出现在这里。</p>
          </div>
        )}
        <div className="candidate-boundary">
          <span>仅表示通过研究筛选</span>
          <strong>NO-GO · NO_TRADE</strong>
        </div>
      </aside>
    </section>
  );
}

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

function PublicSurfaceResearch({
  freshness,
  report,
}: {
  freshness: PublicFreshness;
  report: ResearchReport;
}): React.JSX.Element {
  const expiries = report.vol_surface_status?.expiries ?? [];
  const displayState = publicMarketDisplayState(report, freshness);
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
          拟合质量和无套利检查分开展示；只有两者都通过，曲面才进入候选研究。
        </p>
      </header>
      {displayState === "stale" ? (
        <div className="section-empty published-stop-state" role="status">
          <strong>发布已停摆</strong>
          <p>当前公开版已超过时效上限，曲面图和到期数字全部收起，直到下一版发布。</p>
        </div>
      ) : chartAvailable ? (
        <div className="surface-layout">
          <SurfaceChart expiries={expiries} />
          <div className="surface-expiries" aria-label="到期曲面质量">
            {expiries.map((expiry) => {
              const tone = expiry.candidate_eligible
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
          <p>页面不会根据缺失报价推算曲线；请检查市场数据来源，或重新读取静态快照。</p>
        </div>
      )}
    </section>
  );
}

function PublicCandidateResearch({
  freshness,
  report,
}: {
  freshness: PublicFreshness;
  report: ResearchReport;
}): React.JSX.Element {
  const candidates = researchCandidates(report);
  const summary = report.candidate_research?.summary;
  const displayState = publicMarketDisplayState(report, freshness);
  return (
    <section
      className="research-section candidates-section"
      aria-labelledby="candidates-title"
    >
      <header className="research-section-heading">
        <div>
          <p className="section-kicker">Candidate research / 只读</p>
          <h2 id="candidates-title">研究候选清单</h2>
        </div>
        <p>
          {summary?.eligible_naked_short_calls ?? 0} 个单腿、
          {summary?.eligible_call_credit_spreads ?? 0} 个价差通过当前过滤；这不是交易建议。
        </p>
      </header>
      {displayState === "stale" ? (
        <div className="section-empty published-stop-state" role="status">
          <strong>发布已停摆</strong>
          <p>候选排序依赖当前市场截面；在公开版过期后，这些数字不会继续对外展示。</p>
        </div>
      ) : candidates.length > 0 ? (
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
      ) : (
        <div className="section-empty" role="status">
          <strong>没有通过筛选的研究候选</strong>
          <p>当前报告没有可验证的候选行；页面不会构造示例策略。</p>
        </div>
      )}
    </section>
  );
}

function PublicExchangeEventEvidence({
  displayState,
  report,
}: {
  displayState: "available" | "quality_blocked" | "stale";
  report: ResearchReport;
}): React.JSX.Element {
  const reading = resolvePublicExchangeEventEvidence(report);
  const isStale = displayState === "stale";
  const isQualityBlocked = displayState === "quality_blocked";
  const reasonCode = isStale
    ? "PUBLISHED_EDITION_STALE"
    : isQualityBlocked
      ? (report.data_status?.reason_code ?? "EVENT_SOURCE_UNAVAILABLE")
      : reading.reasonCode;
  const reason = readPublicReasonCode(reasonCode);
  const stateLabel = isStale
    ? "已过期（按阻断处理）"
    : isQualityBlocked
      ? "报告被阻断（状态不发布）"
      : reading.stateLabel;
  const scoreLabel = isStale ? "已收起" : isQualityBlocked ? "不可用" : reading.scoreLabel;
  const blocked = displayState !== "available" || reading.blocked;

  return (
    <section
      aria-label="公开事件源与交易所锁定"
      className="entry-contract"
      role="region"
    >
      <header className="workflow-subheading compact">
        <div>
          <span>Event evidence / 公开证据</span>
          <h3>事件源与交易所锁定</h3>
        </div>
        <strong data-status={blocked ? "block" : "pass"}>{stateLabel}</strong>
      </header>
      <div className="condition-grid">
        <article data-status={blocked ? "block" : "pass"}>
          <div>
            <span>事件分</span>
            <strong>{scoreLabel}</strong>
          </div>
          <p>{reading.sourceLabel}</p>
          <small>该来源只覆盖交易所锁定状态，不覆盖宏观事件日历。</small>
        </article>
        <article data-status={blocked ? "block" : "pass"}>
          <div>
            <span>判定原因</span>
            <code>{reasonCode}</code>
          </div>
          <p>{displayState === "available" ? reading.detail : reason.detail}</p>
          <small>缺失、过期、异常或非契约分值一律按阻断处理。</small>
        </article>
      </div>
    </section>
  );
}

function PublicStrategySection({
  freshness,
  report,
}: {
  freshness: PublicFreshness;
  report: ResearchReport;
}): React.JSX.Element {
  const displayState = publicMarketDisplayState(report, freshness);
  const playbook = report.strategy_research?.playbook;
  const candidate = playbook?.candidate;
  const economics = playbook?.economics;
  const conditionCount = playbook?.entry_contract?.conditions?.length ?? 0;
  const blockingCount =
    playbook?.entry_contract?.conditions?.filter(
      (condition) => condition.status !== "pass",
    ).length ?? 0;

  return (
    <section
      id="framework"
      className="research-section strategy-workflow"
      aria-label="完整策略工作流"
    >
      <header className="strategy-verdict">
        <div className="strategy-verdict-copy">
          <p className="section-kicker">Decision workflow / 研究闭环</p>
          <div className="strategy-title-line">
            <h2>卖它值不值</h2>
            <span className="stance-badge" data-tone="warning">
              研究只读
            </span>
          </div>
          <strong className="primary-structure">
            {report.strategy_research?.decision?.primary_structure === "CALL_CREDIT_SPREAD"
              ? "CALL 信用价差"
              : "当前无主策略"}
          </strong>
          <p>
            公开版只保留结构、候选和定价证据；内部控制层不进入这份构建。
          </p>
        </div>
        <div className="strategy-verdict-aside">
          <span>研究置信上限</span>
          <strong>
            {report.strategy_research?.confidence_ceiling === "screening_only"
              ? "筛选级"
              : "证据不足"}
          </strong>
          <p>只读 · 不生成仓位 · 不生成订单</p>
        </div>
      </header>

      <PublicExchangeEventEvidence
        displayState={displayState}
        report={report}
      />

      {displayState === "stale" ? (
        <div className="strategy-empty published-stop-state" role="status">
          <strong>发布已停摆</strong>
          <p>公开版过期后，策略样本、定价影子与候选比较全部收起，直到下一版发布。</p>
        </div>
      ) : playbook && candidate ? (
        <>
          <article className="strategy-plan">
            <header className="strategy-plan-heading">
              <div>
                <span>公开研究样本</span>
                <h3>定义风险结构，不延伸到内部控制层</h3>
              </div>
              <strong>{formatExpiry(candidate.expiry_date ?? null)}</strong>
            </header>
            <div className="strategy-legs">
              <div data-leg="sell">
                <span>卖出腿 · 研究假设</span>
                <strong>{candidate.sell_leg ?? "—"}</strong>
                <small>Strike {formatUsd(finiteNumber(candidate.sell_strike_usd))}</small>
              </div>
              <span className="leg-connector" aria-hidden="true">
                →
              </span>
              <div data-leg="buy">
                <span>买入保护腿</span>
                <strong>{candidate.buy_leg ?? "—"}</strong>
                <small>Strike {formatUsd(finiteNumber(candidate.buy_strike_usd))}</small>
              </div>
            </div>
            <dl className="strategy-economics">
              <div>
                <dt>净信用影子</dt>
                <dd>{formatUsd(finiteNumber(economics?.credit_usd_shadow))}</dd>
                <small>{formatDecimal(finiteNumber(economics?.credit_coin), 4)} BTC</small>
              </div>
              <div>
                <dt>参考最大损失</dt>
                <dd>
                  {formatUsd(
                    finiteNumber(economics?.reference_max_loss_usd_shadow),
                  )}
                </dd>
                <small>仅保留公开研究影子，不进入内部控制层</small>
              </div>
              <div>
                <dt>参考盈亏平衡</dt>
                <dd>{formatUsd(finiteNumber(economics?.breakeven_usd_shadow))}</dd>
                <small>执行价 + 入场信用的 USD 影子</small>
              </div>
              <div>
                <dt>组合 Delta</dt>
                <dd>{formatDecimal(finiteNumber(candidate.model_delta), 3)}</dd>
                <small>
                  RN P(ITM){" "}
                  {formatPercent(finiteNumber(candidate.risk_neutral_p_itm), 1)}
                </small>
              </div>
            </dl>
          </article>

          <section className="entry-contract" aria-label="条件式进场规则">
            <header className="workflow-subheading">
              <div>
                <span>公开门槛</span>
                <h3>仍然保留的研究条件</h3>
              </div>
              <strong data-status={playbook.entry_contract?.status}>
                {playbook.entry_contract?.status === "ready" ? "条件满足" : "当前不进场"}
              </strong>
            </header>
            <div className="condition-grid">
              <article data-status={playbook.entry_contract?.status ?? "blocked"}>
                <div>
                  <span>公开条件总数</span>
                  <strong>{conditionCount}</strong>
                </div>
                <p>仅展示公开研究门槛；内部控制条件不在 bundle 内。</p>
                <small>按当前快照逐次重算</small>
              </article>
              <article data-status={blockingCount === 0 ? "pass" : "block"}>
                <div>
                  <span>仍未同时满足</span>
                  <strong>{blockingCount}</strong>
                </div>
                <p>只要还有未满足条件，公开页就保持研究只读。</p>
                <small>不生成仓位、订单或自动动作</small>
              </article>
            </div>
            <p className="strategy-note entry-note">
              公开入口只展示研究门槛，不打包内部控制层字段或内部动作目录。
            </p>
          </section>
        </>
      ) : (
        <div className="strategy-empty" role="status">
          <strong>当前没有可验证的公开策略样本</strong>
          <p>只有当真实证据到位时，公开页才会填充结构、候选与影子定价。</p>
        </div>
      )}
    </section>
  );
}

function PublicBoundarySection({
  freshness,
  report,
}: {
  freshness: PublicFreshness;
  report: ResearchReport;
}): React.JSX.Element {
  const displayState = publicMarketDisplayState(report, freshness);
  const publicationStatus =
    report.runtime_context?.mode === "published"
      ? "公开版"
      : report.data_status?.validated === true
        ? "研究快照"
        : "等待验证";
  const marketBoundary =
    displayState === "stale"
      ? "发布已停摆"
      : report.data_status?.validated === true
        ? "快照已验证"
        : "快照未达发布条件";
  const trustBoundary =
    report.data_trust?.verdict === "trusted"
      ? "证据链可信"
      : "证据链未提升";

  return (
    <section
      id="limitations"
      className="research-section limitations-section"
      aria-labelledby="limitations-title"
    >
      <header className="research-section-heading boundary-heading">
        <div>
          <p className="section-kicker">Research boundary / 研究边界</p>
          <h2 id="limitations-title">凭什么信</h2>
        </div>
      </header>

      <section className="truth-strip" aria-label="三项研究边界">
        <dl>
          <div data-tone="safe">
            <dt>公开形态</dt>
            <dd>{publicationStatus}</dd>
          </div>
          <div data-tone={displayState === "available" ? "safe" : "warning"}>
            <dt>市场证据</dt>
            <dd>{marketBoundary}</dd>
          </div>
          <div data-tone={report.data_trust?.verdict === "trusted" ? "safe" : "warning"}>
            <dt>证据链</dt>
            <dd>{trustBoundary}</dd>
          </div>
          <div data-tone="danger">
            <dt>运行边界</dt>
            <dd>RESEARCH_ONLY · NO_TRADE</dd>
          </div>
        </dl>
      </section>

      <PublicReasonNotice codes={report.reason_codes ?? []} />

      <div className="blocked-output-note">
        <div>
          <strong>公开 bundle 只保留研究叙事与公开证据。</strong>
          <p>内部 dashboard 与控制层字段不进入公开构建；公开原因码保留脱敏解释。</p>
        </div>
        <p>数据截止：{formatCutoffTime(report.publish_edition?.captured_at ?? report.generated_at ?? null)}</p>
      </div>
    </section>
  );
}

export function PublicEvidenceView({
  freshness,
  report,
  signalSection = null,
  summary,
}: {
  freshness: PublicFreshness;
  report: ResearchReport;
  signalSection?: React.ReactNode;
  summary: PublicReleaseSummary | null;
}): React.JSX.Element {
  return (
    <main className="console" id="surface-main">
      <PublicVrpOverview freshness={freshness} report={report} summary={summary} />
      <PublicMarketBrief freshness={freshness} report={report} />
      <PublicStrategySection freshness={freshness} report={report} />
      <PublicSurfaceResearch freshness={freshness} report={report} />
      <PublicCandidateResearch freshness={freshness} report={report} />
      {signalSection}
      <PublicBoundarySection freshness={freshness} report={report} />
    </main>
  );
}
