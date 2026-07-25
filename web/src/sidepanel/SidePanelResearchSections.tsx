import React from "react";
import type {
  SidePanelEntryConditionViewModel,
  SidePanelViewModel,
} from "../report";
import {
  formatNavLimit,
  formatUsdShadow,
  labelForStance,
  labelForStructure,
  listOrFallback,
  sectionToneClass,
} from "./sidepanelFormatters";

function toneForEntryCondition(
  status: SidePanelEntryConditionViewModel["status"],
): "neutral" | "safe" | "warning" {
  if (status === "pass") {
    return "safe";
  }
  if (status === "block") {
    return "warning";
  }
  return "neutral";
}

function optionalItems(
  items: Array<React.JSX.Element | null>,
): React.JSX.Element[] {
  return items.filter((item): item is React.JSX.Element => item !== null);
}

export function SidePanelResearchSections({
  model,
}: {
  model: SidePanelViewModel | null;
}): React.JSX.Element | null {
  if (!model) {
    return null;
  }

  return (
    <>
      <section className="panel-card">
        <header className="panel-card-header">
          <div>
            <p className="panel-section-kicker">Strategy stance</p>
            <h2>{labelForStance(model.stance)}</h2>
          </div>
          <span className="panel-badge">
            {labelForStructure(model.primaryStructure)}
          </span>
        </header>
        <p className="panel-summary">
          {model.summary ?? "当前没有可验证的研究摘要。"}
        </p>
        <div className="panel-bullets">
          <div>
            <h3>为什么现在关注</h3>
            <ul>
              {listOrFallback(
                model.whyNow.map((item) => <li key={item}>{item}</li>),
                "没有记录支持当前结构的积极证据。",
              )}
            </ul>
          </div>
          <div>
            <h3>为什么暂不进入</h3>
            <ul>
              {listOrFallback(
                model.whyNot.map((item) => <li key={item}>{item}</li>),
                "没有记录阻断原因。",
              )}
            </ul>
          </div>
        </div>
      </section>

      <section className="panel-card">
        <header className="panel-card-header">
          <div>
            <p className="panel-section-kicker">Structure</p>
            <h2>完整两腿</h2>
          </div>
        </header>
        <div className="panel-legs">
          <article>
            <span className="panel-leg-label">卖腿</span>
            <strong>{model.sellLeg ?? "缺少卖腿"}</strong>
          </article>
          <article>
            <span className="panel-leg-label">保护腿</span>
            <strong>{model.buyLeg ?? "缺少保护腿"}</strong>
          </article>
        </div>
        <p className="panel-meta">
          到期 {model.expiryDate ?? "未知"} · DTE {model.dteDays ?? "?"}
        </p>
      </section>

      <section className="panel-card">
        <header className="panel-card-header">
          <div>
            <p className="panel-section-kicker">Entry</p>
            <h2>{model.entryStatus ?? "没有进场条件"}</h2>
          </div>
        </header>
        <ul className="panel-list">
          {listOrFallback(
            model.entryConditions.map((item) => (
              <li
                className={sectionToneClass(toneForEntryCondition(item.status))}
                key={item.id}
              >
                <strong>{item.label}</strong>
                <span>{item.requirement ?? "未记录硬条件"}</span>
              </li>
            )),
            "未记录进场硬条件。",
          )}
        </ul>
      </section>

      <section className="panel-card">
        <header className="panel-card-header">
          <div>
            <p className="panel-section-kicker">Risk / exit</p>
            <h2>{model.exitPolicyStatus ?? "仅研究模板"}</h2>
          </div>
        </header>
        <div className="panel-bullets panel-bullets-single">
          <div>
            <h3>风险预算（非 sizing）</h3>
            <ul>
              {listOrFallback(
                optionalItems([
                  <li key="reference-max-loss">
                    <strong>参考最大损失</strong>
                    <span>{formatUsdShadow(model.referenceMaxLossUsdShadow)}</span>
                  </li>,
                  <li key="reference-credit">
                    <strong>参考净权利金</strong>
                    <span>{formatUsdShadow(model.referenceCreditUsdShadow)}</span>
                  </li>,
                  <li key="nav-limit">
                    <strong>单笔价差风险上限</strong>
                    <span>{formatNavLimit(model.maxSingleSpreadLossNav)}</span>
                  </li>,
                  <li key="sizing-status">
                    <strong>Sizing 状态</strong>
                    <span>
                      {model.riskSizingStatus ??
                        "未提供；研究模式不生成合约张数"}
                    </span>
                  </li>,
                  model.riskNote ? (
                    <li key="risk-note">
                      <strong>研究边界</strong>
                      <span>{model.riskNote}</span>
                    </li>
                  ) : null,
                ]),
                "研究模式不生成合约张数。",
              )}
            </ul>
          </div>
          <div>
            <h3>止盈与强制退出</h3>
            <ul>
              {listOrFallback(
                [
                  ...model.exitProfitCapture.map((rule, index) => (
                    <li key={`profit-${index}`}>
                      <strong>{rule.trigger ?? "止盈条件"}</strong>
                      <span>{rule.response ?? "未记录响应"}</span>
                    </li>
                  )),
                  ...model.exitKillSwitches.map((item) => (
                    <li className="is-warning" key={item}>
                      <strong>Kill switch</strong>
                      <span>{item}</span>
                    </li>
                  )),
                ],
                "未记录退出规则。",
              )}
            </ul>
          </div>
          <div>
            <h3>时间退出</h3>
            <ul>
              {listOrFallback(
                optionalItems([
                  model.exitTimeManagement.reviewBelowDteDays !== null ? (
                    <li key="review-dte">
                      <strong>低于此 DTE 复核</strong>
                      <span>{model.exitTimeManagement.reviewBelowDteDays} 天</span>
                    </li>
                  ) : null,
                  model.exitTimeManagement.rollAllowedStates.length > 0 ? (
                    <li key="roll-states">
                      <strong>允许评估滚仓的状态</strong>
                      <span>
                        {model.exitTimeManagement.rollAllowedStates.join(" · ")}
                      </span>
                    </li>
                  ) : null,
                  model.exitTimeManagement.rollMustImprove.length > 0 ? (
                    <li key="roll-improve">
                      <strong>滚仓必须改善</strong>
                      <span>{model.exitTimeManagement.rollMustImprove.join(" · ")}</span>
                    </li>
                  ) : null,
                  model.exitTimeManagement.lossDeferralAloneIsForbidden === true ? (
                    <li className="is-warning" key="loss-deferral">
                      <strong>禁止仅延后亏损</strong>
                      <span>滚仓不能只把亏损推迟到更远到期日。</span>
                    </li>
                  ) : null,
                ]),
                "未记录时间退出规则。",
              )}
            </ul>
          </div>
          <div>
            <h3>仓位状态响应</h3>
            <ul>
              {listOrFallback(
                model.exitPositionStates.map((state, index) => (
                  <li key={`${state.state ?? "state"}-${index}`}>
                    <strong>{state.state ?? "未命名状态"}</strong>
                    <span>
                      {[state.deltaCondition, state.lossCondition, state.response]
                        .filter(Boolean)
                        .join(" · ") || "未记录响应"}
                    </span>
                  </li>
                )),
                "未记录仓位状态响应。",
              )}
            </ul>
          </div>
        </div>
      </section>

      <section className="panel-card">
        <header className="panel-card-header">
          <div>
            <p className="panel-section-kicker">Monitor / review</p>
            <h2>持仓监控与复盘缺口</h2>
          </div>
        </header>
        <div className="panel-bullets">
          <div>
            <h3>监控</h3>
            <ul>
              {listOrFallback(
                model.monitoring.map((item, index) => (
                  <li key={`${item.metric ?? "monitor"}-${index}`}>
                    <strong>{item.metric ?? "监控指标"}</strong>
                    <span>
                      {[item.trigger, item.response, item.cadence]
                        .filter(Boolean)
                        .join(" · ") || "未记录响应"}
                    </span>
                  </li>
                )),
                "未记录监控规则。",
              )}
            </ul>
          </div>
          <div>
            <h3>复盘与证据缺口</h3>
            <ul>
              {listOrFallback(
                [
                  ...model.review.missingEvidence.map((item) => (
                    <li className="is-warning" key={item}>
                      <strong>缺失证据</strong>
                      <span>{item}</span>
                    </li>
                  )),
                  ...model.review.promotionConditions.map((item) => (
                    <li key={item}>{item}</li>
                  )),
                ],
                "未记录复盘动作。",
              )}
            </ul>
          </div>
        </div>
      </section>
    </>
  );
}
