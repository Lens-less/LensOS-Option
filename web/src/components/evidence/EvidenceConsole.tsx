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
import { reportBlockers, reportFreshness } from "./reportModel";
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
          <EvidenceChain report={report} />
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
): StrategyBriefSurfaceState {
  const runtime = report.runtime_context;
  if (!runtime) {
    return {
      freshness_status: "UNAVAILABLE",
      source_kind: "fallback",
      presented_as: "published",
      source_label: "Runtime provenance unavailable",
    };
  }
  const mode = runtime.mode;
  return {
    freshness_status:
      freshness.phase === "current"
        ? "CURRENT"
        : freshness.phase === "unavailable"
          ? "UNAVAILABLE"
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
        ? "Published edition"
        : mode === "replay"
          ? runtime.demo_mode
            ? "Demo snapshot"
            : "Replay snapshot"
          : sourceLabel,
  };
}
