import { useEffect, useState } from "react";

import type { ResearchReport } from "../../contracts";
import { APP_INDEX_HREF, NARRATIVE_LINKS, RAW_REPORT_HREF } from "../../publicPaths";
import type { Freshness } from "../evidence/reportModel";
import { formatCutoffTime } from "../evidence/reportModel";
import { PublishedEditionBar } from "./PublishedEditionBar";
import { ReplayBanner } from "./ReplayBanner";
import { SiteFooter } from "./SiteFooter";

export type AppView = "evidence" | "workbench" | "series" | "signal";

function currentNarrativeId(view: AppView): string {
  if (view === "series") {
    return "series";
  }
  if (view === "signal" || view === "workbench") {
    return "signal";
  }
  if (typeof window === "undefined") {
    return "vrp";
  }
  const hash = window.location.hash.replace(/^#/, "");
  if (hash === "framework" || hash === "limitations" || hash === "vrp") {
    return hash;
  }
  return "vrp";
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
  const [activeNarrative, setActiveNarrative] = useState(() => currentNarrativeId(view));

  useEffect(() => {
    const sync = () => {
      setActiveNarrative(currentNarrativeId(view));
    };
    sync();
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
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

        <nav aria-label="五幕叙事" className="spine-views">
          {NARRATIVE_LINKS.map((item) => (
            <a
              aria-current={activeNarrative === item.id ? "page" : undefined}
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
              {refreshing ? "刷新中…" : "刷新"}
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

      {publishedStale ? (
        <main className="published-stop-main" id="surface-main">
          <section className="published-stop-card" role="alert">
            <p className="section-kicker">publication stalled / fail closed</p>
            <h1>发布已停摆</h1>
            <p>
              当前公开版已超过 48 小时时效边界。VRP、DVOL、曲面、候选与历史验证数值均已收起，
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
                {refreshing ? "正在重读" : "重新读取"}
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
