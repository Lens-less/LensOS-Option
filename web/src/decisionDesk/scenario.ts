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
  return { ...scenario, time_days: Number.isFinite(scenario.time_days)
    ? Math.max(0, Math.min(maximum, Math.floor(scenario.time_days))) : 0 };
}
