import { useEffect, useState } from "react";

import type { ResearchReport } from "../../contracts";
import { APP_INDEX_HREF, RAW_REPORT_HREF, VIEW_LINKS } from "../../publicPaths";
import { SectionNavigation } from "../evidence/Shell";
import type { Freshness } from "../evidence/reportModel";
import { formatCutoffTime } from "../evidence/reportModel";
import { formatDurationHours } from "../../report/display";
import { PublishedEditionBar } from "./PublishedEditionBar";
import { ReplayBanner } from "./ReplayBanner";
import { SiteFooter } from "./SiteFooter";

export type AppView = "evidence" | "workbench" | "series" | "signal";

function currentViewId(view: AppView): AppView {
  return view;
}

export function AppShell({
  children,
  freshness,
  onRefresh,
  refreshing,
  report,
  source,
  view,
}: {
  children: React.ReactNode;
  freshness?: Freshness;
  onRefresh?: () => void;
  refreshing: boolean;
  report: ResearchReport;
  source?: string;
  view: AppView;
}): React.JSX.Element {
  const [activeView, setActiveView] = useState<AppView>(() => currentViewId(view));

  useEffect(() => {
    const sync = () => {
      setActiveView(currentViewId(view));
    };
    sync();
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("popstate", sync);
    };
  }, [view]);

  const age =
    freshness?.ageSec === null || freshness?.ageSec === undefined
      ? null
      : freshness.mode === "published"
        ? null
        : `${freshness.ageSec.toLocaleString("zh-CN")} 秒`;
  const cutoff = report.publish_edition?.captured_at ?? report.generated_at ?? null;
  const publishedStale =
    report.runtime_context?.mode === "published" && freshness?.phase === "expired";
  // The boundary comes from the report's own stale_after contract; hardcoding
  // "48 hours" here would contradict PublicShell when the publisher picks a
  // different window.
  const staleBoundaryLabel = publishedStale
    ? formatDurationHours(freshness?.maxAgeSec ?? Number.NaN)
    : null;
  const refreshLabel =
    report.runtime_context?.mode === "published" ? "重新载入本版" : "刷新";

  return (
    <div className="app-shell app-shell-spine">
      <a className="skip-link" href="#surface-main">
        跳到主要内容
      </a>

      <header className="spine-masthead">
        <a className="brand" href={APP_INDEX_HREF} aria-label="LensOS 期权研究台首页">
          <span className="brand-mark" aria-hidden="true">
            LO
          </span>
          <span>
            <strong>LensOS Option</strong>
            <small>Research brief</small>
          </span>
        </a>

        <nav aria-label="全视图导航" className="spine-views">
          {VIEW_LINKS.map((item) => (
            <a
              aria-current={activeView === item.id ? "page" : undefined}
              href={item.href}
              key={item.id}
            >
              {item.label}
            </a>
          ))}
        </nav>

        <div className="spine-actions">
          {freshness ? (
            <span
              className="source-indicator"
              data-state={freshness.phase}
              aria-label={`市场来源 ${source ?? "未提供"}，数据年龄 ${age ?? "由公开版时效条展示"}`}
            >
              <span aria-hidden="true" />
              {source}
              {age ? ` · ${age}` : ""}
            </span>
          ) : null}
          <a
            className="text-link"
            href={RAW_REPORT_HREF}
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
              {refreshing ? `${refreshLabel}中…` : refreshLabel}
            </button>
          ) : null}
        </div>
      </header>

      {freshness ? <PublishedEditionBar freshness={freshness} report={report} /> : null}
      <ReplayBanner report={report} />

      <div className="spine-boundary" role="note">
        <dl>
          <div data-tone="danger">
            <dt>执行边界</dt>
            <dd>RESEARCH_ONLY · NO_TRADE</dd>
          </div>
          <div data-tone="neutral">
            <dt>数据截止</dt>
            <dd>{formatCutoffTime(cutoff)}</dd>
          </div>
        </dl>
      </div>
      {view === "evidence" ? <SectionNavigation /> : null}

      {publishedStale ? (
        <main className="published-stop-main" id="surface-main">
          <section className="published-stop-card" role="alert">
            <p className="section-kicker">publication stalled / fail closed</p>
            <h1>发布已停摆</h1>
            <p>
              当前公开版已超过 {staleBoundaryLabel}
              时效边界。VRP、DVOL、曲面、候选与历史验证数值均已收起，
              直到下一版通过数据质量门禁并完成发布。
            </p>
            {onRefresh ? (
              <button
                aria-busy={refreshing}
                className="refresh-button"
                disabled={refreshing}
                onClick={onRefresh}
                type="button"
              >
                {refreshing ? "重新载入本版中…" : "重新载入本版"}
              </button>
            ) : null}
          </section>
        </main>
      ) : (
        children
      )}

      <SiteFooter />
    </div>
  );
}
