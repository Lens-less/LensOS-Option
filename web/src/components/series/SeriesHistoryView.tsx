import { useEffect, useMemo, useState } from "react";

import {
  isArtifactRecord,
  matchesExpectedArtifactCapture,
} from "../artifactCapture";
import { money, ratio, signed } from "../candidate/format";
import {
  artifactFailureDetail,
  loadArtifactJson,
} from "../../transport/artifactJson";
import { ResidualHeatmap } from "../viz/ResidualHeatmap";
import type { HeatmapRow } from "../viz/ResidualHeatmap";
import { VIZ } from "../viz/tokens";
import { evidenceCount, ResearchProgress } from "../research/ResearchProgress";

interface SeriesPoint {
  date: string;
  present: boolean;
  residual_z?: number | null;
  mark_iv?: number | null;
  model_delta?: number | null;
  bid_usdc?: number | null;
  dte_days?: number | null;
}

interface SeriesInstrument {
  instrument_name: string;
  expiry_date?: string;
  option_type?: string;
  strike_price?: number | null;
  capture_date_count?: number;
  missing_date_count?: number;
  latest?: Record<string, unknown>;
  residual_z?: Record<string, unknown>;
  persistence?: Record<string, unknown>;
  points?: SeriesPoint[];
}

interface SeriesArtifact {
  captured_at?: string;
  generated_at?: string;
  status?: string;
  detail?: string;
  reason_codes?: string[];
  capture_dates?: string[];
  capture_count?: number;
  instrument_count?: number;
  instruments?: SeriesInstrument[];
  truncated_instruments?: number;
  cannot_tell?: string[];
  usable_capture_dates?: string[];
  config?: { min_capture_dates?: number };
}

interface LoadedSeriesArtifact {
  artifact: SeriesArtifact;
  expectedCapturedAt?: string;
  url: string;
  retryKey?: unknown;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * What the capture series already knows, which nothing was asking it.
 *
 * The daily capture exists for the validation sample, and it has been answering
 * a different question the whole time: was this strike rich yesterday too? The
 * caveat is placed above the chart rather than below it, because the chart is
 * persuasive and the caveat is the part that decides what it means.
 */
export function SeriesHistoryView({
  artifact,
}: {
  artifact: SeriesArtifact | null;
}): React.JSX.Element {
  const [selected, setSelected] = useState<string | null>(null);

  const instruments = useMemo(
    () => artifact?.instruments ?? [],
    [artifact],
  );
  const dates = artifact?.capture_dates ?? [];

  const rows: HeatmapRow[] = instruments.map((instrument) => ({
    key: instrument.instrument_name,
    label: instrument.instrument_name,
    cells: (instrument.points ?? []).map((point) => ({
      date: point.date,
      present: point.present,
      value: num(point.residual_z),
    })),
  }));

  const current =
    instruments.find((item) => item.instrument_name === selected) ?? null;

  if (!artifact) {
    return (
      <main className="series-view" id="surface-main">
        <p className="signal-loading" role="status">
          正在读取序列历史…
        </p>
      </main>
    );
  }

  if (artifact.status !== "measured") {
    const unavailable = artifact.status !== "blocked";
    const availableDates = artifact.usable_capture_dates;
    const count = availableDates ? new Set(availableDates).size : null;
    const required = evidenceCount(artifact.config?.min_capture_dates);
    const missing = count !== null && required !== null && count < required
      ? [`还需 ${required - count} 个有效采集日，并保证同一合约在所需日期里都有有效读数。`]
      : ["同一合约需要覆盖足够的有效采集日；总日期数达标不保证每个合约已有可比较的序列。"];
    return (
      <main className="series-view" id="surface-main">
        <header className="research-section-heading">
          <div>
            <p className="section-kicker">Series history / 序列历史</p>
            <h1>{unavailable ? "序列产物尚不可用" : "序列还不够长"}</h1>
          </div>
        </header>
        <ResearchProgress
          label="序列验证进度"
          conclusion={unavailable ? "尚未读取到可核对的序列证据" : count !== null && count > 0 ? "已有采集，尚不能比较跨日变化" : "还没有足够的有效采集"}
          evidenceState={unavailable ? "证据状态：不可用" : "证据状态：序列未通过验证"}
          nextStep={unavailable ? "重新读取当前报告；若仍不可用，核对序列产物是否已生成并接入。" : "继续采集同一合约的有效报价，再重新生成序列；缺失日期保留为空，不补插值。"}
          missing={unavailable ? ["需要能通过校验的序列产物，才能确认已有日期和缺失条件。"] : missing}
          progress={unavailable ? undefined : { label: "有效采集日", current: count, required }}
          dates={unavailable ? undefined : availableDates}
          generatedAt={artifact.generated_at}
          reasonCodes={artifact.reason_codes}
        >
          {artifact.detail ? <p>{artifact.detail}</p> : null}
        </ResearchProgress>
      </main>
    );
  }

  return (
    <main className="series-view" id="surface-main">
      <header className="research-section-heading">
        <div>
          <p className="section-kicker">Series history / 序列历史</p>
          <h1>这个行权价昨天也这么贵吗</h1>
        </div>
        <p>
          {artifact.capture_count} 个采集日 · {artifact.instrument_count} 个合约
        </p>
      </header>

      {/* Above the chart, not below it: the chart is persuasive and this is the
          part that decides what it means. */}
      <p className="series-caveat" role="note">
        <strong>持续为正不等于机会。</strong>
        一条始终为正的残差，同样可能说明二次拟合在那个行权价上跟不上真实的翼部——
        模型系统性偏了，而不是市场持续错了。这张图长什么样，两种情况下是一样的。
      </p>

      <section className="series-block">
        <h2>标准化残差 · 合约 × 采集日</h2>
        <p className="series-note">
          用标准化残差而不是原始 IV：合约每天都在临近到期，它的 IV、delta 与权利金
          都会因此移动，与错价无关。排序用按观测数向零收缩的均值——否则只出现三天的
          合约会靠三个读数排到最前面。
        </p>
        <div className="series-selection">
          <label className="signal-select">
            选择合约查看逐日读数
            <select value={current?.instrument_name ?? ""} onChange={(event) => setSelected(event.target.value)}>
              <option value="" disabled>请选择合约</option>
              {instruments.map((instrument) => <option key={instrument.instrument_name} value={instrument.instrument_name}>{instrument.instrument_name}</option>)}
            </select>
          </label>
          {current ? <a className="text-link" href="#series-instrument-detail">跳到该合约的逐日读数</a> : null}
        </div>
        <ResidualHeatmap
          ariaLabel="各合约标准化残差随采集日的变化"
          dates={dates}
          onSelect={setSelected}
          rows={rows}
          selectedKey={selected}
        />
        {artifact.truncated_instruments ? (
          <p className="series-note">
            另有 {artifact.truncated_instruments} 个合约未显示（按排序截断）。
          </p>
        ) : null}
      </section>

      {current ? (
        <InstrumentDetail instrument={current} />
      ) : (
        <p className="series-note">点击上方任意一行查看该合约的逐日读数。</p>
      )}

      <ul className="series-cannot-tell">
        {(artifact.cannot_tell ?? []).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </main>
  );
}

function InstrumentDetail({
  instrument,
}: {
  instrument: SeriesInstrument;
}): React.JSX.Element {
  const points = instrument.points ?? [];
  const persistence = instrument.persistence ?? {};
  const summary = instrument.residual_z ?? {};
  const observed = points.filter(
    (point) => point.present && num(point.residual_z) !== null,
  );

  return (
    <section className="series-block" id="series-instrument-detail" tabIndex={-1} aria-label={instrument.instrument_name}>
      <h2>{instrument.instrument_name}</h2>
      <div className="series-tiles">
        <div className="stat-tile">
          <dt>收缩后均值</dt>
          <dd>{signed(num(persistence.shrunk_mean), { digits: 2 })}</dd>
        </div>
        <div className="stat-tile">
          <dt>原始均值</dt>
          <dd>{signed(num(summary.mean), { digits: 2 })}</dd>
        </div>
        <div className="stat-tile">
          <dt>采集覆盖</dt>
          <dd>
            {instrument.capture_date_count}
            <small>
              {" "}
              日 · 缺 {instrument.missing_date_count}
            </small>
          </dd>
        </div>
        <div className="stat-tile">
          <dt>读数为正的比例</dt>
          <dd>
            {num(summary.positive_share) === null
              ? "—"
              : `${Math.round((num(summary.positive_share) ?? 0) * 100)}%`}
          </dd>
        </div>
      </div>

      <div className="series-table-scroll" role="region" aria-label="合约逐日读数" tabIndex={0}>
        <table className="signal-table">
          <thead>
            <tr>
              <th scope="col">采集日</th>
              <th scope="col">残差 (σ)</th>
              <th scope="col">DTE</th>
              <th scope="col">delta</th>
              <th scope="col">mark IV</th>
              <th scope="col">买价</th>
            </tr>
          </thead>
          <tbody>
            {observed.map((point) => (
              <tr key={point.date}>
                <th scope="row">{point.date}</th>
                <td
                  className="numeric-cell"
                  style={{
                    color:
                      (num(point.residual_z) ?? 0) >= 0
                        ? VIZ.positive
                        : VIZ.negative,
                  }}
                >
                  {signed(num(point.residual_z), { digits: 2 })}
                </td>
                <td className="numeric-cell">
                  {ratio(num(point.dte_days), { digits: 1 })}
                </td>
                <td className="numeric-cell">
                  {ratio(num(point.model_delta), { digits: 3 })}
                </td>
                <td className="numeric-cell">
                  {ratio(num(point.mark_iv), { digits: 2 })}
                </td>
                <td className="numeric-cell">{money(num(point.bid_usdc))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="series-note">
        只列出实际采集到的日期。缺失日不补插值，因为「没采到」和「读数为零」不是一回事。
      </p>
    </section>
  );
}

/** Loads one capture-bound artifact and never renders an older URL while refetching. */
export function useSeriesArtifact(
  url: string | null,
  expectedCapturedAt?: string,
  retryKey?: unknown,
): SeriesArtifact | null {
  const [loaded, setLoaded] = useState<LoadedSeriesArtifact | null>(null);
  useEffect(() => {
    if (!url) {
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    void loadArtifactJson(url, controller.signal)
      .then((payload) => {
        if (!cancelled) {
          const artifact =
            isArtifactRecord(payload) &&
            matchesExpectedArtifactCapture(payload, expectedCapturedAt)
              ? (payload as SeriesArtifact)
              : {
                  status: "not_configured",
                  detail: expectedCapturedAt
                    ? "序列产物与当前公开版的数据截止时间不一致，已停止展示。"
                    : undefined,
                };
          setLoaded({ artifact, expectedCapturedAt, url, retryKey });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoaded({
            artifact: {
              status: "not_configured",
              detail: artifactFailureDetail(error),
            },
            expectedCapturedAt,
            url,
            retryKey,
          });
        }
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [expectedCapturedAt, url, retryKey]);
  return url &&
    loaded?.url === url &&
    loaded.expectedCapturedAt === expectedCapturedAt && loaded.retryKey === retryKey
    ? loaded.artifact
    : null;
}
