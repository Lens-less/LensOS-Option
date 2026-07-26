import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App, EvidenceConsole } from "./App";
import type { ResearchReport } from "./contracts";
import evidenceStyles from "./styles.css?raw";
import type { LoadedReport } from "./transport";

const blockedReport: ResearchReport = {
  schema_version: "research_report.v1",
  generated_at: "2026-07-24T08:00:00Z",
  action: "RESEARCH_ONLY",
  mode: "research_only",
  effective_mode: "research_only",
  risk_state: "HALT",
  reason_codes: [
    "MISSING_VALIDATED_MARKET_DATA",
    "MISSING_ACCOUNT_API_SNAPSHOT",
    "BACKTEST_NOT_RUN",
  ],
  blocked_outputs: [
    "trade_recommendation",
    "recommended_size",
    "order_instructions",
    "paper_manual_trade_candidates",
  ],
  data_trust: {
    verdict: "untrusted",
    source_class: "missing",
    reason_codes: ["MISSING_VALIDATED_MARKET_DATA"],
  },
  data_status: {
    status: "missing",
    source: "not_configured",
    validated: false,
    reason_code: "MISSING_VALIDATED_MARKET_DATA",
  },
  account_status: {
    status: "missing",
    source: "not_configured",
    margin_light: "HALT",
    trade_gate: "NO_TRADE",
    reason_code: "MISSING_ACCOUNT_API_SNAPSHOT",
  },
  mode_gate: {
    trade_recommendation_allowed: false,
    recommended_size_allowed: false,
    order_instructions_allowed: false,
    paper_manual_candidates_allowed: false,
    reason_codes: [
      "MISSING_VALIDATED_MARKET_DATA",
      "MISSING_ACCOUNT_API_SNAPSHOT",
      "BACKTEST_NOT_RUN",
    ],
  },
  backtest_status: {
    status: "not_run",
    reason_code: "BACKTEST_NOT_RUN",
  },
  full_system_surface: {
    release_readiness: {
      status: "NO-GO",
      prerequisites: [
        {
          name: "external_release_authorization",
          satisfied: false,
          owner: "external_operator",
          action: "Obtain separately authorized manual/external release evidence.",
          reason_codes: ["EXTERNAL_RELEASE_AUTHORIZATION_REQUIRED"],
        },
      ],
    },
  },
};

function loadedReport(
  report: ResearchReport = blockedReport,
  receivedAtMs = Date.parse("2026-07-24T08:00:00Z"),
): LoadedReport {
  return {
    report,
    receivedAtMs,
    cached: false,
  };
}

const strategyResearchFixture: NonNullable<
  ResearchReport["strategy_research"]
> = {
  schema_version: "strategy_research.v1",
  generated_at: "2026-07-24T10:25:00Z",
  status: "partial",
  advisory_only: true,
  execution_allowed: false,
  confidence_ceiling: "screening_only",
  pipeline: [
    { stage: "COLLECT", status: "ready" },
    { stage: "ANALYZE", status: "ready" },
    { stage: "SELECT", status: "ready" },
    { stage: "ENTER", status: "blocked" },
    { stage: "RISK", status: "partial" },
    { stage: "EXIT", status: "partial" },
    { stage: "MONITOR", status: "ready" },
    { stage: "REVIEW", status: "blocked" },
  ],
  decision: {
    stance: "MONITOR_ONLY",
    primary_structure: "CALL_CREDIT_SPREAD",
    entry_readiness: "BLOCKED",
    summary:
      "A defined-risk call credit spread is the primary screening setup; activation gates remain closed.",
    why_now: [
      "20/20 sampled quotes pass the market-data gate.",
      "5 defined-risk call credit spreads pass observable screening.",
    ],
    why_not: [
      "Regime evidence has not been promoted.",
      "A fresh read-only account snapshot is unavailable.",
      "Validated path-risk and EV ranking are unavailable.",
    ],
    rejected_structures: [
      {
        structure: "NAKED_SHORT_CALL",
        status: "rejected_for_current_research_plan",
        reason_codes: [
          "UNBOUNDED_TAIL_LOSS",
          "NAKED_PERMISSION_FALSE",
        ],
      },
    ],
  },
  collection: {
    status: "validated",
    source: "deribit_live:https://www.deribit.com",
    market_data_age_sec: 4,
    coverage: {
      scope: "research_sample",
      selected_instrument_count: 20,
      upstream_instrument_count: 864,
      coverage_ratio: 0.0231,
      is_research_sample: true,
    },
    quality: {
      valid_quotes: 20,
      total_quotes: 20,
      invalid_quotes: 0,
      fetch_errors: 0,
      expiries_evaluated: 2,
    },
    feed_graph: {
      complete: true,
      missing_required_feeds: [],
    },
  },
  analysis: {
    market: {
      spot_usd: 65_058.13,
      dvol_percent: 37.66,
      near_term_atm_iv_percent: 34.13,
      dvol_minus_atm_iv_points: 3.53,
      funding_rate: 0.00000021,
      basis_rate: 0.000256,
      event_score: 0,
      regime_label: "Collecting",
      regime_status: "blocked",
      sell_permission: 0,
      spread_permission: false,
      naked_permission: false,
    },
    volatility: {
      surface_status: "validated",
      term_slope_iv_points: -0.8,
      candidate_expiry_atm_iv_percent: 35.1,
      expected_move_usd: 4_512,
      expected_move_percent: 6.94,
      call_wing_richness_iv_points: 1.9,
      front_expiry: {
        expiry_date: "2026-07-31",
        dte_days: 6.9,
        atm_fitted_iv_percent: 34.3,
        fit_quality_score: 0.9855,
        no_arbitrage_pass: true,
        candidate_eligible: false,
      },
      next_expiry: {
        expiry_date: "2026-08-07",
        dte_days: 13.9,
        atm_fitted_iv_percent: 35.1,
        fit_quality_score: 0.9687,
        no_arbitrage_pass: true,
        candidate_eligible: true,
      },
    },
  },
  strategy_selection: {
    selection_method: "screening_rank_no_path_risk",
    eligible_spread_count: 5,
    ranked_candidate_ids: [
      "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
    ],
  },
  playbook: {
    playbook_id: "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
    structure: "CALL_CREDIT_SPREAD",
    candidate: {
      candidate_id: "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
      expiry_date: "2026-08-07",
      dte_days: 13.9,
      sell_leg: "BTC-7AUG26-71000-C",
      buy_leg: "BTC-7AUG26-77000-C",
      sell_strike_usd: 71_000,
      buy_strike_usd: 77_000,
      model_delta: 0.087,
      risk_neutral_p_itm: 0.106,
      surface_fit_quality: 0.9687,
    },
    economics: {
      premium_currency: "BTC",
      credit_coin: 0.0025,
      credit_usd_shadow: 162.65,
      spread_width_usd: 6_000,
      reference_max_loss_usd_shadow: 5_842.42,
      estimated_total_fees_usd_shadow: 5.07,
      breakeven_usd_shadow: 71_162.65,
      sell_strike_distance_usd: 5_941.87,
      sell_strike_distance_percent: 9.13,
      sell_strike_expected_move_multiple: 1.32,
      credit_to_max_loss_ratio: 0.0278,
    },
    entry_contract: {
      status: "blocked",
      revalidate_on_refresh: true,
      price_basis: "sell_bid_minus_buy_ask",
      execution_assumption: "post_only_limit_research_assumption",
      conditions: [
        {
          id: "market_quality",
          label: "Market snapshot passes the quality gate",
          observed: "validated",
          requirement: "validated",
          status: "pass",
          blocking: true,
        },
        {
          id: "market_freshness",
          label: "Market snapshot remains inside its freshness limit",
          observed: 4,
          requirement: "<= 60 sec",
          status: "pass",
          blocking: true,
        },
        {
          id: "candidate_eligibility",
          label: "Candidate remains eligible after refresh",
          observed: "eligible",
          requirement: "eligible",
          status: "pass",
          blocking: true,
        },
        {
          id: "surface_fit",
          label: "Surface fit quality remains at or above 0.90",
          observed: 0.9687,
          requirement: ">= 0.90",
          status: "pass",
          blocking: true,
        },
        {
          id: "regime_permission",
          label: "Promoted regime evidence permits credit spreads",
          observed: { status: "blocked", spread_permission: false },
          requirement: "validated and true",
          status: "block",
          blocking: true,
        },
        {
          id: "account_gate",
          label: "Read-only account snapshot allows new risk",
          observed: "NO_TRADE",
          requirement: "ALLOW_NEW",
          status: "block",
          blocking: true,
        },
        {
          id: "cost_coverage",
          label: "Net premium remains above five times fees and slippage",
          requirement: "net premium > 5x total expected costs",
          status: "unknown",
          blocking: true,
        },
        {
          id: "calibrated_path_risk",
          label: "Validated path-risk and calibration evidence is promoted",
          observed: "unavailable",
          requirement: "calibrated",
          status: "block",
          blocking: true,
        },
      ],
    },
    risk_budget: {
      max_single_spread_loss_nav: 0.015,
      max_single_naked_stress_loss_nav: 0.0075,
      max_new_margin_nav: 0.08,
      max_net_delta_nav: 0.08,
      max_depth_fraction: 0.1,
      inverse_position_size_multiplier: 0.7,
      sizing_status: "account_input_missing",
      contracts: null,
      formula:
        "floor((NAV * max_single_spread_loss_nav) / reference_max_loss_usd_shadow), then apply caps",
      portfolio_final_action: "halt_system",
      note: "No contract count is emitted in research-only mode.",
    },
    exit_contract: {
      policy_status: "template_only_uncalibrated",
      profit_capture: [
        {
          trigger: "premium_capture >= 60%",
          response: "close_50_percent",
          validated: false,
        },
        {
          trigger: "premium_capture >= 80%",
          response: "close_all",
          validated: false,
        },
        {
          trigger: "remaining_premium < 3_to_5x_expected_close_cost",
          response: "close_early",
          validated: false,
        },
        {
          trigger: "short_call_delta < 0.03",
          response: "close_and_rescan",
          validated: false,
        },
      ],
      position_states: [
        {
          state: "NORMAL",
          delta_condition: "delta <= 0.20",
          loss_condition: "loss < 1.0x entry credit",
          response: "hold_or_take_profit",
        },
        {
          state: "CAUTION",
          delta_condition: "0.20 < delta <= 0.25",
          loss_condition: "1.0x <= loss < 2.0x entry credit",
          response: "no_additions_and_review",
        },
        {
          state: "DEFENSE",
          delta_condition: "0.25 < delta <= 0.35",
          loss_condition: "2.0x <= loss <= 3.0x entry credit",
          response: "reduce_or_add_defined_risk_protection",
        },
        {
          state: "EXIT_REQUIRED",
          delta_condition: "0.35 < delta <= 0.40",
          loss_condition: "loss > 3.0x entry credit",
          response: "close",
        },
        {
          state: "FORCE_CLOSE",
          delta_condition: "delta > 0.40 or breakout kill",
          loss_condition: "portfolio close signal",
          response: "close_and_pause",
        },
      ],
      time_management: {
        review_below_dte_days: 7,
        roll_allowed_states: ["NORMAL", "CAUTION"],
        roll_delta_band: [0.05, 0.2],
        roll_must_improve: ["expected_value", "p_touch", "total_stress_loss"],
        defensive_roll_minimum_stress_reduction: 0.3,
        loss_deferral_alone_is_forbidden: true,
      },
      kill_switches: [
        "breakout score > 0.70",
        "event score > 0.75",
        "market data age > 60 sec",
      ],
    },
  },
  monitoring: [
    {
      metric: "market_age_sec",
      current: 4,
      trigger: "> 60 sec",
      response: "pause_research_setup",
    },
    {
      metric: "surface_fit_quality",
      current: 0.9687,
      trigger: "< 0.9",
      response: "remove_candidate",
    },
    {
      metric: "candidate_delta",
      current: 0.087,
      trigger: "> 0.20 after entry",
      response: "move_to_caution",
    },
    {
      metric: "event_score",
      current: 0,
      trigger: "> 0.75",
      response: "kill_new_entry",
    },
  ],
  review: {
    status: "blocked",
    backtest_status: "not_run",
    calibration_status: "unavailable",
    path_risk_status: "unavailable",
    missing_evidence: [
      "MISSING_ACCOUNT_API_SNAPSHOT",
      "CALIBRATION_NOT_IMPLEMENTED",
      "BACKTEST_NOT_RUN",
      "MISSING_VALIDATED_PATH_RISK",
    ],
    promotion_conditions: [
      "Persist enough rolling observations to promote regime evidence.",
      "Run an aligned bounded backtest on licensed historical data.",
      "Promote walk-forward calibration and validated path-risk outputs.",
      "Reconcile paper observations, fees, slippage, and forced-exit behavior.",
    ],
  },
};

const liveResearchReport = {
  ...blockedReport,
  generated_at: "2026-07-24T10:25:00Z",
  reason_codes: [
    "MISSING_ACCOUNT_API_SNAPSHOT",
    "BACKTEST_NOT_RUN",
  ],
  data_trust: {
    verdict: "trusted",
    source_class: "validated",
    reason_codes: [],
  },
  data_status: {
    status: "validated",
    source: "deribit_live:https://www.deribit.com",
    validated: true,
    market_data_age_sec: 4,
    quality_gate: {
      passed: true,
      summary: {
        total_quotes: 20,
        valid_quotes: 20,
        expiries_evaluated: 2,
      },
      thresholds: {
        market_data_max_age_sec: 60,
      },
    },
    public_response_contract: {
      endpoints: {
        vol_index: {
          status: "available",
          volatility: 0.3766,
          index_name: "BTC DVOL",
        },
      },
    },
  },
  vol_surface_status: {
    status: "validated",
    validated: true,
    summary: {
      eligible_expiries: 1,
      expiries_evaluated: 2,
      quality_passing_quotes: 20,
    },
    expiries: [
      {
        expiry_date: "2026-07-31",
        dte_days: 6.9,
        candidate_eligible: false,
        fit_quality_pass: true,
        fit_quality_score: 0.9855,
        no_arb_pass: false,
        no_arb_error: 0.075,
        reason_codes: ["SURFACE_NO_ARBITRAGE_FAIL"],
        surface_points: [
          {
            strike_price: 66_000,
            surface_fitted_iv: 34.03,
            market_mark_iv: 34.33,
            underlying_price: 65_058.13,
          },
          {
            strike_price: 72_000,
            surface_fitted_iv: 38.1,
            market_mark_iv: 37.81,
            underlying_price: 65_058.13,
          },
        ],
      },
      {
        expiry_date: "2026-08-07",
        dte_days: 13.9,
        candidate_eligible: true,
        fit_quality_pass: true,
        fit_quality_score: 0.9687,
        no_arb_pass: true,
        no_arb_error: 0,
        reason_codes: [],
        surface_points: [
          {
            strike_price: 71_000,
            surface_fitted_iv: 37,
            market_mark_iv: 36.58,
            underlying_price: 65_058.13,
          },
          {
            strike_price: 80_000,
            surface_fitted_iv: 52.27,
            market_mark_iv: 51.62,
            underlying_price: 65_058.13,
          },
        ],
      },
    ],
  },
  candidate_research: {
    status: "validated",
    summary: {
      eligible_call_credit_spreads: 5,
      eligible_expiries: 1,
      eligible_naked_short_calls: 4,
      expiries_considered: 2,
    },
    naked_short_calls: {
      eligible: [
        {
          candidate_id: "BTC-7AUG26-71000-C:naked",
          instrument_name: "BTC-7AUG26-71000-C",
          expiry_date: "2026-08-07",
          dte_days: 13.9,
          model_delta: 0.1201,
          market_mid: 0.004,
          market_mark_iv: 36.58,
          surface_fitted_iv: 37,
          structure_type: "naked_short_call",
          decision: "eligible",
          surface_quality: {
            fit_quality_score: 0.9687,
            no_arb_pass: true,
          },
        },
      ],
      rejected: [],
      review: [],
    },
    call_credit_spreads: {
      eligible: [
        {
          candidate_id:
            "BTC-7AUG26-71000-C->BTC-7AUG26-77000-C:spread",
          sell_leg_instrument_name: "BTC-7AUG26-71000-C",
          buy_leg_instrument_name: "BTC-7AUG26-77000-C",
          expiry_date: "2026-08-07",
          dte_days: 13.9,
          model_delta: 0.087,
          net_credit: 0.0025,
          spread_width: 6_000,
          structure_type: "call_credit_spread",
          decision: "eligible",
          surface_quality: {
            fit_quality_score: 0.9687,
            no_arb_pass: true,
          },
        },
      ],
      rejected: [],
      review: [],
    },
  },
  strategy_research: strategyResearchFixture,
} as unknown as ResearchReport;

describe("EvidenceConsole", () => {
  it("keeps source, trust and the research loop visible at compact widths", () => {
    for (const selector of [
      ".source-indicator",
      ".freshness-source",
      ".read-only-indicator",
      ".strategy-workflow",
    ]) {
      const escapedSelector = selector.replace(".", "\\.");
      expect(evidenceStyles).not.toMatch(
        new RegExp(
          `${escapedSelector}\\s*\\{[^}]*display:\\s*none(?:\\s*!important)?`,
          "s",
        ),
      );
    }

    render(
      <EvidenceConsole
        nowMs={Date.parse("2026-07-24T10:25:04Z")}
        receivedAtMs={Date.parse("2026-07-24T10:25:04Z")}
        report={liveResearchReport}
      />,
    );

    expect(
      screen.getByLabelText(/市场来源 Deribit live，数据年龄 4 秒/),
    ).toBeInTheDocument();
    expect(screen.getByText("当前且可信")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "完整策略工作流" }),
    ).toHaveTextContent(/采集.*分析.*结构.*进场.*风控.*退出.*监控.*复盘/);
  });

  it("leads with current market facts and real research candidates", () => {
    render(
      <EvidenceConsole
        nowMs={Date.parse("2026-07-24T10:25:04Z")}
        receivedAtMs={Date.parse("2026-07-24T10:25:04Z")}
        report={liveResearchReport}
      />,
    );

    const researchSummary = screen.getByRole("region", {
      name: "实时研究摘要",
    });
    expect(
      within(researchSummary).getByRole("heading", { name: "BTC 市场脉搏" }),
    ).toBeInTheDocument();
    expect(within(researchSummary).getByText("$65,058")).toBeInTheDocument();
    expect(within(researchSummary).getByText("37.66%")).toBeInTheDocument();
    expect(
      within(researchSummary).getByText("20 / 20 条有效报价"),
    ).toBeInTheDocument();
    expect(
      within(researchSummary).getByText("4 个单腿候选"),
    ).toBeInTheDocument();
    expect(
      within(researchSummary).getByText("5 个价差候选"),
    ).toBeInTheDocument();
    expect(
      within(researchSummary).getByText("BTC-7AUG26-71000-C"),
    ).toBeInTheDocument();
    expect(screen.getByText("01 · 采集")).toBeInTheDocument();
    expect(screen.getByText("05–06 · 风控与退出")).toBeInTheDocument();
    expect(screen.getAllByText(/FORCE_CLOSE/).length).toBeGreaterThan(0);
    expect(screen.getByText(/只在 NORMAL \/ CAUTION/)).toBeInTheDocument();

    const main = screen.getByRole("main");
    expect(main.textContent?.indexOf("$65,058")).toBeLessThan(
      main.textContent?.indexOf("发布与能力边界") ?? -1,
    );
    expect(
      screen.queryByRole("heading", { name: "NO-GO" }),
    ).not.toBeInTheDocument();
  });

  it("renders a complete collection-to-review strategy workflow", () => {
    render(
      <EvidenceConsole
        nowMs={Date.parse("2026-07-24T10:25:04Z")}
        receivedAtMs={Date.parse("2026-07-24T10:25:04Z")}
        report={liveResearchReport}
      />,
    );

    const workflow = screen.getByRole("region", {
      name: "完整策略工作流",
    });
    expect(
      within(workflow).getByRole("heading", { name: "今日策略结论" }),
    ).toBeInTheDocument();
    expect(within(workflow).getByText("CALL 信用价差")).toBeInTheDocument();
    expect(within(workflow).getByText("仅观察")).toBeInTheDocument();
    expect(within(workflow).getByText("20 / 864")).toBeInTheDocument();
    expect(within(workflow).getByText("2.31% 研究样本")).toBeInTheDocument();
    expect(within(workflow).getByText("$4,512")).toBeInTheDocument();
    expect(
      within(workflow).getByText("BTC-7AUG26-71000-C"),
    ).toBeInTheDocument();
    expect(
      within(workflow).getByText("BTC-7AUG26-77000-C"),
    ).toBeInTheDocument();
    expect(within(workflow).getByText("$163")).toBeInTheDocument();
    expect(within(workflow).getByText("$5,842")).toBeInTheDocument();
    expect(within(workflow).getByText("$71,163")).toBeInTheDocument();

    const entry = within(workflow).getByRole("region", {
      name: "条件式进场规则",
    });
    expect(entry).toHaveTextContent("市场快照");
    expect(entry).toHaveTextContent("Regime 权限");
    expect(entry).toHaveTextContent("账户风控");
    expect(entry).toHaveTextContent("成本覆盖");

    const exit = within(workflow).getByRole("region", {
      name: "风险与退出规则",
    });
    expect(exit).toHaveTextContent("60%");
    expect(exit).toHaveTextContent("80%");
    expect(exit).toHaveTextContent("NORMAL");
    expect(exit).toHaveTextContent("FORCE_CLOSE");

    const pipeline = within(workflow).getByRole("list", {
      name: "策略研究八阶段",
    });
    expect(within(pipeline).getByText("采集")).toBeInTheDocument();
    expect(within(pipeline).getByText("分析")).toBeInTheDocument();
    expect(within(pipeline).getByText("结构")).toBeInTheDocument();
    expect(within(pipeline).getByText("进场")).toBeInTheDocument();
    expect(within(pipeline).getByText("风控")).toBeInTheDocument();
    expect(within(pipeline).getByText("退出")).toBeInTheDocument();
    expect(within(pipeline).getByText("监控")).toBeInTheDocument();
    expect(within(pipeline).getByText("复盘")).toBeInTheDocument();
  });

  it("keeps a blocked research report visibly fail-closed", () => {
    render(
      <EvidenceConsole
        nowMs={Date.parse("2026-07-24T08:00:12Z")}
        receivedAtMs={Date.parse("2026-07-24T08:00:12Z")}
        report={blockedReport}
      />,
    );

    const releaseBoundary = screen.getByRole("region", {
      name: "发布与能力边界",
    });
    expect(releaseBoundary).toHaveTextContent("NO-GO");
    expect(releaseBoundary).toHaveTextContent("RESEARCH_ONLY");
    expect(releaseBoundary).toHaveTextContent("NO_TRADE");
    expect(
      screen.getByText(
        /不会生成交易建议、推荐仓位或订单指令。缺口只影响置信度与执行升级。/,
      ),
    ).toBeInTheDocument();

    const operatorQueue = screen.getByRole("region", {
      name: "操作员与外部动作",
    });
    expect(
      within(operatorQueue).getByText("缺少账户 API 快照"),
    ).toBeInTheDocument();
    expect(
      within(operatorQueue).getByText("缺少已验证市场数据"),
    ).toBeInTheDocument();
    expect(operatorQueue).toHaveTextContent("配置获授权的市场数据源");

    expect(
      screen.queryByRole("button", { name: /下单|交易|执行/ }),
    ).not.toBeInTheDocument();
  });

  it("shows four contract-bound truths without equating service health with release", () => {
    render(
      <EvidenceConsole
        nowMs={Date.parse("2026-07-24T08:00:12Z")}
        receivedAtMs={Date.parse("2026-07-24T08:00:12Z")}
        report={blockedReport}
      />,
    );

    const truthStrip = screen.getByRole("region", {
      name: "四项运行边界",
    });
    expect(within(truthStrip).getByText("报告服务")).toBeInTheDocument();
    expect(within(truthStrip).getByText("已连接并验证")).toBeInTheDocument();
    expect(within(truthStrip).getByText("市场证据")).toBeInTheDocument();
    expect(within(truthStrip).getByText("不可声明")).toBeInTheDocument();
    expect(within(truthStrip).getByText("外部发布授权")).toBeInTheDocument();
    expect(within(truthStrip).getByText("NO-GO")).toBeInTheDocument();
    expect(within(truthStrip).getByText("执行边界")).toBeInTheDocument();
    expect(within(truthStrip).getByText("RESEARCH_ONLY · NO_TRADE")).toBeInTheDocument();
  });

  it("provides an anchored compact navigation with an explicit current section", () => {
    render(
      <EvidenceConsole
        nowMs={Date.parse("2026-07-24T08:00:12Z")}
        receivedAtMs={Date.parse("2026-07-24T08:00:12Z")}
        report={blockedReport}
      />,
    );

    const sectionNavigation = screen.getByRole("navigation", {
      name: "页面章节",
    });
    const briefLink = within(sectionNavigation).getByRole("link", {
      name: "市场简报",
    });
    const frameworkLink = within(sectionNavigation).getByRole("link", {
      name: "策略闭环",
    });
    const limitationsLink = within(sectionNavigation).getByRole("link", {
      name: "边界",
    });
    expect(briefLink).toHaveAttribute("aria-current", "location");
    expect(briefLink).toHaveAttribute("href", "#brief");
    expect(frameworkLink).toHaveAttribute("href", "#framework");
    expect(limitationsLink).toHaveAttribute("href", "#limitations");

    fireEvent.click(frameworkLink);
    expect(frameworkLink).toHaveAttribute("aria-current", "location");
    expect(briefLink).not.toHaveAttribute("aria-current");

    fireEvent.click(limitationsLink);
    expect(limitationsLink).toHaveAttribute("aria-current", "location");
    expect(briefLink).not.toHaveAttribute("aria-current");
  });

  it("routes an undeclared blocker to manual triage instead of inventing automation", () => {
    const reportWithUnknownOwner: ResearchReport = {
      ...blockedReport,
      reason_codes: [...(blockedReport.reason_codes ?? []), "UNMAPPED_BLOCKER"],
    };
    render(
      <EvidenceConsole
        nowMs={Date.parse("2026-07-24T08:00:12Z")}
        receivedAtMs={Date.parse("2026-07-24T08:00:12Z")}
        report={reportWithUnknownOwner}
      />,
    );

    const operatorQueue = screen.getByRole("region", {
      name: "操作员与外部动作",
    });
    const systemQueue = screen.getByRole("region", {
      name: "系统延续动作",
    });
    expect(within(operatorQueue).getByText("UNMAPPED BLOCKER")).toBeInTheDocument();
    expect(within(operatorQueue).getByText("责任未声明")).toBeInTheDocument();
    expect(operatorQueue).toHaveTextContent("请人工核对原始原因码");
    expect(within(systemQueue).queryByText("UNMAPPED BLOCKER")).not.toBeInTheDocument();
  });

  it("does not blame the operator for internal implementation and observation work", () => {
    const internalWorkReport: ResearchReport = {
      ...blockedReport,
      reason_codes: [
        "TRUST_EVIDENCE_NOT_OBSERVED",
        "DATA_TRUST_OBSERVATION_COLLECTING",
        "REGIME_TRUST_EVIDENCE_NOT_PROMOTED",
        "CALIBRATION_NOT_IMPLEMENTED",
        "BACKTEST_NOT_RUN",
      ],
      mode_gate: {
        ...blockedReport.mode_gate,
        reason_codes: [
          "TRUST_EVIDENCE_NOT_OBSERVED",
          "DATA_TRUST_OBSERVATION_COLLECTING",
          "REGIME_TRUST_EVIDENCE_NOT_PROMOTED",
          "CALIBRATION_NOT_IMPLEMENTED",
          "BACKTEST_NOT_RUN",
        ],
      },
    };

    render(
      <EvidenceConsole
        nowMs={Date.parse("2026-07-24T08:00:12Z")}
        receivedAtMs={Date.parse("2026-07-24T08:00:12Z")}
        report={internalWorkReport}
      />,
    );

    const operatorQueue = screen.getByRole("region", {
      name: "操作员与外部动作",
    });
    const systemQueue = screen.getByRole("region", {
      name: "系统延续动作",
    });
    expect(operatorQueue).not.toHaveTextContent("校准能力尚未就绪");
    expect(operatorQueue).not.toHaveTextContent("Backtest 尚未运行");
    expect(within(systemQueue).getByText("校准能力尚未就绪")).toBeInTheDocument();
    expect(within(systemQueue).getByText("Backtest 尚未运行")).toBeInTheDocument();
    expect(
      within(systemQueue).getByText("市场可信观察尚未完成"),
    ).toBeInTheDocument();
    expect(
      within(systemQueue).getByText("Regime 可信证据尚未提升"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("DATA TRUST OBSERVATION COLLECTING"),
    ).not.toBeInTheDocument();
  });

  it("does not promote healthy account and active-regime facts into blockers", () => {
    const informationalReport: ResearchReport = {
      ...blockedReport,
      reason_codes: [
        "ACCOUNT_MARGIN_GREEN",
        "PRIMARY_REGIME_RANGE",
        "RANGE_PERMISSION_ACTIVE",
      ],
      account_status: {
        status: "validated",
        source: "read_only_api",
        margin_light: "GREEN",
        trade_gate: "ALLOW_NEW",
        reason_code: "ACCOUNT_MARGIN_GREEN",
      },
      mode_gate: {
        ...blockedReport.mode_gate,
        reason_codes: [
          "ACCOUNT_MARGIN_GREEN",
          "PRIMARY_REGIME_RANGE",
          "RANGE_PERMISSION_ACTIVE",
        ],
      },
    };
    render(
      <EvidenceConsole
        nowMs={Date.parse("2026-07-24T08:00:12Z")}
        receivedAtMs={Date.parse("2026-07-24T08:00:12Z")}
        report={informationalReport}
      />,
    );

    expect(screen.queryByText("ACCOUNT MARGIN GREEN")).not.toBeInTheDocument();
    expect(screen.queryByText("ACCOUNT_MARGIN_GREEN")).not.toBeInTheDocument();
    expect(screen.queryByText("PRIMARY REGIME RANGE")).not.toBeInTheDocument();
    expect(screen.queryByText("RANGE PERMISSION ACTIVE")).not.toBeInTheDocument();
  });

  it("expires a previously trusted verdict when market evidence reaches its age limit", () => {
    const trustedReport: ResearchReport = {
      ...blockedReport,
      action: "READY",
      mode: "paper",
      effective_mode: "paper",
      risk_state: "ALLOW",
      reason_codes: [],
      blocked_outputs: [],
      data_trust: {
        verdict: "trusted",
        source_class: "validated",
        reason_codes: [],
      },
      data_status: {
        status: "validated",
        source: "fixture:trusted-market",
        validated: true,
        market_data_age_sec: 44,
        quality_gate: {
          passed: true,
          thresholds: {
            market_data_max_age_sec: 60,
          },
        },
      },
      account_status: {
        status: "validated",
        source: "read_only_api",
        margin_light: "GREEN",
        trade_gate: "ALLOW",
      },
      mode_gate: {
        trade_recommendation_allowed: true,
        recommended_size_allowed: true,
        order_instructions_allowed: true,
        paper_manual_candidates_allowed: true,
        reason_codes: [],
      },
      full_system_surface: {
        release_readiness: {
          status: "NO-GO",
          prerequisites: [],
        },
      },
    };
    const receivedAtMs = Date.parse("2026-07-24T08:00:00Z");
    const { rerender } = render(
      <EvidenceConsole
        nowMs={receivedAtMs}
        receivedAtMs={receivedAtMs}
        report={trustedReport}
      />,
    );

    expect(screen.getByText("当前")).toBeInTheDocument();
    expect(screen.getByText("44 秒")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "发布与能力边界" }),
    ).toHaveTextContent("NO-GO");

    rerender(
      <EvidenceConsole
        nowMs={receivedAtMs + 1_000}
        receivedAtMs={receivedAtMs}
        report={trustedReport}
      />,
    );
    expect(screen.getByText("预警")).toBeInTheDocument();

    rerender(
      <EvidenceConsole
        nowMs={receivedAtMs + 16_000}
        receivedAtMs={receivedAtMs}
        report={trustedReport}
      />,
    );
    expect(
      within(
        screen.getByRole("region", { name: "市场证据新鲜度" }),
      ).getByText("已失效"),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("region", { name: "市场证据新鲜度" }),
      ).getAllByText("60 秒"),
    ).toHaveLength(2);
    expect(
      screen.getByRole("region", { name: "发布与能力边界" }),
    ).toHaveTextContent("NO-GO");
  });

  it("shows an honest retryable state when report evidence cannot be loaded", async () => {
    const loadReport = vi
      .fn<() => Promise<LoadedReport>>()
      .mockRejectedValue(new Error("network unavailable"));

    render(<App loadReport={loadReport} />);

    expect(screen.getByRole("status")).toHaveTextContent("正在读取市场研究");
    expect(await screen.findByRole("alert")).toHaveTextContent("研究数据不可用");
    expect(screen.getByRole("alert")).toHaveTextContent("NO-GO · NO_TRADE");
    expect(screen.queryByText(/\d+\s*秒/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重新读取" }));
    expect(loadReport).toHaveBeenCalledTimes(2);
  });

  it("lets the operator explicitly refresh the evidence report", async () => {
    const loadReport = vi
      .fn<() => Promise<LoadedReport>>()
      .mockResolvedValue(loadedReport());

    render(<App loadReport={loadReport} />);

    const refresh = await screen.findByRole("button", { name: "刷新" });
    fireEvent.click(refresh);

    await waitFor(() => {
      expect(loadReport).toHaveBeenCalledTimes(2);
    });
    expect(
      await screen.findByRole("button", { name: "刷新" }),
    ).toHaveAttribute("aria-busy", "false");
  });

  it("preserves transport receipt time when calculating evidence age", async () => {
    const trustedReport: ResearchReport = {
      ...blockedReport,
      data_trust: {
        verdict: "trusted",
        source_class: "validated",
        reason_codes: [],
      },
      data_status: {
        status: "validated",
        source: "deribit_live:https://www.deribit.com",
        validated: true,
        market_data_age_sec: 44,
        quality_gate: {
          passed: true,
          thresholds: {
            market_data_max_age_sec: 60,
          },
        },
      },
    };
    const receivedAtMs = Date.now() - 16_000;

    render(
      <App
        loadReport={() =>
          Promise.resolve(loadedReport(trustedReport, receivedAtMs))
        }
      />,
    );

    expect(
      within(
        await screen.findByRole("region", { name: "市场证据新鲜度" }),
      ).getByText("已失效"),
    ).toBeInTheDocument();
  });

  it("rejects a report that attempts to enable trading semantics", async () => {
    const unsafeReport: ResearchReport = {
      ...blockedReport,
      action: "TRADE",
      effective_mode: "live",
      mode_gate: {
        ...blockedReport.mode_gate,
        trade_recommendation_allowed: true,
      },
      full_system_surface: {
        release_readiness: {
          status: "GO",
          prerequisites: [],
        },
      },
    };

    render(<App loadReport={() => Promise.resolve(loadedReport(unsafeReport))} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("研究数据不可用");
    expect(screen.getByRole("alert")).toHaveTextContent("NO-GO · NO_TRADE");
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
  });

  it("keeps product NO_TRADE distinct from an allowed account sub-gate", async () => {
    const greenAccountReport: ResearchReport = {
      ...blockedReport,
      account_status: {
        status: "validated",
        source: "read_only_api",
        margin_light: "GREEN",
        trade_gate: "ALLOW_NEW",
      },
    };

    render(
      <App loadReport={() => Promise.resolve(loadedReport(greenAccountReport))} />,
    );

    const releaseBoundary = await screen.findByRole("region", {
      name: "发布与能力边界",
    });
    expect(releaseBoundary).toHaveTextContent("NO-GO");
    expect(releaseBoundary).toHaveTextContent("NO_TRADE");
    expect(screen.getByText("ALLOW NEW")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each(["RESEARCH_ONLY_NO_TRADE", "NO_TRADE"])(
    "accepts the contract's conservative %s action",
    async (action) => {
      const conservativeReport: ResearchReport = {
        ...blockedReport,
        action,
      };

      render(
        <App
          loadReport={() => Promise.resolve(loadedReport(conservativeReport))}
        />,
      );

      expect(
        await screen.findByRole("region", { name: "发布与能力边界" }),
      ).toHaveTextContent("NO-GO");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );
});
