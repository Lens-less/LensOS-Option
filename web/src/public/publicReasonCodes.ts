import type { ExchangeLockState, ResearchReport } from "../contracts";
import {
  PUBLIC_REASON_CODE_READINGS,
} from "./publicReasonCodes.generated";
import type { PublicReasonCodeReading } from "./publicReasonCodes.generated";

export function readPublicReasonCode(code: string): PublicReasonCodeReading {
  return (
    PUBLIC_REASON_CODE_READINGS[code] ?? {
      title: "未收录的阻断原因",
      detail:
        "这是尚未收录公开解释的阻断原因。机器码仍会原样展示，页面不静默忽略或自行猜测。",
    }
  );
}

export interface PublicExchangeEventEvidenceReading {
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

/** Resolve only the publisher's sanitized event projection.
 *
 * Keep this module physically separate from the internal reason registry: the
 * public bundle must never import account, execution, or private feed fields.
 */
export function resolvePublicExchangeEventEvidence(
  report: ResearchReport,
): PublicExchangeEventEvidenceReading {
  const event = report.event_status;
  const sourceIsCurrent =
    event?.source === "deribit_public_status" &&
    event.source_status === "available" &&
    event.scope === "exchange_native_only";
  const eventScore = sourceIsCurrent
    ? finiteEventScore(event.event_score)
    : null;
  let state: ExchangeLockState = "unknown";
  let reasonCode = event?.reason_code ?? "EVENT_SOURCE_UNAVAILABLE";

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
    reasonCode = event?.reason_code ?? "EXCHANGE_LOCK_STATE_UNAVAILABLE";
  } else if (sourceIsCurrent) {
    reasonCode = "EVENT_SCORE_NOT_EXCHANGE_LOCK_STATE";
  }

  const stateLabels: Record<ExchangeLockState, string> = {
    unknown: "未知（按阻断处理）",
    normal: "正常（无交易所锁定）",
    partial: "部分锁定（阻断）",
    full: "全局锁定（阻断）",
  };

  return {
    blocked: state !== "normal",
    detail: readPublicReasonCode(reasonCode).detail,
    reasonCode,
    scoreLabel:
      state === "unknown" || eventScore === null
        ? "不可用"
        : eventScore.toFixed(2),
    sourceLabel:
      event?.source === "deribit_public_status"
        ? "Deribit public/status（仅交易所锁定状态，不含宏观事件日历）"
        : "事件来源不可验证（宏观日历覆盖也不可验证）",
    state,
    stateLabel: stateLabels[state],
  };
}
