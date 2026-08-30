import { useState } from "react";

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
    return "Bull Put Credit Spread";
  }
  if (value === "BEAR_CALL_CREDIT_SPREAD") {
    return "Bear Call Credit Spread";
  }
  return "Iron Condor";
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
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="strategy-brief-copy"
      onClick={() => {
        void navigator.clipboard
          ?.writeText(strategy.copy_recipe)
          .then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => setCopied(false));
      }}
      type="button"
    >
      {copied ? "已复制组合" : "复制组合"}
    </button>
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
          <dt>最大亏损</dt>
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
          <dd>short bid / long ask · 已含费用与滑点</dd>
        </div>
      </dl>
      <p>{historyLabel(strategy.history)}</p>
      <p>{forecastLabel(strategy.forecast)}</p>
      {strategy.kill_conditions.length > 0 ? (
        <ul aria-label="取消条件">
          {strategy.kill_conditions.map((condition) => (
            <li key={condition}>CANCEL IF: {condition}</li>
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
  const noTradeReasons = projection.no_trade.reasons_zh ?? [];
  return (
    <section className="strategy-brief-view" aria-label="策略简报">
      <header className="strategy-brief-header">
        <p>{brief.market.underlying}</p>
        <h2>{brief.market.summary_zh}</h2>
        <p role="status">{actionLabel(visibleAction)}</p>
        <dl className="strategy-brief-meta">
          <div>
            <dt>更新于</dt>
            <dd>{formatTimestamp(brief.market.as_of)}</dd>
          </div>
          <div>
            <dt>有效至</dt>
            <dd>{formatTimestamp(brief.market.expires_at)}</dd>
          </div>
          <div>
            <dt>来源</dt>
            <dd>{effectiveSurface?.source_label ?? "未提供"}</dd>
          </div>
        </dl>
        <p className="strategy-brief-boundary">
          RESEARCH_ONLY · execution_allowed=false · 只复制组合，不会提交订单
        </p>
        <p className="strategy-brief-counts">
          候选 {brief.evidence_summary.candidate_count} 个，硬门禁通过{" "}
          {brief.evidence_summary.hard_gate_pass_count} 个，当前展示{" "}
          {brief.evidence_summary.selected_count} 张卡。
        </p>
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
          {projection.no_trade.next_update_at ? (
            <p>下次更新时间：{formatTimestamp(projection.no_trade.next_update_at)}</p>
          ) : null}
        </section>
      )}

      {projection.suppression.suppress_cards ? (
        <p className="strategy-brief-suppression">
          {projection.suppression.reasons_zh.join(" ")}
        </p>
      ) : null}
    </section>
  );
}
