import { useEffect, useState } from "react";

import type { Freshness } from "./reportModel";

export function Masthead({
  freshness,
  onRefresh,
  refreshing,
  source,
}: {
  freshness?: Freshness;
  onRefresh?: () => void;
  refreshing: boolean;
  source?: string;
}): React.JSX.Element {
  const age =
    freshness?.ageSec === null || freshness?.ageSec === undefined
      ? null
      : `${freshness.ageSec.toLocaleString("zh-CN")} 秒`;
  return (
    <header className="masthead">
      <a className="brand" href="/evidence" aria-label="LensOS 期权研究台首页">
        <span className="brand-mark" aria-hidden="true">
          LO
        </span>
        <span>
          <strong>LensOS Option</strong>
          <small>Research brief</small>
        </span>
      </a>
      <nav className="masthead-actions" aria-label="期权研究台操作">
        {freshness ? (
          <span
            className="source-indicator"
            data-state={freshness.phase}
            aria-label={`市场来源 ${source ?? "未提供"}，数据年龄 ${age ?? "不可用"}`}
          >
            <span aria-hidden="true" />
            {source}
            {age ? ` · ${age}` : ""}
          </span>
        ) : null}
        <span className="read-only-indicator">READ-ONLY</span>
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
            className="refresh-button"
            aria-busy={refreshing}
            disabled={refreshing}
            type="button"
            onClick={onRefresh}
          >
            {refreshing ? "刷新中…" : "刷新数据"}
          </button>
        ) : null}
      </nav>
    </header>
  );
}

const SECTION_LINKS = [
  { id: "brief", label: "市场简报" },
  { id: "framework", label: "策略闭环" },
  { id: "surface", label: "曲面" },
  { id: "candidates", label: "候选" },
  { id: "limitations", label: "边界" },
  { id: "evidence-chain", label: "证据" },
] as const;

type SectionId = (typeof SECTION_LINKS)[number]["id"];

export function SectionNavigation(): React.JSX.Element {
  const [activeSection, setActiveSection] = useState<SectionId>("brief");

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") {
      return;
    }
    const targets = SECTION_LINKS.map(({ id }) =>
      document.getElementById(id),
    ).filter((target): target is HTMLElement => target !== null);
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort(
            (left, right) =>
              Math.abs(left.boundingClientRect.top) -
              Math.abs(right.boundingClientRect.top),
          )[0];
        if (visible) {
          setActiveSection(visible.target.id as SectionId);
        }
      },
      {
        rootMargin: "-118px 0px -62% 0px",
        threshold: [0, 0.25, 0.6],
      },
    );
    targets.forEach((target) => {
      observer.observe(target);
    });
    return () => {
      observer.disconnect();
    };
  }, []);

  return (
    <nav className="section-navigation" aria-label="页面章节">
      {SECTION_LINKS.map(({ id, label }) => (
        <a
          aria-current={activeSection === id ? "location" : undefined}
          href={`#${id}`}
          key={id}
          onClick={() => {
            setActiveSection(id);
          }}
        >
          {label}
        </a>
      ))}
    </nav>
  );
}
