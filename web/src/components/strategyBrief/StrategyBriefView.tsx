import { useEffect, useId, useRef, useState } from "react";

import {
  projectStrategyBriefForSurface,
  type StrategyBrief,
  type StrategyBriefForecast,
  type StrategyBriefHistory,
  type StrategyBriefStrategy,
  type StrategyBriefSurfaceProjection,
  type StrategyBriefSurfaceState,
} from "../../report/strategyBrief";

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "未提供";
  }
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "Asia/Shanghai",
  }).format(parsed) + " UTC+8";
}

function formatNumber(value: number | null, digits = 4): string {
  if (value === null) {
    return "暂不可用";
  }
  return value.toLocaleString("en-US", {
    useGrouping: false,
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function formatPercent(value: number | null): string {
  if (value === null) {
    return "暂不可用";
  }
  return `${(value * 100).toFixed(0)}%`;
}

function structureLabel(value: StrategyBriefStrategy["structure_type"]): string {
  if (value === "BULL_PUT_CREDIT_SPREAD") {
    return "牛市看跌价差 · Bull Put Credit Spread";
  }
  if (value === "BEAR_CALL_CREDIT_SPREAD") {
    return "熊市看涨价差 · Bear Call Credit Spread";
  }
  return "铁鹰双边价差 · Iron Condor";
}

function actionLabel(value: StrategyBriefSurfaceProjection["action"]): string {
  if (value === "STRATEGIES_AVAILABLE") {
    return "通过研究门槛 · 仍需人工复核";
  }
  if (value === "WATCH") {
    return "仅观察 · 尚未达到推荐标准";
  }
  return "没有候选通过完整研究门槛";
}

function recommendationLabel(
  value: StrategyBriefStrategy["recommendation_status"],
): string {
  return value === "RECOMMENDED" ? "推荐" : "观察";
}

function historyLabel(history: StrategyBriefHistory): string {
  if (history.status === "VALIDATED") {
    return `历史：胜率 ${formatPercent(history.win_rate)} · 平均净 R ${history.mean_net_r?.toFixed(2)} · ${history.independent_cohorts ?? 0} 个到期 cohort`;
  }
  if (history.status === "FAILED") {
    return "历史：未通过";
  }
  if (history.status === "EXPLORATORY") {
    return "历史：探索中";
  }
  return "历史：样本不足";
}

function forecastLabel(forecast: StrategyBriefForecast): string {
  if (forecast.status === "CALIBRATED") {
    const confidence = {
      HIGH: "高",
      MEDIUM: "中",
      LOW: "低",
      UNAVAILABLE: "不可用",
    }[forecast.confidence ?? "UNAVAILABLE"];
    return `预测：${formatPercent(forecast.win_rate_low)}-${formatPercent(forecast.win_rate_high)} · 可信度 ${confidence}`;
  }
  if (forecast.status === "RETIRED") {
    return "预测：已退役";
  }
  if (forecast.status === "SCREENING_ONLY") {
    return "预测：仅筛选级";
  }
  return "预测：暂不可用";
}

function buildResearchReviewCopy(
  brief: StrategyBrief,
  strategy: StrategyBriefStrategy,
  surface?: StrategyBriefSurfaceState,
): string {
  const recipe = strategy.copy_recipe;
  const context = [
    `BRIEF ID: ${brief.brief_id}`,
    `RECOMMENDATION ID: ${strategy.recommendation_id}`,
    `SOURCE: ${surface?.source_label ?? "未提供"} (${surface?.source_kind ?? "fallback"}; ${surface?.presented_as ?? "published"})`,
    `MARKET AS OF: ${brief.market.as_of}`,
  ];
  // Older v1 records remain reviewable, with context from validated fields.
  if (!recipe.includes("STATUS:")) context.push(`STATUS: ${strategy.recommendation_status} / execution_allowed=false`);
  if (!recipe.includes("ANALYSIS RUN:")) context.push(`ANALYSIS RUN: ${brief.analysis_run_id}`);
  if (!recipe.includes("EVALUATED AT:")) context.push(`EVALUATED AT: ${brief.generated_at}`);
  if (!recipe.includes("CONTRACT EXPIRY:")) context.push(`CONTRACT EXPIRY: ${strategy.expiry_date ?? "见合约名，须人工复核"}`);
  if (!recipe.includes("LEG QUOTE:")) {
    context.push(...strategy.legs.map((leg) =>
      `LEG QUOTE: ${leg.instrument_name} / BID ${leg.bid} / ASK ${leg.ask} / ${leg.premium_currency ?? strategy.entry.currency} (${leg.premium_unit}) / OBSERVED AT ${leg.observed_at}`,
    ));
  }
  const recheck = recipe.includes("RECHECK:") ? [] : [
    "RECHECK: 复核前重新取得正的、同步的双边报价，重新评估证据与冻结成本。超过 VALID UNTIL 后不得沿用。本记录不构成订单或执行授权。",
  ];
  return [...context, recipe, ...recheck].join("\n");
}

function buildRejectionReviewCopy(
  brief: StrategyBrief,
  projection: StrategyBriefSurfaceProjection,
  reasons: string[],
  surface?: StrategyBriefSurfaceState,
): string {
  return [
    "RESEARCH_ONLY / MANUAL REVIEW REQUIRED",
    "STATUS: NO_TRADE / execution_allowed=false",
    `BRIEF ID: ${brief.brief_id}`,
    `ANALYSIS RUN: ${brief.analysis_run_id}`,
    `SOURCE: ${surface?.source_label ?? "未提供"} (${surface?.source_kind ?? "fallback"}; ${surface?.presented_as ?? "published"})`,
    `SOURCE FRESHNESS: ${surface?.freshness_status ?? "UNAVAILABLE"}`,
    `MARKET AS OF: ${brief.market.as_of}`,
    `EVALUATED AT: ${brief.generated_at}`,
    `SNAPSHOT EXPIRES AT: ${brief.market.expires_at}`,
    ...(projection.suppression.suppress_cards ? [
      "CURRENT QUALIFICATION: PAUSED / 当前资格已暂停；快照判定仅作为历史记录，不恢复当前资格。",
    ] : ["CURRENT QUALIFICATION: NO_TRADE / 当前没有可复核的策略卡。"]),
    ...reasons.map((reason) => `REASON: ${reason}`),
    ...projection.suppression.reasons_zh.map((reason) => `SUPPRESSION REASON: ${reason}`),
    `SNAPSHOT REASON CODES: ${projection.no_trade.primary_reason_codes.join(", ") || "未提供"}`,
    ...Object.entries(brief.evidence_summary.rejection_counts).map(
      ([code, count]) => `SNAPSHOT REJECTION COUNT: ${code} / ${count}`,
    ),
    "RECHECK: 重新取得有效来源与双边报价，重新评估证据和成本。已过期的判定不得沿用；本记录只解释研究阻断，不构成订单或执行授权。",
  ].join("\n");
}

function CopyResearchReviewButton({
  text,
  label = "复制研究复核",
  copiedLabel = "已复制研究复核",
  copiedMessage = "已复制报价、成本和证据标识；复核前须重新取数。",
}: {
  text: string;
  label?: string;
  copiedLabel?: string;
  copiedMessage?: string;
}): React.JSX.Element {
  const [status, setStatus] = useState<"idle" | "copying" | "copied" | "failed">("idle");
  const statusId = useId();
  const recipeId = useId();
  const request = useRef(0);
  useEffect(() => {
    setStatus("idle");
    return () => { request.current += 1; };
  }, [text]);
  return (
    <div className="strategy-brief-copy-area">
    <button
      className="strategy-brief-copy"
      aria-describedby={statusId}
      disabled={status === "copying"}
      onClick={() => {
        const sequence = ++request.current;
        setStatus("copying");
        void (async () => {
          try {
            if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
            await navigator.clipboard.writeText(text);
            if (request.current === sequence) setStatus("copied");
          } catch {
            if (request.current === sequence) setStatus("failed");
          }
        })();
      }}
      type="button"
    >
      {status === "copied" ? copiedLabel : status === "copying" ? "复制中…" : label}
    </button>
    <p id={statusId} role="status" className="strategy-brief-copy-status">
      {status === "copied" ? copiedMessage
        : status === "failed" ? "无法访问剪贴板，请选择下方复核文本手动复制。" : ""}
    </p>
    {status === "failed" ? (
      <div className="strategy-brief-copy-fallback">
        <label htmlFor={recipeId}>研究复核文本</label>
        <textarea id={recipeId} readOnly value={text} rows={8}
          onFocus={(event) => event.currentTarget.select()} />
      </div>
    ) : null}
    </div>
  );
}

function StrategyCard({
  strategy,
  brief,
  surface,
}: {
  strategy: StrategyBriefStrategy;
  brief: StrategyBrief;
  surface?: StrategyBriefSurfaceState;
}): React.JSX.Element {
  return (
    <article
      className="strategy-brief-card"
      data-status={strategy.recommendation_status}
    >
      <header className="strategy-brief-card-header">
        <div>
          <p className="strategy-brief-card-rank">
            #{strategy.rank} {structureLabel(strategy.structure_type)}
          </p>
          <strong>{recommendationLabel(strategy.recommendation_status)}</strong>
        </div>
        <p className="strategy-brief-card-valid">
          有效至 {formatTimestamp(strategy.valid_until)}
        </p>
      </header>
      <p>{strategy.thesis_zh}</p>
      <ul aria-label={`${structureLabel(strategy.structure_type)} 精确合约腿`}>
        {strategy.legs.map((leg) => (
          <li className="strategy-brief-leg" key={`${leg.side}-${leg.instrument_name}`}>
            <strong>
              {leg.side} {leg.quantity}
            </strong>{" "}
            {leg.instrument_name}
            <p className="strategy-brief-leg-quote">
              Bid {String(leg.bid)} / Ask {String(leg.ask)}{" "}
              {leg.premium_currency ?? strategy.entry.currency} · {leg.premium_unit}
            </p>
          </li>
        ))}
      </ul>
      <dl className="strategy-brief-metrics">
        <div>
          <dt>最低净权利金</dt>
          <dd>
            {formatNumber(strategy.entry.minimum_net_credit)} {strategy.entry.currency}
          </dd>
        </div>
        <div>
          <dt>模型损失上限</dt>
          <dd>
            {formatNumber(strategy.risk.max_loss_per_unit)} {strategy.risk.currency}
          </dd>
        </div>
        <div>
          <dt>到期 / DTE</dt>
          <dd>
            {strategy.expiry_date ?? "见合约名"}
            {strategy.dte_days === undefined ? "" : ` · ${formatNumber(strategy.dte_days, 1)} 天`}
          </dd>
        </div>
        <div>
          <dt>入场口径</dt>
          <dd>卖出按 bid / 买入按 ask · 已扣入场成本预算</dd>
        </div>
      </dl>
      <p className="strategy-brief-cost-boundary">
        模型损失上限包含列明的成本预算；未来交割费可能超出预算，实际损失可能更高。当前仅观察。
      </p>
      <details className="strategy-brief-review-details">
        <summary>查看报价时间与研究来源</summary>
        <dl>
          {strategy.legs.map((leg) => (
            <div key={leg.instrument_name}>
              <dt>{leg.instrument_name} 采集于</dt>
              <dd>{formatTimestamp(leg.observed_at)}</dd>
            </div>
          ))}
          <div><dt>评估于</dt><dd>{formatTimestamp(brief.generated_at)}</dd></div>
          <div><dt>分析标识</dt><dd><code>{brief.analysis_run_id}</code></dd></div>
          <div><dt>简报标识</dt><dd><code>{brief.brief_id}</code></dd></div>
        </dl>
        <p>这是该时点的研究记录。复核前须重新取得双边报价并重新评估成本与证据，超过有效期不得沿用。</p>
      </details>
      <details className="strategy-brief-risk-details">
        <summary>查看成本预算与模型风险</summary>
        <dl>
          {([
            ["入场手续费", strategy.entry.cost_breakdown.entry_fees],
            ["滑点准备", strategy.entry.cost_breakdown.slippage_reserve],
            ["分腿成交准备", strategy.entry.cost_breakdown.legging_reserve],
            ["结算费用准备", strategy.entry.cost_breakdown.settlement_reserve],
          ] as const).map(([label, value]) => (
            <div key={label}><dt>{label}</dt><dd>{formatNumber(value)} {strategy.entry.currency}</dd></div>
          ))}
          <div><dt>预算内到期盈亏平衡价格</dt><dd>{strategy.risk.breakevens.map((value) => formatNumber(value, 2)).join(" / ")} {strategy.risk.currency}</dd></div>
          <div><dt>尾部平均损失估计（CVaR 95）</dt><dd>{formatNumber(strategy.risk.cvar_95)} {strategy.risk.currency}</dd></div>
        </dl>
        <p>风险估计依赖模型与适用范围；成本准备金不代表已验证的未来费用上界。</p>
        <p>成本模型 <code>{strategy.entry.cost_model_id}</code></p>
      </details>
      <p>{historyLabel(strategy.history)}</p>
      <p>{forecastLabel(strategy.forecast)}</p>
      {strategy.kill_conditions.length > 0 ? (
        <ul aria-label="取消条件">
          {strategy.kill_conditions.map((condition) => (
            <li key={condition}>取消条件：{condition}</li>
          ))}
        </ul>
      ) : null}
      <CopyResearchReviewButton text={buildResearchReviewCopy(brief, strategy, surface)} />
    </article>
  );
}

function MissingStrategyBriefView({
  surface,
}: {
  surface?: StrategyBriefSurfaceState;
}): React.JSX.Element {
  return (
    <section className="strategy-brief-view" aria-label="策略简报">
      <header className="strategy-brief-header">
        <p>BTC</p>
        <h2>今日暂无可靠策略</h2>
        <p role="status">当前运行时尚未提供 `strategy_brief.v1`，因此不展示策略卡。</p>
        <dl>
          <div>
            <dt>来源</dt>
            <dd>{surface?.source_label ?? "未提供"}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>{surface?.freshness_status ?? "UNAVAILABLE"}</dd>
          </div>
        </dl>
      </header>
    </section>
  );
}

export function StrategyBriefView({
  brief,
  surface,
}: {
  brief?: StrategyBrief | null;
  surface?: StrategyBriefSurfaceState;
}): React.JSX.Element {
  if (!brief) {
    return <MissingStrategyBriefView surface={surface} />;
  }

  const effectiveSurface = surface ?? brief.evidence_summary.surface;
  const projection = projectStrategyBriefForSurface(brief, effectiveSurface);
  const visibleAction = projection.action;
  const suppressed = projection.suppression.suppress_cards;
  const noTradeReasons = Array.from(new Set([
    ...(projection.no_trade.reasons_zh ?? []),
    ...projection.suppression.reasons_zh,
  ]));
  return (
    <section className="strategy-brief-view" aria-label="策略简报">
      <header className="strategy-brief-header">
        <p>{brief.market.underlying}</p>
        <h2>{suppressed ? "策略简报已暂停" : visibleAction === "NO_TRADE" ? "暂无可复核策略" : brief.market.summary_zh}</h2>
        <p role="status">{suppressed ? "当前资格已暂停 · 请更新数据后重新评估" : actionLabel(visibleAction)}</p>
        <dl className="strategy-brief-meta">
          <div>
            <dt>{suppressed ? "快照计算于" : "更新于"}</dt>
            <dd>{formatTimestamp(brief.market.as_of)}</dd>
          </div>
          <div>
            <dt>{suppressed ? "原有效至" : "有效至"}</dt>
            <dd>{formatTimestamp(brief.market.expires_at)}</dd>
          </div>
          <div>
            <dt>来源</dt>
            <dd>{effectiveSurface?.source_label ?? "未提供"}</dd>
          </div>
        </dl>
        <p className="strategy-brief-boundary">
          仅供入场前研究 · 复制复核记录不产生订单
        </p>
        {suppressed ? <p className="strategy-brief-counts">
          当前展示 0 张卡；当前资格已暂停，须取得有效证据后重新评估。
        </p> : <p className="strategy-brief-counts">
          候选 {brief.evidence_summary.candidate_count} 个，硬门禁通过{" "}
          {brief.evidence_summary.hard_gate_pass_count} 个，当前展示{" "}
          {projection.strategies.length} 张卡。
        </p>}
      </header>

      {projection.strategies.length > 0 ? (
        <section className="strategy-brief-grid" aria-label="策略卡">
          {projection.strategies.map((strategy) => (
            <StrategyCard key={strategy.recommendation_id} strategy={strategy} brief={brief} surface={effectiveSurface} />
          ))}
        </section>
      ) : (
        <section className="strategy-brief-no-trade" aria-label="NO_TRADE" role="status">
          {projection.no_trade.summary_zh && !noTradeReasons.some((reason) =>
            reason.replace(/[。.!\s]/g, "") === projection.no_trade.summary_zh?.replace(/[。.!\s]/g, ""),
          ) ? <p>{projection.no_trade.summary_zh}</p> : null}
          {noTradeReasons.length > 0 ? (
            <ol>
              {noTradeReasons.slice(0, 2).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ol>
          ) : null}
          {noTradeReasons.length > 2 ? (
            <details className="strategy-brief-rejection-details">
              <summary>全部拒绝原因（{noTradeReasons.length}）</summary>
              <ol>
                {noTradeReasons.map((reason) => <li key={reason}>{reason}</li>)}
              </ol>
            </details>
          ) : null}
          {!suppressed && projection.no_trade.next_update_at ? (
            <p>建议复核时刻：{formatTimestamp(projection.no_trade.next_update_at)} · 需手动更新数据</p>
          ) : null}
          <CopyResearchReviewButton
            text={buildRejectionReviewCopy(brief, projection, noTradeReasons, effectiveSurface)}
            label="复制拒绝原因"
            copiedLabel="已复制拒绝原因"
            copiedMessage="已复制研究阻断和证据标识；须取得有效数据后重新评估。"
          />
        </section>
      )}

    </section>
  );
}
