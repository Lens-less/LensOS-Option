import fixtures from './preview-fixtures.json';
import { validateDecisionDesk, validateDeskComparison, validateDeskReview } from './client';
import type { DecisionDesk, DeskAsset, DeskCriteria, DeskMode, DeskScenario, DeskReview } from './types';

// A frozen, explicitly synthetic replay. Never make a network request or price a structure here.
export const PREVIEW_CLOCK = fixtures.clock;
export const previewNow = (): number => Date.parse(PREVIEW_CLOCK);
export const PREVIEW_SCENARIOS = fixtures.scenarios;
export const previewCandidateIds = (asset: DeskAsset): readonly string[] => fixtures.assets[asset].selected_ids;
const copy = <T,>(value: T): T => structuredClone(value);
const sameScenario = (left: DeskScenario, right: DeskScenario): boolean =>
  left.price_change_pct === right.price_change_pct && left.time_days === right.time_days && left.iv_shift_points === right.iv_shift_points;

export async function discoverDesk(asset: DeskAsset, criteria: DeskCriteria, mode: DeskMode): Promise<DecisionDesk> {
  if (mode !== 'demo') throw new Error('此云端预览未运行实时行情后端。');
  const desk = validateDecisionDesk(copy(fixtures.assets[asset].desk));
  if (Object.entries(criteria).some(([key, value]) => desk.criteria[key as keyof DeskCriteria] !== value)) {
    throw new Error('此预览仅支持固定筛选样例。');
  }
  return desk;
}

export async function compareDesk(snapshotId: string, candidateIds: string[], scenario: DeskScenario, analysisId: string) {
  const fixture = Object.values(fixtures.assets).find((asset) => asset.desk.snapshot_id === snapshotId && asset.desk.analysis_id === analysisId);
  if (!fixture || new Set(candidateIds).size !== candidateIds.length || candidateIds.length < 2 || candidateIds.length > 3) throw new Error('预计算样例身份不匹配。');
  const match = fixture.comparisons.find((comparison) => sameScenario(comparison.scenario, scenario)
    && comparison.members.length === candidateIds.length && comparison.members.every((member) => candidateIds.includes(member.candidate_id)));
  if (!match) throw new Error('该组合或情景不在预计算样例中。');
  return validateDeskComparison(copy(match));
}

export async function reviewObservation(record: { desk: DecisionDesk; candidate_id: string }): Promise<DeskReview> {
  validateDecisionDesk(record.desk);
  if (!record.desk.candidates.some((candidate) => candidate.candidate_id === record.candidate_id)) throw new Error('原始选腿不匹配。');
  return validateDeskReview({
    schema_version: 'desk_review.v1', reviewed_at: new Date().toISOString(),
    original_snapshot_id: record.desk.snapshot_id, original_candidate_id: record.candidate_id,
    reviewed_candidate_id: null, status: 'unavailable', desk: null,
    reasons: [{code: 'CLOUD_PREVIEW_NO_LIVE_BACKEND', detail: '此页面只有固定合成回放，没有实时行情或 Python 后端；不能取得同一合约的新报价。原记录保留不变。'}],
  });
}
