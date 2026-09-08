import type { ResearchReport } from "../../contracts";
import {
  type StrategyBriefSurfaceState,
  validateStrategyBrief,
} from "../../report/strategyBrief";
import { StrategyBriefView } from "../strategyBrief/StrategyBriefView";
import { MarketBrief } from "./MarketBrief";
import { ReleaseBoundary, EvidenceChain } from "./ReleaseEvidence";
import { Masthead, SectionNavigation } from "./Shell";
import {
  CandidateResearchSection,
  SurfaceResearch,
} from "./SurfaceCandidates";
import { StrategyFrameworkSection } from "./StrategyFramework";
import { marketFacts, researchCandidates } from "./marketModel";
import { marketDisplayState, reportBlockers, reportFreshness } from "./reportModel";
import { VrpOverview } from "./VrpOverview";
import { SiteFooter } from "../shell/SiteFooter";

export { Masthead } from "./Shell";
export { friendlySource, reportFreshness } from "./reportModel";

export interface EvidenceConsoleProps {
  nowMs: number;
  onRefresh?: () => void;
  receivedAtMs: number;
  refreshing?: boolean;
  report: ResearchReport;
  /**
   * Rendered inside `AppShell`, which already carries the masthead, the replay
   * banner and the run boundary. Standalone mounts (tests, embeds) keep the
   * self-contained chrome.
   */
  embedded?: boolean;
}

export function EvidenceConsole({
  report,
  receivedAtMs,
  nowMs,
  onRefresh,
  refreshing = false,
  embedded = false,
}: EvidenceConsoleProps): React.JSX.Element {
  const blockers = reportBlockers(report);
  const operatorBlockers = blockers.filter(
    (blocker) => blocker.queue === "operator",
  );
  const systemBlockers = blockers.filter(
    (blocker) => blocker.queue === "system",
  );
  const freshness = reportFreshness(report, receivedAtMs, nowMs);
  const facts = marketFacts(report);
  const candidates = researchCandidates(report);
  const strategyBrief = loadStrategyBrief(report);
  const strategyBriefSurface = strategyBriefSurfaceState(
    report,
    freshness,
    facts.source,
    receivedAtMs,
    nowMs,
  );

  const body = (
    <>
      {embedded ? null : <SectionNavigation />}
      <main
        className="console"
        id={embedded ? "surface-main" : "evidence-main"}
      >
        <StrategyBriefView
          brief={strategyBrief}
          surface={strategyBriefSurface}
        />
        <details className="strategy-brief-details">
          <summary>查看依据</summary>
          <VrpOverview freshness={freshness} report={report} />
          <MarketBrief
            candidates={candidates}
            facts={facts}
            freshness={freshness}
            report={report}
          />
          <StrategyFrameworkSection freshness={freshness} report={report} />
          <SurfaceResearch freshness={freshness} report={report} />
          <CandidateResearchSection
            candidates={candidates}
            freshness={freshness}
            report={report}
          />
          <ReleaseBoundary
            freshness={freshness}
            operatorBlockers={operatorBlockers}
            report={report}
            systemBlockers={systemBlockers}
          />
          <EvidenceChain freshness={freshness} report={report} />
        </details>
      </main>
    </>
  );

  if (embedded) {
    return body;
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#evidence-main">
        跳到主要内容
      </a>
      <Masthead
        freshness={freshness}
        onRefresh={onRefresh}
        refreshing={refreshing}
        source={facts.source}
      />
      {body}
      <SiteFooter />
    </div>
  );
}

function loadStrategyBrief(report: ResearchReport) {
  try {
    return report.strategy_brief
      ? validateStrategyBrief(report.strategy_brief)
      : null;
  } catch {
    return null;
  }
}

function strategyBriefSurfaceState(
  report: ResearchReport,
  freshness: ReturnType<typeof reportFreshness>,
  sourceLabel: string,
  receivedAtMs: number,
  nowMs: number,
): StrategyBriefSurfaceState {
  const runtime = report.runtime_context;
  if (!runtime) {
    return {
      freshness_status: "UNAVAILABLE",
      source_kind: "fallback",
      presented_as: "published",
      source_label: "运行来源不可验证",
      now_ms: nowMs,
    };
  }
  const mode = runtime.mode;
  const evaluationMs = Date.parse(runtime.evaluation_clock ?? "");
  const viewClock = mode === "replay" && Number.isFinite(evaluationMs)
    ? evaluationMs + Math.max(0, nowMs - receivedAtMs)
    : nowMs;
  return {
    now_ms: viewClock,
    freshness_status:
      marketDisplayState(report, freshness) === "quality_blocked"
        ? "UNAVAILABLE"
        : freshness.phase === "current"
          ? "CURRENT"
          : "STALE",
    source_kind:
      mode === "published"
        ? "published"
        : mode === "replay"
          ? "replay"
          : runtime.demo_mode
            ? "demo"
            : "live",
    presented_as:
      mode === "published"
        ? "published"
        : mode === "replay"
          ? "replay"
          : "live",
    source_label:
      mode === "published"
        ? "公开快照"
        : mode === "replay"
          ? runtime.demo_mode
            ? "演示快照"
            : "历史回放快照"
          : sourceLabel,
  };
}
