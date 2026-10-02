import { PREVIEW_SCENARIOS } from "./preview";
import { DEFAULT_DESK_SCENARIO } from "./types";
import type { DecisionDesk, DeskCandidate, DeskScenario } from "./types";

/** Match the engine's frozen evaluation clock, rather than rounded display DTE. */
export function maximumScenarioDays(desk: DecisionDesk, candidates: readonly DeskCandidate[]): number {
  if (!candidates.length) return 0;
  const remaining = (Math.min(...candidates.map((candidate) => candidate.expiration_timestamp))
    - Date.parse(desk.generated_at)) / 86_400_000;
  return Number.isFinite(remaining) ? Math.max(0, Math.min(365, Math.floor(remaining))) : 0;
}

export function scenarioForSelection(
  desk: DecisionDesk | null, candidates: readonly DeskCandidate[], scenario: DeskScenario,
): DeskScenario {
  const maximum = desk ? maximumScenarioDays(desk, candidates) : 0;
  const supported = PREVIEW_SCENARIOS.some(({value}) => value.price_change_pct === scenario.price_change_pct
    && value.time_days === scenario.time_days && value.iv_shift_points === scenario.iv_shift_points);
  if (!desk || !candidates.length || !supported || scenario.time_days > maximum) return { ...DEFAULT_DESK_SCENARIO };
  return { ...scenario };
}
