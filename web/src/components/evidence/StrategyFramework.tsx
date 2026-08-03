import type { ResearchReport } from "../../contracts";
import {
  displayStatus,
  finiteNumber,
  formatCutoffTime,
  formatPublishedAge,
  friendlySource,
  humanize,
  marketDisplayState,
} from "./reportModel";
import type { Freshness } from "./reportModel";
import {
  formatDecimal,
  formatExpiry,
  formatPercent,
  formatUsd,
} from "./marketModel";

const STRATEGY_STAGE_LABELS: Record<string, string> = {
  ANALYZE: "分析",
  COLLECT: "采集",
  ENTER: "进场",
  EXIT: "退出",
  MONITOR: "监控",
  REVIEW: "复盘",
  RISK: "风控",
  SELECT: "结构",
};

const CONDITION_LABELS: Record<string, string> = {
  account_gate: "账户风控",
  calibrated_path_risk: "路径风险 / 校准",
  candidate_eligibility: "候选资格",
  cost_coverage: "成本覆盖",
  delta_band: "Delta 区间",
  event_gate: "事件风险",
  leg_liquidity: "双腿流动性",
  market_freshness: "数据新鲜度",
  market_quality: "市场快照",
  no_arbitrage: "无套利检查",
  regime_permission: "Regime 权限",
  settlement_window: "结算时段",
  surface_fit: "曲面拟合",
};

const CONDITION_STATUS_LABELS: Record<string, string> = {
  block: "未通过",
  pass: "通过",
  unknown: "待验证",
};

const POSITION_RESPONSE_LABELS: Record<string, string> = {
  close: "平仓",
  close_and_pause: "平仓并暂停",
  close_unless_defined_risk_conversion_reduces_total_stress:
    "平仓；仅允许可证明降低总压力的定义风险转换",
  hold_or_take_profit: "持有或按止盈规则减仓",
  no_additions_and_review: "停止加仓并复核",
  reduce_or_add_defined_risk_protection: "减仓或增加定义风险保护",
};

const PROFIT_RESPONSE_LABELS: Record<string, string> = {
  close_50_percent: "平掉 50%",
  close_all: "全部平仓",
  close_and_rescan: "平仓并重新扫描",
  close_early: "提前平仓",
};

const MONITOR_METRIC_LABELS: Record<string, string> = {
  account_age_sec: "账户快照年龄",
  buy_leg_spread_ratio: "买入腿价差比",
  candidate_delta: "候选 Delta",
  dte_days: "剩余到期天数",
  event_score: "事件风险分",
  market_age_sec: "市场数据年龄",
  no_arbitrage_pass: "无套利状态",
  position_loss_multiple: "持仓亏损倍数",
  sell_leg_spread_ratio: "卖出腿价差比",
  spread_permission: "Regime 价差权限",
  surface_fit_quality: "曲面拟合质量",
};

const MONITOR_RESPONSE_LABELS: Record<string, string> = {
  keep_monitor_only: "保持仅观察",
  kill_new_entry: "禁止新进场",
  move_to_caution: "转入 CAUTION",
  move_to_defense: "转入 DEFENSE",
  no_contract_sizing: "停止仓位计算",
  pause_research_setup: "暂停研究方案",
  remove_candidate: "移出候选",
  time_management_review: "启动时间管理复核",
};

const PROMOTION_LABELS: Record<string, string> = {
  "Attach a fresh read-only account snapshot before any sizing study.":
    "接入新鲜的只读账户快照后，才允许研究仓位上限。",
  "Persist enough rolling observations to promote regime evidence.":
    "积累足够的滚动样本，提升 Regime 证据等级。",
  "Promote walk-forward calibration and validated path-risk outputs.":
    "完成 Walk-forward 校准，并提升已验证的路径风险输出。",
  "Reconcile paper observations, fees, slippage, and forced-exit behavior.":
    "核对 Paper 观察、费用、滑点与强制退出行为。",
  "Run an aligned bounded backtest on licensed historical data.":
    "在获授权历史数据上运行口径对齐的有限边界 Backtest。",
};

function strategyStanceLabel(value: string | undefined): string {
  if (value === "CONDITIONAL_RESEARCH") {
    return "条件式研究";
  }
  if (value === "MONITOR_ONLY") {
    return "仅观察";
  }
  return "无可验证方案";
}

function formatSignedPoints(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return `${value > 0 ? "+" : ""}${value.toFixed(2)} pt`;
}

function formatConditionObserved(id: string, value: unknown): string {
  if (value === null || value === undefined) {
    return "未提供";
  }
  if (id === "market_freshness" && typeof value === "number") {
    return `${value.toFixed(0)} 秒`;
  }
  if (id === "surface_fit" && typeof value === "number") {
    return value.toFixed(3);
  }
  if (id === "delta_band" && typeof value === "number") {
    return value.toFixed(3);
  }
  if (id === "event_gate" && typeof value === "number") {
    return value.toFixed(2);
  }
  if (id === "leg_liquidity" && typeof value === "object") {
    const ratios = value as { buy?: number | null; sell?: number | null };
    return `卖 ${formatPercent(ratios.sell ?? null, 1)} · 买 ${formatPercent(
      ratios.buy ?? null,
      1,
    )}`;
  }
  if (id === "regime_permission" && typeof value === "object") {
    const permission = value as {
      spread_permission?: boolean;
      status?: string;
    };
    return `${displayStatus(permission.status)} · ${
      permission.spread_permission ? "允许" : "未允许"
    }`;
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (typeof value === "number") {
    return value.toLocaleString("zh-CN");
  }
  if (typeof value === "string") {
    const labels: Record<string, string> = {
      eligible: "通过筛选",
      outside: "窗口外",
      unavailable: "不可用",
      validated: "已验证",
    };
    return labels[value] ?? humanize(value);
  }
  return "见原始数据";
}

function formatPublishedLimitHours(maxAgeSec: number | null | undefined): string {
  if (typeof maxAgeSec !== "number" || !Number.isFinite(maxAgeSec) || maxAgeSec <= 0) {
    return "未提供时效上限";
  }
  return `${(maxAgeSec / 3_600).toLocaleString("zh-CN", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })} 小时`;
}

export function StrategyFrameworkSection({
  report,
  freshness,
}: {
  report: ResearchReport;
  freshness?: Freshness;
}): React.JSX.Element {
  const strategy = report.strategy_research;
  const displayState = freshness ? marketDisplayState(report, freshness) : "available";
  const isPublished = report.runtime_context?.mode === "published";
  const collection = strategy?.collection;
  const market = strategy?.analysis?.market;
  const volatility = strategy?.analysis?.volatility;
  const playbook = strategy?.playbook;
  const candidate = playbook?.candidate;
  const economics = playbook?.economics;
  const conditions = (playbook?.entry_contract?.conditions ?? []).filter(
    (condition) => !isPublished || condition.id !== "account_gate",
  );
  const riskBudget = playbook?.risk_budget;
  const exitContract = playbook?.exit_contract;
  const coverage = collection?.coverage;
  const quality = collection?.quality;
  const monitoring = (strategy?.monitoring ?? []).filter(
    (watch) => !isPublished || watch.metric !== "account_age_sec",
  );
  const promotionConditions = (strategy?.review?.promotion_conditions ?? []).filter(
    (condition) =>
      !isPublished ||
      condition !==
        "Attach a fresh read-only account snapshot before any sizing study.",
  );
  const pipeline =
    strategy?.pipeline ??
    Object.keys(STRATEGY_STAGE_LABELS).map((stage) => ({
      stage,
      status: "blocked" as const,
    }));
  const publishedFreshnessObserved =
    isPublished && freshness
      ? `采集 ${formatCutoffTime(
          report.publish_edition?.captured_at ?? report.generated_at ?? null,
        )} · 发布 ${formatCutoffTime(report.publish_edition?.published_at ?? null)} · 评估 ${formatCutoffTime(
          report.runtime_context?.evaluation_clock ??
            report.publish_edition?.captured_at ??
            report.generated_at ??
            null,
        )}`
      : null;
  const publishedFreshnessRequirement =
    isPublished && freshness
      ? `${formatPublishedAge(freshness.ageSec)} · 公开版在 ${formatPublishedLimitHours(
          freshness.maxAgeSec,
        )} 后失效`
      : null;

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
            <h2>今日策略结论</h2>
            <span
              className="stance-badge"
              data-tone={
                strategy?.decision?.stance === "CONDITIONAL_RESEARCH"
                  ? "safe"
                  : "warning"
              }
            >
              {strategyStanceLabel(strategy?.decision?.stance)}
            </span>
          </div>
          <strong className="primary-structure">
            {strategy?.decision?.primary_structure === "CALL_CREDIT_SPREAD"
              ? "CALL 信用价差"
              : "当前无主策略"}
          </strong>
          <p>
            {playbook
              ? isPublished
                ? "当前优先研究定义风险结构。市场与曲面已形成候选，但 Regime、路径风险和成本覆盖尚未同时通过，因此不进场。"
                : "当前优先研究定义风险结构。市场与曲面已形成候选，但 Regime、账户、路径风险和成本覆盖尚未同时通过，因此不进场。"
              : "当前没有足够的可验证市场证据，系统不会构造策略或估算缺失值。"}
          </p>
        </div>
        <div className="strategy-verdict-aside">
          <span>研究置信上限</span>
          <strong>
            {strategy?.confidence_ceiling === "screening_only"
              ? "筛选级"
              : "证据不足"}
          </strong>
          <p>只读 · 不生成仓位 · 不生成订单</p>
        </div>
      </header>

      <ol className="strategy-pipeline" aria-label="策略研究八阶段">
        {pipeline.map((stage, index) => (
          <li data-status={stage.status} key={stage.stage}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{STRATEGY_STAGE_LABELS[stage.stage] ?? stage.stage}</strong>
            <small>
              {stage.status === "ready"
                ? "已形成"
                : stage.status === "partial"
                  ? "部分"
                  : "未通过"}
            </small>
          </li>
        ))}
      </ol>

      {displayState === "stale" ? (
        <div className="strategy-empty published-stop-state" role="status">
          <strong>发布已停摆</strong>
          <p>
            当前公开版已超过时效上限；策略样本、经济值与候选比较全部暂停展示，直到下一版发布。
          </p>
        </div>
      ) : playbook ? (
        <>
          <div className="strategy-analysis-grid">
            <article className="strategy-panel">
              <header>
                <span>01 · 采集</span>
                <strong>{friendlySource(collection?.source)}</strong>
              </header>
              <dl className="strategy-metric-grid">
                <div>
                  <dt>样本 / 全市场</dt>
                  <dd>
                    {coverage?.selected_instrument_count ?? "—"} /{" "}
                    {coverage?.upstream_instrument_count ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>覆盖口径</dt>
                  <dd>
                    {formatPercent(coverage?.coverage_ratio ?? null, 2)} 研究样本
                  </dd>
                </div>
                <div>
                  <dt>有效报价</dt>
                  <dd>
                    {quality?.valid_quotes ?? "—"} /{" "}
                    {quality?.total_quotes ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>公共采集图</dt>
                  <dd>{collection?.feed_graph?.complete ? "完整" : "不完整"}</dd>
                </div>
              </dl>
              <p className="strategy-note">
                这是分层研究样本，不是完整期权链；页面保留真实覆盖率，不把 20
                条样本包装成全市场。
              </p>
            </article>

            <article className="strategy-panel">
              <header>
                <span>02 · 市场与波动率分析</span>
                <strong>{market?.regime_label ?? "Unavailable"}</strong>
              </header>
              <dl className="strategy-metric-grid analysis-metrics">
                <div>
                  <dt>现货</dt>
                  <dd>{formatUsd(finiteNumber(market?.spot_usd))}</dd>
                </div>
                <div>
                  <dt>DVOL / ATM IV</dt>
                  <dd>
                    {formatPercent(
                      finiteNumber(market?.dvol_percent),
                      2,
                    )}{" "}
                    /{" "}
                    {formatPercent(
                      finiteNumber(market?.near_term_atm_iv_percent),
                      2,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>DVOL − ATM</dt>
                  <dd>
                    {formatSignedPoints(
                      finiteNumber(market?.dvol_minus_atm_iv_points),
                    )}
                  </dd>
                </div>
                <div>
                  <dt>预期波动</dt>
                  <dd>
                    {formatUsd(finiteNumber(volatility?.expected_move_usd))}
                  </dd>
                </div>
                <div>
                  <dt>期限斜率</dt>
                  <dd>
                    {formatSignedPoints(
                      finiteNumber(volatility?.term_slope_iv_points),
                    )}
                  </dd>
                </div>
                <div>
                  <dt>CALL 翼溢价</dt>
                  <dd>
                    {formatSignedPoints(
                      finiteNumber(
                        volatility?.call_wing_richness_iv_points,
                      ),
                    )}
                  </dd>
                </div>
              </dl>
              <p className="strategy-note">
                Regime 仍在收集，不能把当前快照命名为趋势或震荡；期限与偏度只作结构筛选。
              </p>
            </article>
          </div>

          <article className="strategy-plan">
            <header className="strategy-plan-heading">
              <div>
                <span>03 · 主策略研究样本</span>
                <h3>卖近腿 CALL，买远腿 CALL，限定尾部风险</h3>
              </div>
              <strong>{formatExpiry(candidate?.expiry_date ?? null)}</strong>
            </header>
            <div className="strategy-legs">
              <div data-leg="sell">
                <span>卖出腿 · 研究假设</span>
                <strong>{candidate?.sell_leg ?? "—"}</strong>
                <small>
                  Strike {formatUsd(finiteNumber(candidate?.sell_strike_usd))}
                </small>
              </div>
              <span className="leg-connector" aria-hidden="true">
                →
              </span>
              <div data-leg="buy">
                <span>买入保护腿</span>
                <strong>{candidate?.buy_leg ?? "—"}</strong>
                <small>
                  Strike {formatUsd(finiteNumber(candidate?.buy_strike_usd))}
                </small>
              </div>
            </div>
            <dl className="strategy-economics">
              <div>
                <dt>净信用估值</dt>
                <dd>{formatUsd(finiteNumber(economics?.credit_usd_shadow))}</dd>
                <small>
                  {formatDecimal(finiteNumber(economics?.credit_coin), 4)} BTC
                </small>
              </div>
              <div>
                <dt>单份参考最大损失</dt>
                <dd>
                  {formatUsd(
                    finiteNumber(economics?.reference_max_loss_usd_shadow),
                  )}
                </dd>
                <small>含保守费用影子，不含滑点</small>
              </div>
              <div>
                <dt>参考盈亏平衡</dt>
                <dd>
                  {formatUsd(
                    finiteNumber(economics?.breakeven_usd_shadow),
                  )}
                </dd>
                <small>执行价 + 入场信用的 USD 影子</small>
              </div>
              <div>
                <dt>卖出腿距离</dt>
                <dd>
                  {formatPercent(
                    finiteNumber(economics?.sell_strike_distance_percent),
                    2,
                  )}
                </dd>
                <small>
                  {formatDecimal(
                    finiteNumber(
                      economics?.sell_strike_expected_move_multiple,
                    ),
                    2,
                  )}
                  × 预期波动
                </small>
              </div>
              <div>
                <dt>组合 Delta</dt>
                <dd>{formatDecimal(finiteNumber(candidate?.model_delta), 3)}</dd>
                <small>
                  RN P(ITM){" "}
                  {formatPercent(
                    finiteNumber(candidate?.risk_neutral_p_itm),
                    1,
                  )}
                </small>
              </div>
            </dl>
          </article>

          <section className="entry-contract" aria-label="条件式进场规则">
            <header className="workflow-subheading">
              <div>
                <span>04 · 进场</span>
                <h3>条件式进场规则</h3>
              </div>
              <strong data-status={playbook.entry_contract?.status}>
                {playbook.entry_contract?.status === "ready"
                  ? "条件满足"
                  : "当前不进场"}
              </strong>
            </header>
            <div className="condition-grid">
              {conditions.map((condition) => (
                <article data-status={condition.status} key={condition.id}>
                  <div>
                    <span>
                      {isPublished && condition.id === "market_freshness"
                        ? "发布计算时数据新鲜度"
                        : (CONDITION_LABELS[condition.id] ?? condition.id)}
                    </span>
                    <strong>
                      {CONDITION_STATUS_LABELS[condition.status] ??
                        condition.status}
                    </strong>
                  </div>
                  <p>
                    {isPublished && condition.id === "market_freshness"
                      ? publishedFreshnessObserved
                      : `${isPublished ? "当次评估" : "当前"}：${formatConditionObserved(
                          condition.id,
                          condition.observed,
                        )}`}
                  </p>
                  <small>
                    {isPublished && condition.id === "market_freshness"
                      ? publishedFreshnessRequirement
                      : `要求：${condition.requirement ?? "见策略合同"}`}
                  </small>
                </article>
              ))}
            </div>
            <p className="strategy-note entry-note">
              定价口径：卖出腿 bid − 买入腿 ask；每次刷新必须重新满足全部硬条件。
            </p>
          </section>

          <section className="risk-exit-contract" aria-label="风险与退出规则">
            <header className="workflow-subheading">
              <div>
                <span>05–06 · 风控与退出</span>
                <h3>风险与退出规则</h3>
              </div>
              <strong>模板级 · 尚未校准</strong>
            </header>
            {isPublished ? (
              <p className="strategy-note">
                公开版不展示账户、保证金、仓位上限或模拟执行细节；这一幕只保留研究边界与证据链。
              </p>
            ) : (
              <>
                <div className="risk-budget-strip">
                  <div>
                    <span>单一价差损失预算</span>
                    <strong>
                      {formatPercent(
                        finiteNumber(riskBudget?.max_single_spread_loss_nav),
                        2,
                      )}{" "}
                      NAV
                    </strong>
                  </div>
                  <div>
                    <span>新增保证金上限</span>
                    <strong>
                      {formatPercent(
                        finiteNumber(riskBudget?.max_new_margin_nav),
                        1,
                      )}{" "}
                      NAV
                    </strong>
                  </div>
                  <div>
                    <span>市场深度占比</span>
                    <strong>
                      {formatPercent(
                        finiteNumber(riskBudget?.max_depth_fraction),
                        1,
                      )}
                    </strong>
                  </div>
                  <div>
                    <span>实际张数</span>
                    <strong>不生成</strong>
                    <small>缺账户快照；研究模式也禁止输出仓位</small>
                  </div>
                </div>
                <div className="exit-policy-grid">
                  <div>
                    <h4>止盈与时间管理</h4>
                    <ol className="profit-policy">
                      {(exitContract?.profit_capture ?? []).map((rule) => (
                        <li key={rule.trigger}>
                          <strong>
                            {(rule.trigger ?? "")
                              .replace("premium_capture >= ", "")
                              .replace(
                                "remaining_premium < 3_to_5x_expected_close_cost",
                                "剩余权利金 < 3–5× 平仓成本",
                              )
                              .replace(
                                "short_call_delta < 0.03",
                                "卖出腿 Delta < 0.03",
                              )}
                          </strong>
                          <span>
                            {PROFIT_RESPONSE_LABELS[rule.response ?? ""] ??
                              humanize(rule.response)}
                          </span>
                        </li>
                      ))}
                    </ol>
                    <p>
                      DTE ≤ {exitContract?.time_management?.review_below_dte_days ?? 7}{" "}
                      天必须复核；只在 NORMAL / CAUTION 状态允许主动滚动，且必须同时改善
                      EV、P_Touch 与总压力损失。
                    </p>
                  </div>
                  <div>
                    <h4>仓位状态阶梯</h4>
                    <ol className="position-ladder">
                      {(exitContract?.position_states ?? []).map((state) => (
                        <li key={state.state} data-state={state.state}>
                          <strong>{state.state}</strong>
                          <div>
                            <span>{state.delta_condition}</span>
                            <span>{state.loss_condition}</span>
                          </div>
                          <small>
                            {POSITION_RESPONSE_LABELS[state.response ?? ""] ??
                              humanize(state.response)}
                          </small>
                        </li>
                      ))}
                    </ol>
                  </div>
                </div>
              </>
            )}
          </section>

          <section className="monitor-review" aria-label="监控与复盘规则">
            <div>
              <header className="workflow-subheading compact">
                <div>
                  <span>07 · 监控</span>
                  <h3>每次刷新检查</h3>
                </div>
              </header>
              <ul className="monitor-list">
                {monitoring.slice(0, 8).map((watch) => (
                  <li key={watch.metric}>
                    <span>
                      {MONITOR_METRIC_LABELS[watch.metric ?? ""] ??
                        humanize(watch.metric)}
                    </span>
                    <strong>{watch.trigger ?? "—"}</strong>
                    <small>
                      {MONITOR_RESPONSE_LABELS[watch.response ?? ""] ??
                        humanize(watch.response)}
                    </small>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <header className="workflow-subheading compact">
                <div>
                  <span>08 · 复盘</span>
                  <h3>升级所需证据</h3>
                </div>
              </header>
              <ol className="review-list">
                {promotionConditions.map(
                  (condition, index) => (
                    <li key={condition}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <p>{PROMOTION_LABELS[condition] ?? condition}</p>
                    </li>
                  ),
                )}
              </ol>
            </div>
          </section>
        </>
      ) : (
        <div className="strategy-empty" role="status">
          <strong>完整工作流已建立，但当前没有可验证的策略样本</strong>
          <p>
            采集、分析、结构、进场、风控、退出、监控与复盘八阶段均保留；只有真实证据到位后才填充。
          </p>
        </div>
      )}
    </section>
  );
}
