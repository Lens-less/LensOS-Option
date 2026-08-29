import type { ResearchReport } from "../../contracts";

/**
 * States that the report on screen is a replay of a recorded snapshot.
 *
 * A replayed report pins server-side evaluation to the snapshot's capture time.
 * Client-side freshness still advances after the response is received so a tab
 * cannot keep trusting the same payload forever. The banner distinguishes those
 * two clocks and is deliberately not dismissible.
 */
export function ReplayBanner({
  report,
}: {
  report: ResearchReport;
}): React.JSX.Element | null {
  const context = report.runtime_context;
  if (!context?.replay) {
    return null;
  }
  const clock = context.evaluation_clock ?? null;
  const isDemo = context.demo_mode === true;
  return (
    <div className="replay-banner" role="status">
      <span className="replay-banner-tag">{isDemo ? "演示 / 快照数据" : "回放"}</span>
      <p>
        {isDemo ? "当前界面显示的是随安装包提供的演示快照。" : "评估时钟已固定在快照采集时刻"}
        {clock ? (
          <>
            {" "}
            <time dateTime={clock}>{clock}</time>
          </>
        ) : null}
        {isDemo
          ? " 它只用于本地只读演示；新鲜度与阻断逻辑仍会继续生效，不会伪装成当前行情。"
          : "；新鲜度从该时刻的报告读数起算，页面载入后继续计时，超限仍会阻断。这不是当前行情。"}
      </p>
      {context.snapshot_fixture ? (
        <code className="replay-banner-source">{context.snapshot_fixture}</code>
      ) : null}
    </div>
  );
}
