import type { ResearchReport } from "../../contracts";
import type { Freshness } from "../evidence/reportModel";
import { ReplayBanner } from "./ReplayBanner";

export type AppView = "evidence" | "workbench" | "signal";

const VIEWS: Array<{ id: AppView; label: string; hint: string }> = [
  { id: "evidence", label: "证据台", hint: "结论与它依赖的每一份证据" },
  { id: "workbench", label: "候选工作台", hint: "筛选、排序、并排比较候选" },
  { id: "signal", label: "信号验证", hint: "排序信号有没有预测力，以及样本攒到哪一步" },
];

function releaseStatus(report: ResearchReport): string {
  return report.full_system_surface?.release_readiness?.status ?? "NO-GO";
}

/**
 * The single spine both surfaces hang from.
 *
 * The two views used to be switched by a bare button bar floating above the
 * masthead, and each then re-rendered its own masthead and its own copy of the
 * run state — release authority, execution boundary and data freshness appeared
 * two or three times on one page while the way to reach the other view appeared
 * nowhere except a URL parameter. Stating each fact once, in a place that does
 * not move between views, is the whole job of this component.
 */
export function AppShell({
  children,
  freshness,
  onRefresh,
  onViewChange,
  refreshing,
  report,
  source,
  view,
}: {
  children: React.ReactNode;
  freshness?: Freshness;
  onRefresh?: () => void;
  onViewChange: (view: AppView) => void;
  refreshing: boolean;
  report: ResearchReport;
  source?: string;
  view: AppView;
}): React.JSX.Element {
  const age =
    freshness?.ageSec === null || freshness?.ageSec === undefined
      ? null
      : `${freshness.ageSec.toLocaleString("zh-CN")} 秒`;
  const replay = report.runtime_context?.replay === true;

  return (
    <div className="app-shell app-shell-spine" data-replay={replay || undefined}>
      <a className="skip-link" href="#surface-main">
        跳到主要内容
      </a>

      <header className="spine-masthead">
        <a className="brand" href="/evidence" aria-label="LensOS 期权研究台首页">
          <span className="brand-mark" aria-hidden="true">
            LO
          </span>
          <span>
            <strong>LensOS Option</strong>
            <small>Research brief</small>
          </span>
        </a>

        <nav aria-label="视图切换" className="spine-views">
          {VIEWS.map((item) => (
            <button
              aria-current={view === item.id ? "page" : undefined}
              key={item.id}
              onClick={() => onViewChange(item.id)}
              title={item.hint}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="spine-actions">
          {freshness ? (
            <span
              className="source-indicator"
              data-state={replay ? "replay" : freshness.phase}
              aria-label={`市场来源 ${source ?? "未提供"}，数据年龄 ${age ?? "不可用"}`}
            >
              <span aria-hidden="true" />
              {replay ? "回放" : source}
              {age ? ` · ${age}` : ""}
            </span>
          ) : null}
          <a
            className="text-link"
            href="/research/report"
            rel="noreferrer"
            target="_blank"
          >
            原始 JSON
          </a>
          {onRefresh ? (
            <button
              aria-busy={refreshing}
              className="refresh-button"
              disabled={refreshing}
              onClick={onRefresh}
              type="button"
            >
              {refreshing ? "刷新中…" : "刷新"}
            </button>
          ) : null}
        </div>
      </header>

      <ReplayBanner report={report} />

      {/* Stated once, for both views. It used to be repeated per view, which
          made the boundary read as decoration rather than as a constraint. */}
      <div className="spine-boundary" role="note">
        <dl>
          <div data-tone="danger">
            <dt>外部发布授权</dt>
            <dd>{releaseStatus(report)}</dd>
          </div>
          <div data-tone="danger">
            <dt>执行边界</dt>
            <dd>RESEARCH_ONLY · NO_TRADE</dd>
          </div>
          <div data-tone="neutral">
            <dt>报告契约</dt>
            <dd>{report.schema_version}</dd>
          </div>
        </dl>
      </div>

      {children}

      <footer className="page-footer">
        <span>LensOS Option · research only</span>
        <p>真实市场数据用于研究阅读；页面不连接下单与自动执行。</p>
      </footer>
    </div>
  );
}
