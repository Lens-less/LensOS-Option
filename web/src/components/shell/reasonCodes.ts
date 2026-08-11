import type { ExchangeLockState, ResearchReport } from "../../contracts";

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
export interface ReasonCodeReading {
  /** One line, in the reader's language, of what the code means. */
  title: string;
  /** Why the pipeline stopped here rather than estimating. */
  detail: string;
  /** The command that clears it, when one exists. */
  remedy?: {
    label: string;
    command: string;
  };
}

const HISTORY_REMEDY = {
  label: "抓取标的历史（公开数据，无需凭证）",
  command:
    "crypto-options-underlying-history --currency BTC --days 1200 --output artifacts/history/btc-daily.json",
};

const DVOL_HISTORY_REMEDY = {
  label: "补齐 DVOL 历史（公开数据，无需凭证）",
  command:
    "crypto-options-dvol-history --currency BTC --days 1095 --output artifacts/history/btc-dvol.json",
};

const SNAPSHOT_REMEDY = {
  label: "抓取一份实时公开快照",
  command:
    "crypto-options-report pull-snapshot --currency BTC --instrument-limit 96 --output-dir artifacts/snapshots/btc-series",
};

const REPLAY_REMEDY = {
  label: "以回放模式启动本地引擎（固定评估时钟）",
  command:
    "python -m crypto_options_report.api --replay --snapshot-fixture <快照文件> --underlying-history-fixture artifacts/history/btc-daily.json",
};

export const REASON_CODE_READINGS: Record<string, ReasonCodeReading> = {
  MISSING_VALIDATED_MARKET_DATA: {
    title: "没有可验证的市场快照",
    detail:
      "引擎没有拿到任何通过质量门禁的行情。价格、DVOL、曲面与候选都不会被估算或补齐。",
    remedy: SNAPSHOT_REMEDY,
  },
  MARKET_DATA_QUALITY_FAIL: {
    title: "市场快照未通过质量门禁",
    detail:
      "快照被读到了，但报价质量不达标——常见原因是快照过旧（超过 60 秒）、报价陈旧或买卖价异常。",
    remedy: REPLAY_REMEDY,
  },
  MARKET_DATA_AGE_EXCEEDED: {
    title: "快照超过新鲜度上限",
    detail:
      "录制快照相对当前时钟已经过期。要在浏览器里读取录制数据，需要把评估时钟固定到采集时刻。",
    remedy: REPLAY_REMEDY,
  },
  MISSING_VALIDATED_PATH_RISK: {
    title: "缺少已验证的路径风险证据",
    detail:
      "绝对预期价值需要标的的历史收益分布。没有它，相对价值排序仍会给出，但 EV 一栏会保持为空，而不是用排序分推断。",
    remedy: HISTORY_REMEDY,
  },
  MISSING_DVOL_HISTORY: {
    title: "缺少 DVOL 历史",
    detail:
      "VRP 头条需要 Deribit BTC DVOL 的连续日线历史。缺了这条序列，前端不会把空值显示成 0。",
    remedy: DVOL_HISTORY_REMEDY,
  },
  INSUFFICIENT_VRP_HISTORY: {
    title: "VRP 样本不足",
    detail:
      "VRP 还没有累计到报告声明的最少有效读数。页面保留不可用状态，不展示头条数字。",
    remedy: DVOL_HISTORY_REMEDY,
  },
  PUBLISHED_EDITION_STALE: {
    title: "公开版已超过发布时效上限",
    detail:
      "这份 published 报告已经超过对外展示阈值。页面会保留研究边界与方法说明，但撤下所有当前市场数字。",
  },
  NO_VALIDATED_PATH_RISK: {
    title: "该候选没有路径风险证据",
    detail:
      "这一条的预期价值未被计算：要么标的历史不足以覆盖它的持有期，要么它排在计算配额之外。",
    remedy: HISTORY_REMEDY,
  },
  NO_ELIGIBLE_CANDIDATES: {
    title: "本次快照没有合格候选",
    detail:
      "曲面拟合通过了，但没有合约同时满足 DTE、delta、报价宽度、未平仓量与最低信用的全部门槛。这是正常结果，不是故障。",
  },
  SURFACE_QUALITY_FAIL: {
    title: "波动率曲面未通过质量检查",
    detail:
      "拟合优度或无套利检查未通过。用一条不可信的微笑去算残差，会把拟合误差报告成 edge。",
  },
  CALIBRATION_NOT_IMPLEMENTED: {
    title: "校准与模型提升尚未实现",
    detail:
      "排序分未经过 walk-forward 校准，因此只用于研究内部的相对比较，不是收益预测。这是产品当前的成熟度，不是你的配置问题。",
  },
  BACKTEST_NOT_RUN: {
    title: "尚未运行回测",
    detail: "报告里没有回测产物。这不影响相对价值排序。",
  },
  MISSING_ACCOUNT_API_SNAPSHOT: {
    title: "没有接入只读账户快照",
    detail:
      "账户风险视图需要一份只读的账户 sidecar 数据。研究结论本身不依赖它。",
  },
  SIMULATION_NOT_REQUESTED: {
    title: "未请求账户情景模拟",
    detail: "这是默认状态，不是错误。",
  },
  UNCALIBRATED_SCORE_MODEL: {
    title: "打分模型未校准",
    detail:
      "排序分尚未通过校准复核；它衡量的是同一条链上的相对定价，不是盈利概率。",
  },
  UNBOUNDED_LOSS_STRUCTURE: {
    title: "该结构亏损无上界",
    detail:
      "由候选自身的腿判定：净卖出 call 的结构在上行方向没有保护，因此没有可定义的最大亏损，风险回报比也就无从计算。",
  },
  SUSPECT_PRICE_DIVERGENCE: {
    title: "报价与模型估值严重背离",
    detail:
      "可成交信用远离模型自身的估值。这通常是单位错配或陈旧报价，而不是一个巨大的机会。",
  },
  RESIDUAL_SCALE_UNAVAILABLE: {
    title: "无法计算残差尺度",
    detail:
      "该到期日的报价太少，撑不起拟合的自由度。此时用原始 IV 点数排序，恰好会偏袒最不可信的链条，所以该分量被阻断。",
  },
  INDEX_SPOT_SUBSTITUTED_FOR_FORWARD: {
    title: "用现货指数替代了远期",
    detail:
      "该到期日没有远期报价，改用了现货。这会平移每个行权价的 moneyness，把基差表现成「贵」，因此该分量降级为需留意。",
  },
  MISSING_CANDIDATE_GREEKS: {
    title: "候选缺少希腊值",
    detail:
      "delta 或 vega 缺失。它们是损失分布的输入，代入占位数会让压力成本变成占位数的产物，因此该候选的 EV 不可用。",
  },
  DELTA_OUT_OF_RANGE: {
    title: "delta 不在研究区间内",
    detail: "该行权价的 |delta| 超出 0.03–0.15 的筛选窗口。",
  },
  SPREAD_WIDTH_OUT_OF_RANGE: {
    title: "价差宽度不在区间内",
    detail: "两腿行权价间距超出 5000–15000 的窗口。",
  },
  OPEN_INTEREST_TOO_LOW: {
    title: "未平仓量过低",
    detail: "流动性不足以支撑研究结论。",
  },
  QUOTE_TOO_STALE: {
    title: "报价过旧",
    detail: "该合约的报价时间戳超过了允许的滞后。",
  },
  SPREAD_RATIO_TOO_WIDE: {
    title: "买卖价差过宽",
    detail: "以中价衡量的价差比例超过阈值，可成交性存疑。",
  },
  EVENTS_MISSING: {
    title: "交易所事件源缺失",
    detail:
      "报告没有拿到 Deribit public/status 的交易所锁定状态；缺失不会被解释成 0，事件门保持阻断。",
  },
  EVENTS_FEED_STALE: {
    title: "交易所事件源已过期",
    detail:
      "Deribit public/status 的观察时间超过新鲜度上限；旧的无锁定状态不能继续当作当前证据。",
  },
  EVENTS_FEED_MALFORMED: {
    title: "交易所事件源格式异常",
    detail:
      "Deribit public/status 响应缺少锁定字段或集合，已按不可验证处理，不从异常数据推断状态。",
  },
  EVENT_SOURCE_UNAVAILABLE: {
    title: "交易所事件证据不可用",
    detail:
      "事件来源、范围或新鲜度未同时通过验证；事件门保持阻断，且不会把缺失值显示为 0。",
  },
  EXCHANGE_LOCK_STATE_UNAVAILABLE: {
    title: "交易所锁定状态不可用",
    detail:
      "事件源存在，但报告没有可验证的锁定分；在状态明确前按阻断处理。",
  },
  EXCHANGE_NO_ACTIVE_LOCKS: {
    title: "交易所未报告锁定",
    detail:
      "当次 Deribit public/status 未报告交易所、币种或指数锁定。该源不包含宏观事件日历，不能据此宣称没有宏观事件。",
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
    title: "事件分无法解释为交易所锁定状态",
    detail:
      "事件分不是公开契约允许的 0、0.80 或 1.00；页面拒绝猜测其含义并保持阻断。",
  },
};

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
