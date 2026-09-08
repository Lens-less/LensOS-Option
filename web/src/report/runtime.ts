import type { ResearchReport, StrategyResearch } from "../contracts";
import { validateStrategyBrief } from "./strategyBrief";
import { ResearchReportStructureError, validateReportStructure } from "./structure";

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

export class ResearchReportSafetyError extends Error {
  readonly kind = "safety";
  constructor(message: string) {
    super(message);
    this.name = "ResearchReportSafetyError";
  }
}

function fail(message: string): never {
  throw new ResearchReportSafetyError(message);
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

function validatePublishedSafety(report: ResearchReport): void {
  if (report.runtime_context?.mode !== "published") {
    return;
  }

  const edition = report.publish_edition;
  const capturedAt = Date.parse(edition?.captured_at ?? "");
  const publishedAt = Date.parse(edition?.published_at ?? "");
  const nextExpectedAt = Date.parse(edition?.next_expected_at ?? "");
  const staleAfter = Date.parse(edition?.stale_after ?? "");
  const hasTruthfulClock =
    edition?.cadence === "daily" &&
    report.runtime_context.replay === false &&
    report.runtime_context.evaluation_clock === edition?.captured_at &&
    [capturedAt, publishedAt, nextExpectedAt, staleAfter].every(Number.isFinite) &&
    publishedAt >= capturedAt &&
    nextExpectedAt > capturedAt &&
    staleAfter > nextExpectedAt;
  if (!hasTruthfulClock) {
    fail("published edition is missing its truthful publication clock");
  }

  const gates = new Map(
    (report.full_system_surface?.release_gates ?? []).map((gate) => [
      gate.name,
      gate,
    ]),
  );
  const publicationGate = gates.get("research_publication");
  const executionGate = gates.get("execution_authorization");
  const publicationGateIsCoherent =
    (publicationGate?.status === "GO" && publicationGate.satisfied === true) ||
    (publicationGate?.status === "NO-GO" && publicationGate.satisfied === false);
  if (!publicationGateIsCoherent) {
    fail("published edition is missing publication authorization evidence");
  }
  if (executionGate?.status !== "NO-GO" || executionGate.satisfied !== false) {
    fail("published edition attempted to weaken execution authorization");
  }
}

export function validateResearchReport(payload: unknown): ResearchReport {
  validateReportStructure(payload);
  const report = payload;
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
  if (report.strategy_brief !== undefined && report.strategy_brief !== null) {
    if (typeof report.strategy_brief === "object" && !Array.isArray(report.strategy_brief)) {
      const boundary = report.strategy_brief as Record<string, unknown>;
      if (boundary.research_only === false || boundary.execution_allowed === true) {
        fail("strategy brief attempted to weaken the safety boundary");
      }
    }
    try {
      validateStrategyBrief(report.strategy_brief);
    } catch {
      throw new ResearchReportStructureError("report.strategy_brief");
    }
  }
  validatePublishedSafety(report);

  return report;
}
