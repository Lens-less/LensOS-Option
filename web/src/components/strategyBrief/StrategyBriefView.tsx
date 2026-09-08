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
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(parsed);
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
    return "今日行动：有可靠的有限风险策略";
  }
  if (value === "WATCH") {
    return "今日行动：仅观察，不升级为推荐";
  }
  return "今日行动：今日暂无可靠策略";
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

function CopyCombinationButton({
  strategy,
}: {
  strategy: StrategyBriefStrategy;
}): React.JSX.Element {
  const [status, setStatus] = useState<"idle" | "copying" | "copied" | "failed">("idle");
  const statusId = useId();
  const recipeId = useId();
  const request = useRef(0);
  useEffect(() => {
    setStatus("idle");
    return () => { request.current += 1; };
  }, [strategy.copy_recipe]);
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
            await navigator.clipboard.writeText(strategy.copy_recipe);
            if (request.current === sequence) setStatus("copied");
          } catch {
            if (request.current === sequence) setStatus("failed");
          }
        })();
      }}
      type="button"
    >
      {status === "copied" ? "已复制组合" : status === "copying" ? "复制中…" : "复制组合"}
    </button>
    <p id={statusId} role="status" className="strategy-brief-copy-status">
      {status === "copied" ? "已复制研究组合，请人工复核全部条件。"
        : status === "failed" ? "无法访问剪贴板，请选择下方组合文本手动复制。" : ""}
    </p>
    {status === "failed" ? (
      <div className="strategy-brief-copy-fallback">
        <label htmlFor={recipeId}>研究组合文本</label>
        <textarea id={recipeId} readOnly value={strategy.copy_recipe} rows={8}
          onFocus={(event) => event.currentTarget.select()} />
      </div>
    ) : null}
    </div>
  );
}

function StrategyCard({
  strategy,
}: {
  strategy: StrategyBriefStrategy;
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
          <li key={`${leg.side}-${leg.instrument_name}`}>
            <strong>
              {leg.side} {leg.quantity}
            </strong>{" "}
            {leg.instrument_name}
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
      <CopyCombinationButton strategy={strategy} />
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
        <h2>{suppressed ? "策略简报已暂停" : brief.market.summary_zh}</h2>
        <p role="status">{actionLabel(visibleAction)}</p>
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
          RESEARCH_ONLY · execution_allowed=false · 复制研究组合供人工复核，不会提交订单
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
            <StrategyCard key={strategy.recommendation_id} strategy={strategy} />
          ))}
        </section>
      ) : (
        <section className="strategy-brief-no-trade" aria-label="NO_TRADE" role="status">
          <strong>{projection.no_trade.headline_zh ?? "今日暂无可靠策略"}</strong>
          {projection.no_trade.summary_zh ? <p>{projection.no_trade.summary_zh}</p> : null}
          {noTradeReasons.length > 0 ? (
            <ol>
              {noTradeReasons.slice(0, 2).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ol>
          ) : null}
          {!suppressed && projection.no_trade.next_update_at ? (
            <p>下次更新时间：{formatTimestamp(projection.no_trade.next_update_at)}</p>
          ) : null}
        </section>
      )}

    </section>
  );
}
