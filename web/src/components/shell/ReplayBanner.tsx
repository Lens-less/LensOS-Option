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
        ；新鲜度从该时刻的报告读数起算，页面载入后继续计时，超限仍会阻断。这不是当前行情。
      </p>
      {context.snapshot_fixture ? (
        <code className="replay-banner-source">{context.snapshot_fixture}</code>
      ) : null}
    </div>
  );
}
