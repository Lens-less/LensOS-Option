import type { ExchangeLockState, ResearchReport } from "../contracts";

interface PublicReasonReading {
  title: string;
  detail: string;
}

const PUBLIC_REASON_READINGS: Record<string, PublicReasonReading> = {
  MISSING_VALIDATED_MARKET_DATA: {
    title: "没有可验证的市场快照",
    detail:
      "公开报告没有通过质量门禁的行情；价格、波动率和候选都不会被估算或补齐。",
  },
  MARKET_DATA_QUALITY_FAIL: {
    title: "市场快照未通过质量门禁",
    detail:
      "公开快照未通过质量门禁；价格、波动率和事件状态不会从失败数据中推断。",
  },
  MARKET_DATA_AGE_EXCEEDED: {
    title: "市场快照已经过期",
    detail: "快照超过报告的新鲜度上限；旧报价不会继续充当当前市场证据。",
  },
  MISSING_VALIDATED_PATH_RISK: {
    title: "缺少已验证的路径风险证据",
    detail:
      "历史路径证据不足；页面不会把相对排序伪装成绝对预期价值。",
  },
  MISSING_DVOL_HISTORY: {
    title: "缺少 DVOL 历史",
    detail: "VRP 需要连续 DVOL 历史；缺失值不会显示成 0。",
  },
  INSUFFICIENT_VRP_HISTORY: {
    title: "VRP 样本不足",
    detail: "VRP 有效读数少于报告声明的最低样本数，头条数字保持不可用。",
  },
  PUBLISHED_EDITION_STALE: {
    title: "公开版已超过发布时效",
    detail:
      "这份公开报告已超过展示时效；当前市场数字与事件状态均按阻断处理。",
  },
  NO_VALIDATED_PATH_RISK: {
    title: "候选缺少路径风险证据",
    detail: "该候选没有足够的持有期历史或未进入计算配额，因此不发布 EV。",
  },
  NO_ELIGIBLE_CANDIDATES: {
    title: "本次没有合格研究候选",
    detail: "没有合约同时满足期限、delta、报价、流动性和信用门槛；这不是故障。",
  },
  SURFACE_QUALITY_FAIL: {
    title: "波动率曲面未通过质量检查",
    detail: "拟合或无套利检查失败；页面不会把拟合误差报告成优势。",
  },
  CALIBRATION_NOT_IMPLEMENTED: {
    title: "校准与模型提升尚未实现",
    detail: "排序尚未经过 walk-forward 校准，只能作为研究观察，不能作为收益预测。",
  },
  BACKTEST_NOT_RUN: {
    title: "尚未运行对齐回测",
    detail: "没有与当前策略对齐的回测产物；策略结论保持阻断。",
  },
  UNCALIBRATED_SCORE_MODEL: {
    title: "打分模型未校准",
    detail: "分数只衡量相对定价，不代表盈利概率。",
  },
  TRUST_EVIDENCE_NOT_OBSERVED: {
    title: "数据可信度尚未形成观测证据",
    detail: "还没有足够的连续采集证据证明数据链稳定，页面保持保守状态。",
  },
  DATA_TRUST_OBSERVATION_COLLECTING: {
    title: "数据可信度仍在积累",
    detail: "连续观测尚未达到提升门槛；不会提前宣称数据源已受信任。",
  },
  REGIME_ROLLING_HISTORY_INSUFFICIENT: {
    title: "市场状态历史不足",
    detail: "滚动历史不足以验证市场状态，权限保持为零。",
  },
  REGIME_TRUST_EVIDENCE_NOT_PROMOTED: {
    title: "市场状态证据尚未提升",
    detail: "状态证据仍是研究级，不能用于放开任何执行权限。",
  },
  REGIME_MIN_OBSERVATIONS_NOT_MET: {
    title: "市场状态观测数不足",
    detail: "有效观测未达到预设下限，结论保持不可用。",
  },
  REGIME_ROLLING_FIELDS_INCOMPLETE: {
    title: "市场状态字段不完整",
    detail: "滚动状态所需字段存在缺口；页面不会用默认值补齐。",
  },
  NO_OPEN_POSITIONS: {
    title: "没有可评估的持仓",
    detail: "公开研究不接入私人持仓；本项只是明确的空状态。",
  },
  EVENTS_MISSING: {
    title: "交易所事件源缺失",
    detail:
      "报告没有拿到 Deribit public/status 的交易所锁定状态；缺失不会被解释成 0。",
  },
  EVENTS_FEED_STALE: {
    title: "交易所事件源已过期",
    detail:
      "Deribit public/status 的观察时间超过新鲜度上限；旧状态不能继续作为当前证据。",
  },
  EVENTS_FEED_MALFORMED: {
    title: "交易所事件源格式异常",
    detail:
      "Deribit public/status 响应格式异常；页面拒绝从异常数据推断锁定状态。",
  },
  EVENT_SOURCE_UNAVAILABLE: {
    title: "交易所事件证据不可用",
    detail:
      "公开事件来源、范围或新鲜度无法验证；事件门保持阻断，缺失值不会显示为 0。",
  },
  EXCHANGE_LOCK_STATE_UNAVAILABLE: {
    title: "交易所锁定状态不可用",
    detail:
      "公开事件源存在，但没有可验证的锁定分；在状态明确前按阻断处理。",
  },
  EXCHANGE_NO_ACTIVE_LOCKS: {
    title: "交易所未报告锁定",
    detail:
      "当次 Deribit public/status 未报告交易所、币种或指数锁定。该源不包含宏观事件日历。",
  },
  EXCHANGE_PARTIAL_LOCK: {
    title: "交易所存在部分锁定",
    detail:
      "Deribit public/status 报告币种或指数锁定；事件分为 0.80，研究门按阻断处理。",
  },
  EXCHANGE_FULL_LOCK: {
    title: "交易所处于全局锁定",
    detail:
      "Deribit public/status 报告全交易所锁定；事件分为 1.00，研究门按阻断处理。",
  },
  EVENT_SCORE_NOT_EXCHANGE_LOCK_STATE: {
    title: "事件分不符合公开契约",
    detail:
      "事件分不是公开契约允许的 0、0.80 或 1.00；页面拒绝猜测其含义并保持阻断。",
  },
};

export function readPublicReasonCode(code: string): PublicReasonReading {
  return (
    PUBLIC_REASON_READINGS[code] ?? {
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
