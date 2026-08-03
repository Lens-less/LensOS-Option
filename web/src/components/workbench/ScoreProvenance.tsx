import type { EvCandidateScanner } from "../../contracts";
import {
  RESEARCH_RANKING_VALUE_LABEL,
  researchRankingValueLabel,
} from "./candidateModel";

const METHOD_LABELS: Record<string, string> = {
  dominance_frontier: "帕累托占优前沿",
  screening_rank_no_path_risk: "无路径风险的筛选排序",
};

export function ScoreProvenance({
  scanner,
}: {
  scanner: EvCandidateScanner | undefined;
}): React.JSX.Element {
  const basis = scanner?.ranking_basis;
  return (
    <section className="score-provenance" aria-label="排序依据与评分口径">
      <div>
        <span>最小可用排序口径</span>
        <strong>{researchRankingValueLabel(scanner?.score_status)}</strong>
        <p>
          这不是混合总分。当前先看前沿位置与是否被占优，再按支配轴顺序细排；
          {RESEARCH_RANKING_VALUE_LABEL} 仅用于研究内部比较，不是收益预测。
        </p>
      </div>
      <div>
        <span>排序方法</span>
        <strong>{METHOD_LABELS[basis?.method ?? ""] ?? basis?.method ?? "未提供"}</strong>
        <p>并列顺序：{(basis?.tie_break_order ?? []).join(" → ") || "未提供"}</p>
      </div>
      <div>
        <span>占优比较范围</span>
        <strong>{basis?.dominance_scope ?? "未提供"}</strong>
        <p>
          绝对 EV 可用性：
          {basis?.absolute_ev_available ? "部分候选已具备" : "尚未提供"}
        </p>
      </div>
    </section>
  );
}
