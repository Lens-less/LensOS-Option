import type { ResearchReport, StrategyResearch } from "../contracts";

export const REQUIRED_BLOCKED_OUTPUTS = [
  "trade_recommendation",
  "recommended_size",
  "order_instructions",
  "paper_manual_trade_candidates",
] as const;

const SAFE_RESEARCH_ACTIONS = new Set([
  "RESEARCH_ONLY",
  "RESEARCH_ONLY_NO_TRADE",
  "NO_TRADE",
]);

const REQUIRED_RELEASE_STATUS = "NO-GO";
const REQUIRED_STRATEGY_SCHEMA = "strategy_research.v1";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function fail(message: string): never {
  throw new Error(message);
}

function validateStrategySafety(strategy: StrategyResearch): void {
  if (strategy.schema_version !== REQUIRED_STRATEGY_SCHEMA) {
    fail(`unexpected strategy schema: ${strategy.schema_version}`);
  }

  if (strategy.execution_allowed !== false) {
    fail("strategy research attempted to allow execution");
  }

  const contracts = strategy.playbook?.risk_budget?.contracts;
  if (contracts !== undefined && contracts !== null) {
    fail("strategy research attempted to emit a contract count");
  }
}

export function validateResearchReport(payload: unknown): ResearchReport {
  if (!isRecord(payload)) {
    fail("research report payload must be an object");
  }

  if (payload.schema_version !== "research_report.v1") {
    fail(`unexpected research report schema: ${String(payload.schema_version)}`);
  }

  const report = payload as unknown as ResearchReport;
  const blockedOutputs = new Set(report.blocked_outputs ?? []);
  const gate = report.mode_gate;
  const remainsResearchOnly =
    SAFE_RESEARCH_ACTIONS.has(report.action ?? "") &&
    report.mode === "research_only" &&
    report.effective_mode === "research_only";
  const remainsNoTrade =
    gate?.trade_recommendation_allowed === false &&
    gate.recommended_size_allowed === false &&
    gate.order_instructions_allowed === false &&
    gate.paper_manual_candidates_allowed === false &&
    REQUIRED_BLOCKED_OUTPUTS.every((output) => blockedOutputs.has(output));
  const remainsNoGo =
    report.full_system_surface?.release_readiness?.status ===
    REQUIRED_RELEASE_STATUS;

  if (!remainsResearchOnly || !remainsNoTrade || !remainsNoGo) {
    fail("research report attempted to weaken the safety boundary");
  }

  if (report.strategy_research) {
    validateStrategySafety(report.strategy_research);
  }

  return report;
}
