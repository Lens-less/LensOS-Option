import type { ExchangeLockState, ResearchReport } from "../../contracts";
import {
  SHELL_REASON_CODE_READINGS as REASON_CODE_READINGS,
} from "../../reasonCodes/catalog";
import type { ShellReasonCodeReading } from "../../reasonCodes/catalog";

export type ReasonCodeReading = ShellReasonCodeReading;

/**
 * Plain-language readings of the machine reason codes.
 *
 * This product is fail-closed by design, which makes the blocked state the one
 * users see most often — on a first run it is the only state they see. Until
 * now that state's entire explanation was the raw code, so the most-viewed
 * screen in the product was also its least legible one.
 *
 * A code with a `remedy` is one the reader can act on, and the command is the
 * exact one that clears it. A code without a remedy is a property of the
 * product's own maturity, not something the reader did wrong, and says so.
 */
export function readReasonCode(code: string): ReasonCodeReading {
  return (
    REASON_CODE_READINGS[code] ?? {
      title: "未收录的阻断原因",
      detail:
        "这是一个尚未收录人话解释的机器码。机器码仍会原样展示，页面不会静默忽略或自行猜测。",
    }
  );
}

export interface ExchangeEventEvidenceReading {
  blocked: boolean;
  detail: string;
  reasonCode: string;
  scoreLabel: string;
  sourceLabel: string;
  state: ExchangeLockState;
  stateLabel: string;
}

function finiteEventScore(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function resolveExchangeEventEvidence(
  report: ResearchReport,
): ExchangeEventEvidenceReading {
  const explicit = report.event_status;
  const feed = report.data_status?.feed_coverage?.feeds?.events;
  const source =
    explicit?.source ??
    (feed?.source_endpoint === "public/status" ? "deribit_public_status" : null);
  const sourceStatus = explicit?.source_status ?? feed?.status ?? null;
  const scope = explicit?.scope ?? feed?.scope ?? null;
  const freshnessStatus = explicit ? "fresh" : (feed?.freshness_status ?? null);
  const sourceIsCurrent =
    source === "deribit_public_status" &&
    sourceStatus === "available" &&
    scope === "exchange_native_only" &&
    freshnessStatus === "fresh";
  const rawScore =
    explicit?.event_score ??
    report.strategy_research?.analysis?.market?.event_score;
  const eventScore = sourceIsCurrent ? finiteEventScore(rawScore) : null;
  let state: ExchangeLockState = "unknown";
  let reasonCode =
    explicit?.reason_code ?? feed?.reason_code ?? "EVENT_SOURCE_UNAVAILABLE";

  if (sourceIsCurrent && eventScore === 0) {
    state = "normal";
    reasonCode = "EXCHANGE_NO_ACTIVE_LOCKS";
  } else if (sourceIsCurrent && eventScore === 0.8) {
    state = "partial";
    reasonCode = "EXCHANGE_PARTIAL_LOCK";
  } else if (sourceIsCurrent && eventScore === 1) {
    state = "full";
    reasonCode = "EXCHANGE_FULL_LOCK";
  } else if (sourceIsCurrent && eventScore === null) {
    reasonCode = explicit?.reason_code ?? "EXCHANGE_LOCK_STATE_UNAVAILABLE";
  } else if (sourceIsCurrent) {
    reasonCode = "EVENT_SCORE_NOT_EXCHANGE_LOCK_STATE";
  }

  const reading = readReasonCode(reasonCode);
  const stateLabels: Record<ExchangeLockState, string> = {
    unknown: "未知（按阻断处理）",
    normal: "正常（无交易所锁定）",
    partial: "部分锁定（阻断）",
    full: "全局锁定（阻断）",
  };

  return {
    blocked: state !== "normal",
    detail: reading.detail,
    reasonCode,
    scoreLabel:
      state === "unknown" || eventScore === null
        ? "不可用"
        : eventScore.toFixed(2),
    sourceLabel:
      source === "deribit_public_status"
        ? "Deribit public/status（仅交易所锁定状态，不含宏观事件日历）"
        : "事件来源不可验证（宏观日历覆盖也不可验证）",
    state,
    stateLabel: stateLabels[state],
  };
}
