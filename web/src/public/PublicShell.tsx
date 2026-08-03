import { useEffect, useState } from "react";

import type { ResearchReport } from "../contracts";
import {
  APP_INDEX_HREF,
  FOOTER_LINKS,
  RAW_REPORT_HREF,
} from "../publicPaths";
import {
  formatCutoffTime,
  formatDurationHours,
  formatPublishedAge,
  type PublicFreshness,
  type PublicView,
} from "./publicModel";
import { friendlySource, publicMarketDisplayState } from "./publicModel";

const FIVE_ACT_LINKS = [
  { href: `${APP_INDEX_HREF}#vrp`, id: "vrp", label: "现在贵不贵" },
  { href: `${APP_INDEX_HREF}#surface`, id: "surface", label: "曲面贵在哪里" },
  { href: `${APP_INDEX_HREF}#framework`, id: "framework", label: "卖它值不值" },
  { href: `${APP_INDEX_HREF}#signal`, id: "signal", label: "这套排序灵不灵" },
  { href: `${APP_INDEX_HREF}#limitations`, id: "limitations", label: "凭什么信" },
] as const;

function currentNarrativeId(view: PublicView): string {
  if (view === "series") {
    return "series";
  }
  if (view === "signal") {
    return "signal";
  }
  if (typeof window === "undefined") {
    return "vrp";
  }
  const hash = window.location.hash.replace(/^#/, "");
  if (
    hash === "framework" ||
    hash === "limitations" ||
    hash === "signal" ||
    hash === "surface" ||
    hash === "vrp"
  ) {
    return hash;
  }
  return "vrp";
}

function ReplayBanner({
  report,
}: {
  report: ResearchReport;
}): React.JSX.Element | null {
  const context = report.runtime_context;
  if (!context?.replay) {
    return null;
  }
  const clock = context.evaluation_clock ?? null;
  return (
    <div className="replay-banner" role="status">
      <span className="replay-banner-tag">回放</span>
      <p>
        评估时钟已固定在快照采集时刻
        {clock ? (
          <>
            {" "}
            <time dateTime={clock}>{clock}</time>
          </>
        ) : null}
        ，页面上的新鲜度描述的是那一刻，不是现在。
      </p>
    </div>
  );
}

function PublishedEditionBar({
  freshness,
  report,
}: {
  freshness: PublicFreshness;
  report: ResearchReport;
}): React.JSX.Element | null {
  if (report.runtime_context?.mode !== "published") {
    return null;
  }

  const cutoff = report.publish_edition?.captured_at ?? report.generated_at ?? null;
  const state = publicMarketDisplayState(report, freshness);

  return (
    <div
      className="published-edition-bar"
      data-state={state === "stale" ? "stale" : freshness.phase}
      role="status"
    >
      <span className="published-edition-tag">公开版</span>
      <p>
        数据截止 <time dateTime={cutoff ?? undefined}>{formatCutoffTime(cutoff)}</time>
        {" · "}
        {formatPublishedAge(freshness.ageSec)}
      </p>
      {state === "stale" ? (
        <strong>发布已停摆</strong>
      ) : report.publish_edition?.next_expected_at ? (
        <small>
          下次预期发布时间{" "}
          <time dateTime={report.publish_edition.next_expected_at}>
            {formatCutoffTime(report.publish_edition.next_expected_at)}
          </time>
        </small>
      ) : null}
    </div>
  );
}

export function PublicShell({
  children,
  freshness,
  onRefresh,
  refreshing,
  report,
  view,
}: {
  children: React.ReactNode;
  freshness: PublicFreshness;
  onRefresh: () => void;
  refreshing: boolean;
  report: ResearchReport;
  view: PublicView;
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
    freshness.ageSec === null || freshness.mode === "published"
      ? null
      : formatPublishedAge(freshness.ageSec);
  const source = friendlySource(report.data_status?.source);
  const cutoff = report.publish_edition?.captured_at ?? report.generated_at ?? null;
  const publishedStale =
    report.runtime_context?.mode === "published" && freshness.phase === "expired";

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
          {FIVE_ACT_LINKS.map((item) => (
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
          <span
            className="source-indicator"
            data-state={freshness.phase}
            aria-label={`市场来源 ${source}，数据年龄${age ?? "由公开版时效条展示"}`}
          >
            <span aria-hidden="true" />
            {source}
            {age ? ` · ${age}` : ""}
          </span>
          <a
            className="text-link"
            href={RAW_REPORT_HREF}
            rel="noreferrer"
            target="_blank"
          >
            原始 JSON
          </a>
          <button
            aria-busy={refreshing}
            className="refresh-button"
            disabled={refreshing}
            onClick={onRefresh}
            type="button"
          >
            {refreshing ? "正在重新读取静态快照" : "重新读取静态快照"}
          </button>
        </div>
      </header>

      <PublishedEditionBar freshness={freshness} report={report} />
      <ReplayBanner report={report} />

      <div className="spine-boundary" role="note">
        <dl>
          <div data-tone="danger">
            <dt>运行边界</dt>
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
              当前公开版已超过 {formatDurationHours(freshness.maxAgeSec)}时效边界。
              VRP、DVOL、曲面、候选与历史验证数值均已收起，
              直到下一版通过数据质量门禁并完成发布。
            </p>
            <button
              aria-busy={refreshing}
              className="refresh-button"
              disabled={refreshing}
              onClick={onRefresh}
              type="button"
            >
              {refreshing ? "正在重新读取静态快照" : "重新读取静态快照"}
            </button>
          </section>
        </main>
      ) : (
        children
      )}

      <footer className="page-footer">
        <div className="page-footer-copy">
          <span>LensOS Option · research only</span>
          <p>公开站仅供研究与信息用途。页面不连接下单、自动动作或内部控制层。</p>
        </div>
        <nav aria-label="页脚链接" className="page-footer-links">
          <a href={`${APP_INDEX_HREF}?view=series`}>历史残差验证</a>
          {FOOTER_LINKS.map((link) => (
            <a href={link.href} key={link.href}>
              {link.label}
            </a>
          ))}
        </nav>
      </footer>
    </div>
  );
}
