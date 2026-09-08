import { APP_INDEX_HREF } from "../../publicPaths";
import { ResearchErrorBoundary } from "../shell/ResearchErrorBoundary";
import { SiteFooter } from "../shell/SiteFooter";
import { DemoGuide } from "./DemoGuide";

/** Learning is available without a report, a demo runtime, or a network request. */
export function LearningApp(): React.JSX.Element {
  return (
    <div className="app-shell learning-app-shell">
      <a className="skip-link" href="#surface-main">跳到主要内容</a>
      <header className="learning-masthead">
        <a className="brand" href={APP_INDEX_HREF} aria-label="LensOS 期权研究台首页">
          <span className="brand-mark" aria-hidden="true">LO</span>
          <span><strong>LensOS Option</strong><small>期权决策研究</small></span>
        </a>
        <a className="text-link" href={APP_INDEX_HREF}>返回研究简报</a>
      </header>
      <p className="spine-learning-boundary" role="note">
        <strong>离线教学</strong><span>仅研究 · NO_TRADE</span>
      </p>
      <ResearchErrorBoundary label="离线教学导览">
        <DemoGuide />
      </ResearchErrorBoundary>
      <SiteFooter />
    </div>
  );
}
