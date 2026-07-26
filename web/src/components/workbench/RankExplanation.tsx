import type { DominatedExplanation } from "../../contracts";
import { AXIS_LABELS } from "./candidateModel";
import type { CandidateViewRow } from "./candidateModel";

function axisLabel(axis: string): string {
  return AXIS_LABELS[axis] ?? axis;
}

export function RankExplanation({
  explanation,
  row,
  tieBreakOrder,
}: {
  explanation: DominatedExplanation | null;
  row: CandidateViewRow;
  tieBreakOrder: string[];
}): React.JSX.Element {
  const dominatedBy = explanation?.dominated_by ?? row.dominatedBy;
  const losingAxes = explanation?.losing_axes ?? row.losingAxes;

  return (
    <section className="rank-explanation" aria-label="排序解释">
      <h4>为什么是这个排序</h4>
      {dominatedBy ? (
        <p className="rank-dominated" data-tone="warning">
          该候选被 <code>{dominatedBy}</code> 占优，在以下维度处于劣势：{" "}
          {losingAxes.length > 0
            ? losingAxes.map(axisLabel).join("、")
            : "未提供具体维度"}
          。
        </p>
      ) : (
        <p className="rank-frontier" data-tone="safe">
          该候选目前位于占优前沿：没有其他候选在全部比较维度上同时优于它。
        </p>
      )}
      <div className="rank-tie-break">
        <span>并列时的判定顺序</span>
        {tieBreakOrder.length > 0 ? (
          <ol>
            {tieBreakOrder.map((axis, index) => (
              <li key={axis}>
                <span>{index + 1}</span>
                {axisLabel(axis)}
              </li>
            ))}
          </ol>
        ) : (
          <p>报告未提供并列判定顺序。</p>
        )}
      </div>
    </section>
  );
}
