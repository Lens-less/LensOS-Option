import type { ResearchReport } from "../../contracts";
import {
  FRESHNESS_LABELS,
  friendlySource,
  marketDisplayState,
} from "./reportModel";
import type { Freshness, Tone } from "./reportModel";
import {
  formatDecimal,
  formatDvol,
  formatExpiry,
  formatTimestamp,
  formatUsd,
} from "./marketModel";
import type { CandidateRow, MarketFacts } from "./marketModel";

function FreshnessStatus({
  freshness,
  report,
}: {
  freshness: Freshness;
  report: ResearchReport;
}): React.JSX.Element {
  const age =
    freshness.ageSec === null
      ? "无可验证年龄"
      : `${freshness.ageSec.toLocaleString("zh-CN")} 秒`;
  return (
    <section
      className="freshness-status"
      data-state={freshness.phase}
      aria-label="市场证据新鲜度"
    >
      <span className="freshness-dot" aria-hidden="true" />
      <div>
        <span>市场证据</span>
        {/* Only the phase is announced. The age below re-renders every second,
            so a live region there would read the counter aloud continuously. */}
        <strong aria-live="polite">{FRESHNESS_LABELS[freshness.phase]}</strong>
      </div>
      <div>
        <span>数据年龄</span>
        <strong>{age}</strong>
      </div>
      <div>
        <span>失效上限</span>
        <strong>{freshness.maxAgeSec} 秒</strong>
      </div>
      <div className="freshness-source">
        <span>来源</span>
        <strong>{friendlySource(report.data_status?.source)}</strong>
      </div>
    </section>
  );
}

function MarketMetric({
  label,
  value,
  tone = "muted",
}: {
  label: string;
  value: string;
  tone?: Tone;
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

export function MarketBrief({
  candidates,
  facts,
  freshness,
  report,
}: {
  candidates: CandidateRow[];
  facts: MarketFacts;
  freshness: Freshness;
  report: ResearchReport;
}): React.JSX.Element {
  const displayState = marketDisplayState(report, freshness);
  const hasMarketEvidence =
    displayState === "available" && facts.underlyingPrice !== null;
  const candidateTotal =
    (facts.nakedCandidates ?? 0) + (facts.spreadCandidates ?? 0);
  const narrative = displayState === "stale"
    ? "这版公开稿已超过发布时效上限；所有当前市场数字视图已统一收起，等待下一版发布。"
    : !hasMarketEvidence
      ? "当前没有可验证的市场快照；价格、DVOL、曲面与候选不会被估算或补齐。"
    : `${facts.validQuotes ?? "—"} 条报价通过质量门；${
        facts.eligibleExpiries ?? "—"
      } 个到期曲面可进入候选研究。`;
  const visibleCandidates = hasMarketEvidence ? candidates.slice(0, 4) : [];

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
        <FreshnessStatus freshness={freshness} report={report} />
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
