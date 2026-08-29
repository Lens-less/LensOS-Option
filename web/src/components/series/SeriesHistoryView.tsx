import { useEffect, useMemo, useState } from "react";

import {
  isArtifactRecord,
  matchesExpectedArtifactCapture,
} from "../artifactCapture";
import { money, ratio, signed } from "../candidate/format";
import {
  artifactFailureDetail,
  readArtifactJson,
} from "../../transport/artifactJson";
import { ResidualHeatmap } from "../viz/ResidualHeatmap";
import type { HeatmapRow } from "../viz/ResidualHeatmap";
import { VIZ } from "../viz/tokens";

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
}

interface LoadedSeriesArtifact {
  artifact: SeriesArtifact;
  expectedCapturedAt?: string;
  url: string;
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
    return (
      <main className="series-view" id="surface-main">
        <header className="research-section-heading">
          <div>
            <p className="section-kicker">Series history / 序列历史</p>
            <h1>序列还不够长</h1>
          </div>
        </header>
        <p className="signal-empty">
          {artifact.detail ??
            "采集序列里还没有足够多的日期。每天采集一次，几天之后这里就会有内容。"}
        </p>
        <ul className="signal-reasons">
          {(artifact.reason_codes ?? []).map((code) => (
            <li key={code}>
              <code>{code}</code>
            </li>
          ))}
        </ul>
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
    <section className="series-block">
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

      <div className="series-table-scroll">
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
): SeriesArtifact | null {
  const [loaded, setLoaded] = useState<LoadedSeriesArtifact | null>(null);
  useEffect(() => {
    if (!url) {
      return;
    }
    let cancelled = false;
    void fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    })
      .then(readArtifactJson)
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
          setLoaded({ artifact, expectedCapturedAt, url });
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
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [expectedCapturedAt, url]);
  return url &&
    loaded?.url === url &&
    loaded.expectedCapturedAt === expectedCapturedAt
    ? loaded.artifact
    : null;
}
