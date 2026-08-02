import { useEffect, useState } from "react";

import { money, ratio, signed } from "../candidate/format";
import { DivergingBars } from "../viz/DivergingBars";
import type { DivergingRow } from "../viz/DivergingBars";
import { VIZ } from "../viz/tokens";

interface SignalArtifact {
  schema_version?: string;
  status?: string;
  reason_code?: string;
  detail?: string;
  reason_codes?: string[];
  t_stat_threshold?: number;
  sample?: Record<string, unknown>;
  bands?: Record<string, Record<string, unknown>>;
  cohorts?: Array<Record<string, unknown>>;
  signals?: Record<string, Record<string, unknown>>;
  collinearity?: Record<string, unknown>;
  summary?: Record<string, unknown>;
  pre_registration?: Record<string, unknown>;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * The accumulating validation sample, and — once there is one — its measurement.
 *
 * The sample cannot be backfilled, so for weeks the honest content of this
 * screen is "what has been collected and what is still pending". That state
 * gets the same care as the measured one, because it is the one that will
 * actually be looked at.
 */
export function SignalValidationView({
  artifact,
}: {
  artifact: SignalArtifact | null;
}): React.JSX.Element {
  if (!artifact) {
    return (
      <main className="signal-view" id="surface-main">
        <p className="signal-loading" role="status">
          正在读取信号验证产物…
        </p>
      </main>
    );
  }

  if (artifact.status === "not_configured") {
    return (
      <main className="signal-view" id="surface-main">
        <header className="research-section-heading">
          <div>
            <p className="section-kicker">Signal validation / 信号验证</p>
            <h1>排序信号有没有预测力</h1>
          </div>
        </header>
        <p className="signal-empty">
          {artifact.detail || "验证产物尚未接入；这不改变研究边界，只是当前无法展示统计结论。"}
        </p>
      </main>
    );
  }

  return (
    <main className="signal-view" id="surface-main">
      <header className="research-section-heading">
        <div>
          <p className="section-kicker">Signal validation / 信号验证</p>
          <h1>排序信号有没有预测力</h1>
        </div>
        <p>
          排序主轴本身也在被度量之列，结论可能是「没有可检出的 edge」。
          <strong>这正是它存在的意义。</strong>
        </p>
      </header>

      {artifact.status === "projected" ? (
        <PreflightSections artifact={artifact} />
      ) : null}
      {artifact.status === "measured" ? (
        <MeasuredSections artifact={artifact} />
      ) : null}
      {artifact.status === "blocked" ? (
        <BlockedSection artifact={artifact} />
      ) : null}
    </main>
  );
}

function BlockedSection({
  artifact,
}: {
  artifact: SignalArtifact;
}): React.JSX.Element {
  const sample = artifact.sample ?? {};
  return (
    <section className="signal-block">
      <h2>样本尚不足以发布统计量</h2>
      <p className="signal-note">
        已采集 {String(num(sample.observation_count) ?? 0)} 条观测、
        {String(num(sample.independent_expiry_cohorts) ?? 0)} 个已结算到期日
        cohort。样本量按 cohort 计，不按观测数——相邻两天的快照是同一批合约、
        同一个结算价。
      </p>
      <ul className="signal-reasons">
        {(artifact.reason_codes ?? []).map((code) => (
          <li key={code}>
            <code>{code}</code>
          </li>
        ))}
      </ul>
    </section>
  );
}

function PreflightSections({
  artifact,
}: {
  artifact: SignalArtifact;
}): React.JSX.Element {
  const bands = artifact.bands ?? {};
  const research = bands.research_window ?? {};
  const cohorts = artifact.cohorts ?? [];

  return (
    <>
      <div className="signal-tiles">
        <div className="stat-tile">
          <dt>已结算 cohort</dt>
          <dd>
            {num(research.settled_cohorts) ?? 0}
            <small> / {num(research.cohorts_required) ?? 8}</small>
          </dd>
        </div>
        <div className="stat-tile">
          <dt>待结算 cohort</dt>
          <dd>{num(research.pending_cohorts) ?? 0}</dd>
        </div>
        <div className="stat-tile">
          <dt>待结算观测</dt>
          <dd>
            {(num(research.pending_observation_count) ?? 0).toLocaleString(
              "zh-CN",
            )}
          </dd>
        </div>
      </div>

      <p className="signal-note">
        采集<strong>不可回补</strong>：Deribit 不发布历史期权链，样本只能向前累积。
        下表是每个已采集到期日在结算后能贡献什么——它让一个什么都产不出的序列在第一天就说出来，
        而不是第六十天。
      </p>

      <section className="signal-block">
        <h2>各到期日 cohort</h2>
        <div className="signal-table-scroll">
          <table className="signal-table">
            <thead>
              <tr>
                <th scope="col">到期日</th>
                <th scope="col">波段</th>
                <th scope="col">采集天数</th>
                <th scope="col">DTE</th>
                <th scope="col">预计观测</th>
                <th scope="col">结算价可用</th>
                <th scope="col">阻塞原因</th>
              </tr>
            </thead>
            <tbody>
              {cohorts.map((cohort) => {
                const blocking = cohort.blocking_reasons as
                  | Record<string, number>
                  | undefined;
                const settled = cohort.settlement_close_available === true;
                return (
                  <tr key={String(cohort.expiry_date)}>
                    <th scope="row">{String(cohort.expiry_date)}</th>
                    <td>
                      {cohort.band === "research_window" ? "研究窗口" : "短期"}
                    </td>
                    <td className="numeric-cell">
                      {num(cohort.capture_date_count) ?? 0}
                    </td>
                    <td className="numeric-cell">
                      {ratio(num(cohort.dte_days_min), { digits: 1 })}
                    </td>
                    <td className="numeric-cell">
                      {(
                        num(cohort.prospective_observation_count) ?? 0
                      ).toLocaleString("zh-CN")}
                    </td>
                    <td>
                      <span
                        className="tier-badge"
                        data-tone={settled ? "safe" : "warning"}
                      >
                        {settled ? "已结算" : "待结算"}
                      </span>
                    </td>
                    <td className="signal-blocking">
                      {blocking && Object.keys(blocking).length > 0
                        ? Object.entries(blocking)
                            .map(([code, count]) => `${code}×${count}`)
                            .join(" · ")
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function MeasuredSections({
  artifact,
}: {
  artifact: SignalArtifact;
}): React.JSX.Element {
  const signals = artifact.signals ?? {};
  const threshold = num(artifact.t_stat_threshold) ?? 2;
  const sample = artifact.sample ?? {};
  const [selected, setSelected] = useState<string>(
    () => Object.keys(signals).find((key) => key.includes("smile_residual_z")) ??
      Object.keys(signals)[0] ??
      "",
  );

  const registration = artifact.pre_registration ?? {};
  const registeredAxis = String(registration.axis ?? "");
  const summary = artifact.summary ?? {};

  const rows: DivergingRow[] = Object.entries(signals).map(([name, item]) => {
    const ic = item.information_coefficient as
      | Record<string, unknown>
      | undefined;
    return {
      key: name,
      label: name,
      value: num(ic?.t_stat),
      note:
        item.status === "measured" ? undefined : String(item.reason_code ?? "样本不足"),
    };
  });

  const current = signals[selected] as Record<string, unknown> | undefined;
  const buckets = (current?.buckets as Array<Record<string, unknown>>) ?? [];
  const collinearity = artifact.collinearity ?? {};
  const equivalent =
    (collinearity.rank_equivalent_pairs as Array<Record<string, unknown>>) ?? [];

  return (
    <>
      <div className="signal-tiles">
        <div className="stat-tile">
          <dt>独立 cohort</dt>
          <dd>{num(sample.independent_expiry_cohorts) ?? 0}</dd>
        </div>
        <div className="stat-tile">
          <dt>观测数</dt>
          <dd>
            {(num(sample.observation_count) ?? 0).toLocaleString("zh-CN")}
          </dd>
        </div>
        <div className="stat-tile">
          <dt>实际不同排序</dt>
          <dd>
            {num(collinearity.distinct_signal_estimate) ?? 0}
            <small> / {Object.keys(signals).length}</small>
          </dd>
        </div>
      </div>

      {registeredAxis ? (
        <section className="signal-block signal-registration">
          <h2>事前登记的轴</h2>
          <p className="signal-note">
            这里同时度量 10 个信号（约 7 个不同排序）。在同一份样本上挑出得分最高的
            那个再提升，就是在样本上做选择。所以<strong>只有一个轴</strong>在样本产生之前就被登记，
            其余全部是探索性的：它们的高分只能用于设计下一次登记，永远不能从这份样本
            里被提升。
          </p>
          <dl className="signal-registration-grid">
            <div>
              <dt>登记的轴</dt>
              <dd>
                <code>{registeredAxis}</code>
              </dd>
            </div>
            <div>
              <dt>登记时间</dt>
              <dd>{String(registration.registered_at ?? "—")}</dd>
            </div>
            <div>
              <dt>适用阈值</dt>
              <dd>|t| ≥ {String(registration.threshold ?? threshold)}</dd>
            </div>
            <div>
              <dt>该轴的判定</dt>
              <dd>
                <span
                  className="tier-badge"
                  data-tone={
                    summary.promotion_eligible === true ? "safe" : "warning"
                  }
                >
                  {String(summary.pre_registered_axis_verdict ?? "未度量")}
                </span>
              </dd>
            </div>
          </dl>
          {summary.best_exploratory_signal &&
          summary.best_exploratory_signal !== registeredAxis ? (
            <p className="signal-note">
              本样本里得分最高的是{" "}
              <code>{String(summary.best_exploratory_signal)}</code>
              ，它<strong>不可提升</strong>——记录它，用于下一次登记。
            </p>
          ) : null}
        </section>
      ) : null}

      <section className="signal-block">
        <h2>各信号的 t 值</h2>
        <p className="signal-note">
          中性化后的信息系数除以其标准误，标准误按 cohort 计。
          阈值 ±{threshold} 是发布的判定线，越过它才叫「可检出」。
        </p>
        <DivergingBars
          ariaLabel="各候选信号中性化信息系数的 t 值"
          format={(value) => signed(value, { digits: 2 })}
          referenceLines={[
            { value: threshold, label: `+${threshold}` },
            { value: -threshold, label: `-${threshold}` },
          ]}
          rows={rows}
          unit="t"
        />
      </section>

      {equivalent.length > 0 ? (
        <section className="signal-block">
          <h2>秩等价的信号</h2>
          <p className="signal-note">
            数信号不等于数信息。下面这些对给出<strong>完全相同的排序</strong>，
            它们的一致是重复表述，不是相互印证。
          </p>
          <ul className="signal-equivalent">
            {equivalent.map((pair) => {
              const names = (pair.signals as string[]) ?? [];
              return (
                <li key={names.join("|")}>
                  <code>{names[0]}</code>
                  <span aria-hidden="true">≡</span>
                  <code>{names[1]}</code>
                  <strong>
                    ρ = {ratio(num(pair.mean_rank_correlation), { digits: 3 })}
                  </strong>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {buckets.length > 0 ? (
        <section className="signal-block">
          <h2>分档表</h2>
          <label className="signal-select">
            信号
            <select
              onChange={(event) => setSelected(event.target.value)}
              value={selected}
            >
              {Object.keys(signals).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <DivergingBars
            ariaLabel={`${selected} 各分档的平均结果`}
            format={(value) => signed(value, { digits: 2 })}
            rows={buckets.map((bucket) => ({
              key: String(bucket.bucket),
              label: `第 ${bucket.bucket} 档`,
              value: num(bucket.mean_pnl_per_vega_iv_points),
            }))}
            unit="IV 点 / vega"
          />
          <p className="signal-note">
            若排序有效，从第 1 档到第 5 档应当单调上升。每档的独立 cohort 数见表格视图——
            一个只靠两个到期日撑起来的分档不能当二十个读。
          </p>
        </section>
      ) : null}

      <ul className="signal-cannot-tell">
        {((artifact.summary?.cannot_tell as string[]) ?? []).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </>
  );
}

/** Loads the artifact the engine serves, keeping the previous render on refetch. */
export function useSignalArtifact(): SignalArtifact | null {
  const [artifact, setArtifact] = useState<SignalArtifact | null>(null);
  useEffect(() => {
    let cancelled = false;
    void fetch("/research/signal")
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (!cancelled) {
          setArtifact(payload ?? { status: "not_configured", detail: "" });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setArtifact({ status: "not_configured", detail: "本地引擎不可达。" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return artifact;
}

export const SIGNAL_VIEW_ACCENT = VIZ.subject;
export const formatMoneyForSignals = money;
