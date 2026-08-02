import type { ResearchReport } from "../../contracts";
import {
  formatCutoffTime,
  formatPublishedAge,
  marketDisplayState,
} from "../evidence/reportModel";
import type { Freshness } from "../evidence/reportModel";

export function PublishedEditionBar({
  freshness,
  report,
}: {
  freshness: Freshness;
  report: ResearchReport;
}): React.JSX.Element | null {
  if (report.runtime_context?.mode !== "published") {
    return null;
  }

  const cutoff = report.publish_edition?.captured_at ?? report.generated_at ?? null;
  const state = marketDisplayState(report, freshness);

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
