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
      <details className="learning-current-start">
        <summary>用当前公开行情开始研究</summary>
        <p>若需要切换到当前公开行情，在终端按 Ctrl+C 结束现有服务，再运行下面一条命令。已经以当前模式启动时，直接返回研究简报即可。无需账户或密钥。</p>
        <code>crypto-options-report start --current</code>
        <p>数据与证据不足时会给出拒绝原因；有效快照会复用，过期后重新采集。研究结果最高为观察，不会提交订单。</p>
      </details>
      <SiteFooter />
    </div>
  );
}
