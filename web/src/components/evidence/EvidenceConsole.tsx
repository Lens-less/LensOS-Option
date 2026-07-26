import type { ResearchReport } from "../../contracts";
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

  const body = (
    <>
      <SectionNavigation />
      <main
        className="console"
        id={embedded ? "surface-main" : "evidence-main"}
      >
        <MarketBrief
          candidates={candidates}
          facts={facts}
          freshness={freshness}
          report={report}
        />
        <StrategyFrameworkSection report={report} />
        <SurfaceResearch report={report} />
        <CandidateResearchSection candidates={candidates} report={report} />
        <ReleaseBoundary
          freshness={freshness}
          operatorBlockers={operatorBlockers}
          report={report}
          systemBlockers={systemBlockers}
        />
        <EvidenceChain report={report} />
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
      <footer className="page-footer">
        <span>LensOS Option · research only</span>
        <p>真实市场数据用于研究阅读；页面不连接下单与自动执行。</p>
      </footer>
    </div>
  );
}
