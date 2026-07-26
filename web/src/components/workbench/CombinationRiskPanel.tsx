import { useMemo } from "react";

import type { ResearchReport } from "../../contracts";
import { instrumentOf, money, signedMoney } from "../candidate/format";
import { structureLabel } from "../candidate/vocabulary";
import { DivergingBars } from "../viz/DivergingBars";
import type { DivergingRow } from "../viz/DivergingBars";
import { PayoffChart } from "../viz/PayoffChart";
import type { PayoffSeries } from "../viz/PayoffChart";
import { breakevens, parseLegs, payoffPoints } from "../viz/payoff";

interface CombinationMember {
  candidate_id?: string;
  structure_type?: string;
  expiry_date?: string;
  credit_usdc?: number | null;
  max_loss_usdc?: number | null;
  loss_is_bounded?: boolean;
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * What the leading candidates do when held together.
 *
 * Everything else in this product reports one candidate at a time, which is the
 * wrong unit for deciding what to put on: two short call spreads a strike apart
 * are very nearly the same trade twice, and a per-candidate view shows them as
 * two moderate positions. The two places aggregation lies — a maximum loss
 * summed across expiries, and a net vega that hides its term composition — are
 * given the most space here rather than the least.
 */
export function CombinationRiskPanel({
  report,
  spotUsdc,
}: {
  report: ResearchReport;
  spotUsdc: number | null;
}): React.JSX.Element | null {
  const combination = report.combination_risk as
    | Record<string, unknown>
    | undefined;

  const scanner = report.ev_candidate_scanner as
    | { ranked_candidates?: Array<Record<string, unknown>> }
    | undefined;

  const members = (combination?.members as CombinationMember[] | undefined) ?? [];
  const book = (combination?.book as Record<string, unknown> | undefined) ?? {};
  const greeks = (book.greeks as Record<string, unknown> | undefined) ?? {};

  const payoff = useMemo(() => {
    const ranked = scanner?.ranked_candidates ?? [];
    const byId = new Map(
      ranked.map((row) => [String(row.candidate_id ?? ""), row]),
    );
    const single = new Set(
      members.map((member) => String(member.expiry_date ?? "")),
    );
    // A combined curve is only defined when every leg settles on one date. With
    // more than one expiry the members are drawn on their own and no combined
    // line is claimed.
    const jointlyEvaluable = single.size === 1;

    const series: PayoffSeries[] = [];
    const allLegs: ReturnType<typeof parseLegs> = [];
    let totalCredit = 0;

    for (const member of members) {
      const raw = byId.get(String(member.candidate_id ?? ""));
      const legs = parseLegs(raw?.structure_legs);
      const credit = number(member.credit_usdc) ?? 0;
      if (legs.length === 0) {
        continue;
      }
      allLegs.push(...legs);
      totalCredit += credit;
      series.push({
        key: String(member.candidate_id),
        label: instrumentOf(String(member.candidate_id ?? "")),
        emphasis: "context",
        points: payoffPoints(legs, { entryCash: credit, spot: spotUsdc }),
      });
    }

    if (jointlyEvaluable && allLegs.length > 0) {
      series.push({
        key: "__book__",
        label: "组合",
        emphasis: "subject",
        points: payoffPoints(allLegs, {
          entryCash: totalCredit,
          spot: spotUsdc,
        }),
      });
    }
    return { jointlyEvaluable, series, allLegs, totalCredit };
  }, [members, scanner, spotUsdc]);

  if (!combination || combination.status !== "evaluated") {
    return null;
  }

  const vegaByExpiry = (greeks.by_expiry as Record<string, Record<string, number>> | undefined) ?? {};
  const vegaRows: DivergingRow[] = Object.entries(vegaByExpiry).map(
    ([expiry, values]) => ({
      key: expiry,
      label: expiry,
      value: number(values?.vega),
    }),
  );
  const netVega = number((greeks.net as Record<string, unknown> | undefined)?.vega);

  const marginal =
    (combination.marginal_contributions as Array<Record<string, unknown>>) ?? [];
  const marginalRows: DivergingRow[] = marginal.map((row) => ({
    key: String(row.candidate_id),
    label: instrumentOf(String(row.candidate_id ?? "")),
    value: number(row.marginal_max_loss_usdc),
    note:
      row.status === "evaluated"
        ? undefined
        : "跨到期日时无法计算联合最坏情况",
  }));

  const joint = (book.joint_terminal_risk as Record<string, unknown>) ?? {};
  const jointMaxLoss = number(joint.max_loss_usdc);
  const upperBound = number(book.max_loss_upper_bound_usdc);
  const curvePoints =
    payoff.series.find((item) => item.emphasis === "subject")?.points ?? [];

  return (
    <section className="combination-panel" aria-labelledby="combination-heading">
      <header className="research-section-heading">
        <div>
          <p className="section-kicker">Combination risk / 组合风险</p>
          <h2 id="combination-heading">这几个一起做会怎样</h2>
        </div>
        <p>
          按每个结构一张计算，<strong>不含任何手数</strong>。前沿候选共 {members.length} 个。
        </p>
      </header>

      <div className="combination-tiles">
        <div className="stat-tile">
          <dt>合计信用</dt>
          <dd>{money(number(book.total_credit_usdc))}</dd>
        </div>
        <div className="stat-tile">
          <dt>联合最大亏损</dt>
          <dd>
            {jointMaxLoss === null ? (
              <span className="stat-tile-unavailable">跨到期日不可计算</span>
            ) : (
              money(jointMaxLoss)
            )}
          </dd>
        </div>
        <div className="stat-tile">
          <dt>上界（各成员最坏情况之和）</dt>
          <dd>
            {upperBound === null ? (
              <span className="stat-tile-unavailable">含无界成员</span>
            ) : (
              money(upperBound)
            )}
          </dd>
        </div>
      </div>

      {jointMaxLoss === null ? (
        <p className="combination-caveat" role="note">
          {String(joint.note ?? "")} 上界假设每个成员的最坏情况同时发生。
        </p>
      ) : upperBound !== null && upperBound > jointMaxLoss ? (
        <p className="combination-caveat" role="note">
          把各成员最坏情况相加会得到 {money(upperBound)}，其中{" "}
          {money(upperBound - jointMaxLoss)} 是<strong>不可能同时发生</strong>的风险。
        </p>
      ) : null}

      {payoff.series.length > 0 ? (
        <div className="combination-block">
          <h3>到期盈亏</h3>
          {payoff.jointlyEvaluable ? null : (
            <p className="combination-note">
              成员分属不同到期日，没有单一的联合到期曲线；下面画的是各成员自己的曲线。
            </p>
          )}
          <PayoffChart
            ariaLabel="组合与各成员的到期盈亏曲线"
            currentSpot={spotUsdc}
            formatMoney={(value) => money(value, { digits: 0 })}
            markers={breakevens(curvePoints).map((spot) => ({
              spot,
              label: "盈亏平衡",
            }))}
            series={payoff.series}
          />
        </div>
      ) : null}

      {vegaRows.length > 0 ? (
        <div className="combination-block">
          <h3>Vega 按到期日拆分</h3>
          <p className="combination-note">
            净 vega {netVega === null ? "不可用" : signedMoney(netVega)}
            ，它隐含「波动率平行移动」这个假设。下面是它掩盖掉的构成。
          </p>
          <DivergingBars
            ariaLabel="组合 vega 按到期日拆分"
            format={(value) => signedMoney(value)}
            rows={vegaRows}
            unit="USD / IV 点"
          />
        </div>
      ) : null}

      {marginalRows.length > 0 ? (
        <div className="combination-block">
          <h3>边际贡献</h3>
          <p className="combination-note">
            按「把它移出组合」计算，而不是它自己的最坏情况——一个与既有仓位对冲的候选，
            贡献小于它单独看起来的样子。
          </p>
          <DivergingBars
            ariaLabel="各成员对组合最大亏损的边际贡献"
            format={(value) => signedMoney(value)}
            rows={marginalRows}
            unit="USDC"
          />
        </div>
      ) : null}

      <ul className="combination-cannot-tell">
        {((combination.cannot_tell as string[]) ?? []).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </section>
  );
}

export function combinationMemberSummary(
  member: CombinationMember,
): string {
  return `${instrumentOf(String(member.candidate_id ?? ""))} · ${structureLabel(
    member.structure_type,
  )}`;
}
