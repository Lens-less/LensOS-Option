import type { ResearchReport } from "../../contracts";
import type { Freshness } from "../evidence/reportModel";
import { FRESHNESS_LABELS, formatCutoffTime } from "../evidence/reportModel";

/** Describe collection policy independently of evidence or strategy eligibility. */
export function ResearchSourceBar({ report, freshness, refreshing, onRefresh }: {
  report: ResearchReport;
  freshness?: Freshness;
  refreshing: boolean;
  onRefresh?: () => void;
}): React.JSX.Element {
  const runtime = report.runtime_context;
  const demo = runtime?.demo_mode === true;
  const replay = runtime?.replay === true;
  const published = runtime?.mode === "published";
  const live = runtime?.live_fetch_allowed === true && !demo && !replay && !published;
  const title = demo ? "包内历史快照" : replay ? "历史快照回放" : published ? "公开研究快照" : live ? "Deribit 公开行情" : "本地研究快照";
  const description = demo || replay
    ? "仅复核采集时刻的研究；重新读取不会采集当前行情。"
    : published ? "本版由发布者采集；重新载入不会产生新的行情。"
    : live ? "读取公开市场数据。有效快照会复用，过期后重新采集。"
    : "读取启动时配置的输入文件；更新行情需先更新本地快照。";
  const label = live ? "更新公开行情" : published ? "重新载入本版" : "重新读取快照";
  const cutoff = report.publish_edition?.captured_at ?? runtime?.evaluation_clock ?? report.generated_at;
  const freshnessLabel = freshness && (demo || replay)
    ? `回放窗口${freshness.phase === "current" ? "有效" : freshness.phase === "warning" ? "预警" : freshness.phase === "expired" ? "已失效" : "不可用"}`
    : freshness ? FRESHNESS_LABELS[freshness.phase] : null;
  return (
    <section className="research-source-bar" aria-label="数据模式">
      <div className="research-source-copy">
        <div className="research-source-title"><strong>{title}</strong><span className="research-mode-tag">{demo || replay ? "历史" : published ? "公开版" : live ? "当前采集" : "本地文件"}</span></div>
        <p>{description}</p>
        <p className="research-source-time">{demo || replay || published ? "数据截止" : "评估于"} {formatCutoffTime(cutoff ?? null)}{freshnessLabel ? ` · ${freshnessLabel}` : ""}</p>
        <span className="research-source-boundary">仅研究 · NO_TRADE</span>
      </div>
      {onRefresh ? <button className="refresh-button" type="button" onClick={onRefresh} disabled={refreshing} aria-busy={refreshing}>
        {refreshing ? live ? "正在采集与核验…" : "正在读取…" : label}
      </button> : null}
    </section>
  );
}
