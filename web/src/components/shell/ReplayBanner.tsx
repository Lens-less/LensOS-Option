import type { ResearchReport } from "../../contracts";

/**
 * States that the report on screen is a replay of a recorded snapshot.
 *
 * A replayed report pins the evaluation clock to the snapshot's capture time,
 * which makes every freshness figure on the page read as current — the masthead
 * will happily say "Deribit live · 3 seconds" about a chain captured last week.
 * Nothing else on the page can contradict that, so this banner is not decorative
 * and is deliberately not dismissible.
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
        ，页面上的新鲜度指标描述的是那一刻，不是现在。
      </p>
      {context.snapshot_fixture ? (
        <code className="replay-banner-source">{context.snapshot_fixture}</code>
      ) : null}
    </div>
  );
}
