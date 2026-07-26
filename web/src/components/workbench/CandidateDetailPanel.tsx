import type { EdgeComponentStatus, ResearchReport } from "../../contracts";
import { finiteNumber } from "../../report";
import {
  AXIS_LABELS,
  dominanceExplanationFor,
  evCandidateScannerOf,
} from "./candidateModel";
import type { CandidateViewRow } from "./candidateModel";
import { money, signedMoney } from "../candidate/format";
import { DivergingBars } from "../viz/DivergingBars";
import { PayoffChart } from "../viz/PayoffChart";
import { breakevens, lossIsBounded, parseLegs, payoffPoints } from "../viz/payoff";
import { PayoffCurve } from "./PayoffCurve";
import { RankExplanation } from "./RankExplanation";

const KILL_CONDITION_LABELS: Record<string, string> = {
  UNCALIBRATED_SCORE_MODEL: "评分模型尚未校准",
  NO_VALIDATED_PATH_RISK: "缺少已验证路径风险",
  UNBOUNDED_LOSS_STRUCTURE: "结构本身亏损无上限",
  SUSPECT_PRICE_DIVERGENCE: "报价存在可疑偏离",
};

const EDGE_STATUS_LABELS: Record<EdgeComponentStatus, string> = {
  OK: "正常",
  CAUTION: "需留意",
  UNKNOWN: "未知",
  BLOCKED: "已阻断",
};

const EDGE_STATUS_TONE: Record<EdgeComponentStatus, string> = {
  OK: "safe",
  CAUTION: "warning",
  UNKNOWN: "muted",
  BLOCKED: "danger",
};

function humanizeReasonCode(code: string): string {
  return code.replaceAll("_", " ");
}

function formatUsdcSigned(value: number | null): string {
  if (value === null) {
    return "—";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}$${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

function formatUsdc(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return `$${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

function formatCount(value: number | null): string {
  return value === null ? "—" : value.toLocaleString("zh-CN");
}

export function CandidateDetailPanel({
  headingRef,
  onClose,
  report,
  row,
  spotUsdc,
}: {
  headingRef?: React.Ref<HTMLHeadingElement>;
  onClose: () => void;
  report: ResearchReport;
  row: CandidateViewRow;
  spotUsdc: number | null;
}): React.JSX.Element {
  const scanner = evCandidateScannerOf(report);
  const tieBreakOrder = scanner?.ranking_basis?.tie_break_order ?? [];
  const explanation = dominanceExplanationFor(report, row.id);
  const edgeComponents = row.raw.edge_components;
  const absoluteEv = row.raw.absolute_ev;
  const evAfterCost = finiteNumber(absoluteEv?.ev_after_cost_usdc) ?? row.evAfterCostUsdc;
  const entryCredit = finiteNumber(absoluteEv?.entry_credit_usdc) ?? row.executableCreditUsdc;
  const expectedPayout = finiteNumber(absoluteEv?.expected_payout_usdc);
  const feesTotal = finiteNumber(absoluteEv?.modelled_fees_usdc?.total_usdc);
  const sampleSize = finiteNumber(absoluteEv?.authoritative_sample_size);
  const pathRisk = row.raw.path_risk;
  const marginSnapshot = row.raw.margin_snapshot;
  const fairIv = row.raw.fair_iv_diagnostics;

  const legs = parseLegs(
    (row.raw as { structure_legs?: unknown }).structure_legs,
  );
  const curvePoints =
    legs.length > 0
      ? payoffPoints(legs, {
          entryCash: row.executableCreditUsdc ?? row.premiumUsdc ?? 0,
          spot: spotUsdc,
        })
      : [];

  const execution = (
    absoluteEv as { execution_sensitivity?: Record<string, unknown> } | undefined
  )?.execution_sensitivity;
  const executionValues =
    (execution?.ev_after_cost_usdc as Record<string, number> | undefined) ?? {};
  const EXECUTION_LABELS: Array<[string, string]> = [
    ["sell_at_bid", "卖出 @ 买价"],
    ["sell_at_mid", "卖出 @ 中价"],
    ["buy_at_mid", "买入 @ 中价"],
    ["buy_at_ask", "买入 @ 卖价"],
  ];
  const executionRows = EXECUTION_LABELS.filter(
    ([key]) => typeof executionValues[key] === "number",
  ).map(([key, label]) => ({
    key,
    label,
    value: executionValues[key],
  }));

  return (
    <section aria-label="候选详情" className="candidate-detail-panel">
      <header className="candidate-detail-heading">
        <div>
          <p className="section-kicker">Candidate detail / 只读</p>
          <h3 ref={headingRef} tabIndex={-1}>
            {row.id}
          </h3>
          <span className="candidate-detail-structure">
            {row.structureType} · {row.action}
          </span>
        </div>
        <button
          aria-label="关闭候选详情"
          className="candidate-detail-close"
          onClick={onClose}
          type="button"
        >
          关闭
        </button>
      </header>

      {legs.length > 0 ? (
        <div className="candidate-detail-block">
          <h4>到期盈亏</h4>
          <PayoffChart
            ariaLabel={`${row.id} 的到期盈亏曲线`}
            currentSpot={spotUsdc}
            formatMoney={(value) => money(value, { digits: 0 })}
            markers={breakevens(curvePoints).map((spot) => ({
              spot,
              label: "盈亏平衡",
            }))}
            series={[
              {
                key: row.id,
                label: row.id,
                emphasis: "subject",
                points: curvePoints,
              },
            ]}
          />
          {!lossIsBounded(legs) ? (
            <p className="candidate-detail-warning" role="note">
              该结构在上行方向没有保护，亏损无上界；曲线右端会持续下行。
            </p>
          ) : null}
        </div>
      ) : (
        <PayoffCurve
          creditUsdc={row.executableCreditUsdc ?? row.premiumUsdc}
          longStrikeUsdc={row.legs.longStrikeUsdc}
          shortStrikeUsdc={row.legs.shortStrikeUsdc}
          spotUsdc={spotUsdc}
          structureKind={row.structureKind}
        />
      )}

      {executionRows.length > 0 ? (
        <div className="candidate-detail-block">
          <h4>edge 在价差的哪一侧</h4>
          <p className="candidate-detail-note">
            预期赔付与开仓价格无关，所以这四个变体是同一次路径重放上的算术。
            两边都为负说明公允价落在买卖价之间——那是正常报价市场的样子，不是发现。
          </p>
          <DivergingBars
            ariaLabel="买卖两个方向在买价、中价、卖价上的预期价值"
            format={(value) => signedMoney(value)}
            rows={executionRows}
            unit="USDC"
          />
        </div>
      ) : null}

      <RankExplanation
        explanation={explanation}
        row={row}
        tieBreakOrder={tieBreakOrder}
      />

      <section aria-label="逐项证据分解" className="edge-component-grid">
        <h4>逐项证据分解</h4>
        {edgeComponents ? (
          <div className="edge-component-list">
            {Object.entries(edgeComponents).map(([name, component]) => (
              <article data-tone={EDGE_STATUS_TONE[component.status]} key={name}>
                <div>
                  <span>{AXIS_LABELS[name] ?? name}</span>
                  <strong>{EDGE_STATUS_LABELS[component.status]}</strong>
                </div>
                <p>
                  {component.value === null || component.value === undefined
                    ? "无数值"
                    : `${component.value.toLocaleString("zh-CN", {
                        maximumFractionDigits: 4,
                      })}${component.unit ? ` ${component.unit}` : ""}`}
                </p>
                <small>{component.reason_code ?? "未提供原因码"}</small>
              </article>
            ))}
          </div>
        ) : (
          <p className="edge-component-empty" role="status">
            该候选没有逐项证据分解（常见于已被拒绝或尚未计算细分依据的候选）。
          </p>
        )}
      </section>

      <section aria-label="税后期望值分解" className="absolute-ev-block">
        <h4>税后期望值分解（卖方视角）</h4>
        {evAfterCost === null ? (
          <p className="absolute-ev-empty" role="status">
            尚无已验证的路径风险证据，无法计算税后 EV；不会显示为 0 或留空占位。
          </p>
        ) : (
          <>
            <dl className="absolute-ev-grid">
              <div>
                <dt>入场信用</dt>
                <dd>{formatUsdc(entryCredit)}</dd>
              </div>
              <div>
                <dt>预期支出（卖方成本，非利润）</dt>
                <dd>{formatUsdc(expectedPayout)}</dd>
              </div>
              <div>
                <dt>建模费用</dt>
                <dd>{formatUsdc(feesTotal)}</dd>
              </div>
              <div>
                <dt>税后 EV = 信用 − 支出 − 费用</dt>
                <dd>{formatUsdcSigned(evAfterCost)}</dd>
              </div>
            </dl>
            <p className="absolute-ev-sample">
              独立不重叠样本量：{formatCount(sampleSize)}（
              {absoluteEv?.sample_size_basis ?? "样本口径未提供"}） · 证据等级：
              {absoluteEv?.evidence_class ?? "未提供"}
            </p>
          </>
        )}
      </section>

      <section aria-label="路径风险与保证金证据" className="path-risk-block">
        <h4>路径风险 · 保证金 · 公允 IV</h4>
        <dl className="path-risk-grid">
          <div>
            <dt>路径风险状态</dt>
            <dd>{pathRisk?.status ?? "未提供"}</dd>
          </div>
          <div>
            <dt>P(触及) / P(到期实值)</dt>
            <dd>
              {finiteNumber(pathRisk?.p_touch)?.toFixed(3) ?? "—"} /{" "}
              {finiteNumber(pathRisk?.p_itm)?.toFixed(3) ?? "—"}
            </dd>
          </div>
          <div>
            <dt>CVaR 95 / 99</dt>
            <dd>
              {formatUsdc(finiteNumber(pathRisk?.cvar_95_usdc))} /{" "}
              {formatUsdc(finiteNumber(pathRisk?.cvar_99_usdc))}
            </dd>
          </div>
          <div>
            <dt>保证金参考</dt>
            <dd>{formatUsdc(finiteNumber(marginSnapshot?.reference_margin_usdc))}</dd>
          </div>
          <div>
            <dt>公允 IV 残差</dt>
            <dd>
              {finiteNumber(fairIv?.residual_iv_points)?.toFixed(2) ?? "—"} pt ·{" "}
              {fairIv?.residual_status ?? "未提供"}
            </dd>
          </div>
        </dl>
      </section>

      <section aria-label="淘汰条件" className="kill-conditions-block">
        <h4>淘汰条件</h4>
        {row.killConditions.length > 0 ? (
          <ul>
            {row.killConditions.map((code) => (
              <li key={code}>
                <strong>{KILL_CONDITION_LABELS[code] ?? humanizeReasonCode(code)}</strong>
                <code>{code}</code>
              </li>
            ))}
          </ul>
        ) : (
          <p>报告未列出淘汰条件。</p>
        )}
      </section>
    </section>
  );
}
