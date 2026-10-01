import { useEffect, useState } from "react";

import type { DecisionDesk, DeskCandidate, DeskCriteria, DeskStructure, Viewpoint } from "./types";

export const STRUCTURE_LABELS: Record<DeskStructure, string> = {
  BULL_PUT_CREDIT: "牛市看跌信用价差",
  BEAR_CALL_CREDIT: "熊市看涨信用价差",
  IRON_CONDOR: "铁鹰区间结构",
};
export const VIEWPOINT_LABELS: Record<Viewpoint, string> = {
  all: "尚未确定", bullish: "偏多", bearish: "偏空", range: "区间",
};

export function deskNumber(value: number | null | undefined, precision = 2): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("zh-CN", { maximumFractionDigits: precision }) : "未提供";
}

export function deskTime(value: string | null | undefined): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "未提供";
  return `${new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(new Date(value))} UTC+8`;
}

export function deskExpired(desk: DecisionDesk, nowMs: number): boolean {
  const expiry = Date.parse(desk.expires_at);
  return !Number.isFinite(expiry) || nowMs >= expiry
    || desk.qualification.data_status === "stale" || desk.qualification.data_status === "unavailable";
}

export function candidateComparable(candidate: DeskCandidate, nowMs = Date.now()): boolean {
  const expectedLegs = candidate.structure === "IRON_CONDOR" ? 4 : 2;
  const recheck = Date.parse(candidate.recheck_at);
  return candidate.status === "comparable" && Number.isFinite(recheck) && recheck > nowMs
    && candidate.expiration_timestamp > nowMs && candidate.legs.length === expectedLegs
    && candidate.legs.every((leg) => typeof leg.bid === "number" && leg.bid > 0
      && typeof leg.ask === "number" && leg.ask >= leg.bid
      && Number.isFinite(Date.parse(leg.quote_time ?? leg.observed_at ?? "")));
}

export function CandidateLegs({ candidate, detailed = false }: {
  candidate: DeskCandidate; detailed?: boolean;
}): React.JSX.Element {
  return <ul className="desk-legs" aria-label={`${STRUCTURE_LABELS[candidate.structure]}完整合约腿`}>
    {candidate.legs.map((leg) => <li key={`${leg.side}:${leg.instrument_name}`}>
      <div className="desk-leg-name"><span className="desk-leg-side" data-side={leg.side}>{leg.side === "SELL" ? "卖出腿" : "买入腿"}</span>
        <span>{leg.instrument_name}</span><small>比例 {leg.ratio} · 合约单位 {leg.contract_size}</small></div>
      <p>Bid {leg.bid === null ? "—" : String(leg.bid)} / Ask {leg.ask === null ? "—" : String(leg.ask)} {leg.price_currency}</p>
      {detailed ? <small>报价于 {deskTime(leg.quote_time ?? leg.observed_at)} · 结算 {leg.settlement_currency}</small> : null}
    </li>)}
  </ul>;
}

const OPPORTUNITY_COPY: Record<DecisionDesk["qualification"]["opportunity_status"], { title: string; detail: string }> = {
  available: { title: "从完整结构开始比较", detail: "先确认自己的观点，再比较同一到期日的两到三个结构。筛选不改变研究资格。" },
  no_match: { title: "当前筛选没有匹配结构", detail: "可以调整观点或到期范围；这是筛选结果，不代表市场不存在机会。" },
  data_blocked: { title: "这批报价暂不能形成可靠比较", detail: "缺失、过期或交叉报价已被排除。取得新数据后再复核。" },
  liquidity_blocked: { title: "结构存在，报价流动性不足", detail: "双边价差或有效报价未满足当前条件；没有用中间价代替可观察的报价。" },
  risk_blocked: { title: "结构存在，风险条件未通过", detail: "保留排除原因；不会通过隐藏保护腿或降低条件生成可比较结构。" },
};

export interface DiscoverWorkspaceProps {
  desk: DecisionDesk;
  criteria: DeskCriteria;
  selectedIds: string[];
  busy: boolean;
  nowMs: number;
  onCriteriaChange: (criteria: DeskCriteria) => void;
  onApply: () => void;
  onSelect: (candidate: DeskCandidate) => void;
  onCompare: () => void;
}

export function DiscoverWorkspace({ desk, criteria, selectedIds, busy, nowMs,
  onCriteriaChange, onApply, onSelect, onCompare }: DiscoverWorkspaceProps): React.JSX.Element {
  const [showExcluded, setShowExcluded] = useState(false);
  const [structure, setStructure] = useState<DeskStructure | "all">("all");
  const [visibleLimit, setVisibleLimit] = useState(12);
  useEffect(() => { setVisibleLimit(12); }, [desk.snapshot_id, desk.analysis_id, showExcluded, structure]);
  const expired = deskExpired(desk, nowMs);
  const copy = OPPORTUNITY_COPY[desk.qualification.opportunity_status];
  const changed = criteria.viewpoint !== desk.criteria.viewpoint || criteria.dte_min !== desk.criteria.dte_min
    || criteria.dte_max !== desk.criteria.dte_max || criteria.max_width_pct !== desk.criteria.max_width_pct
    || criteria.max_spread_ratio !== desk.criteria.max_spread_ratio;
  const selected = desk.candidates.filter((candidate) => selectedIds.includes(candidate.candidate_id));
  const selectedExpiry = selected[0]?.expiry_date;
  const tier = { comparable: 0, research_only: 1, excluded: 2 };
  const matched = desk.candidates.filter((candidate) => (structure === "all" || candidate.structure === structure)
    && (showExcluded || candidate.status !== "excluded"))
    .sort((left, right) => tier[left.status] - tier[right.status]);
  const visible = matched.slice(0, visibleLimit);
  const comparableCount = desk.candidates.filter((candidate) => candidateComparable(candidate, nowMs)).length;
  const excludedCount = desk.candidates.filter((candidate) => candidate.status === "excluded").length;
  const dataExclusions = Object.entries(desk.coverage.exclusions);
  const candidateExclusions = Object.entries(desk.qualification.exclusion_counts);

  return <main className="desk-workspace" id="decision-desk-main">
    <div className="desk-workspace-heading"><div><p className="desk-eyebrow">01 · 发现</p>
      <h1>{expired ? "先更新数据，再比较结构" : copy.title}</h1>
      <p>{expired ? "当前快照有效期已过。下方作为历史研究展示，比较与观察保存已暂停。" : copy.detail}</p></div>
      <span className="desk-quiet-label">{desk.asset} · USDC 线性期权</span></div>

    <form className="desk-filter-panel" onSubmit={(event) => { event.preventDefault(); onApply(); }}>
      <fieldset className="desk-viewpoint"><legend>我的研究观点</legend><div className="desk-segmented">
        {(Object.keys(VIEWPOINT_LABELS) as Viewpoint[]).map((viewpoint) => <button key={viewpoint} type="button"
          aria-pressed={criteria.viewpoint === viewpoint} onClick={() => onCriteriaChange({ ...criteria, viewpoint })}>
          {VIEWPOINT_LABELS[viewpoint]}</button>)}
      </div></fieldset>
      <div className="desk-filter-adjustment-row"><details className="desk-filter-conditions"
        onInvalidCapture={(event) => { event.currentTarget.open = true; }}>
        <summary><strong>到期与报价条件</strong><span>{criteria.dte_min}–{criteria.dte_max} 天 · 保护翼 ≤{deskNumber(criteria.max_width_pct * 100, 0)}% · 单腿价差 ≤{deskNumber(criteria.max_spread_ratio * 100, 0)}%</span></summary>
        <div className="desk-filter-fields">
        <label>最短到期天数<input type="number" min={0} max={365} step={1} required value={criteria.dte_min}
          onChange={(event) => onCriteriaChange({ ...criteria, dte_min: Number(event.currentTarget.value) })} /></label>
        <label>最长到期天数<input type="number" min={criteria.dte_min} max={365} step={1} required value={criteria.dte_max}
          onChange={(event) => onCriteriaChange({ ...criteria, dte_max: Number(event.currentTarget.value) })} /></label>
        <label>最大保护翼宽度 <span>占标的价格 %</span><input type="number" min={1} max={50} step={1} required
          value={Math.round(criteria.max_width_pct * 100)} onChange={(event) => onCriteriaChange({ ...criteria, max_width_pct: Number(event.currentTarget.value) / 100 })} /></label>
        <label>最大单腿价差 <span>相对中间价 %</span><input type="number" min={1} max={100} step={1} required
          value={Math.round(criteria.max_spread_ratio * 100)} onChange={(event) => onCriteriaChange({ ...criteria, max_spread_ratio: Number(event.currentTarget.value) / 100 })} /></label>
        </div>
      </details><button className="desk-button desk-button-primary" disabled={busy} type="submit">{busy ? "正在核验…" : "应用筛选"}</button></div>
      <p className="desk-filter-help">{changed ? "筛选有变更，应用后重新发现结构。" : "观点由你选择；未校准的排序和报价不等于胜率或预期盈利。"}</p>
    </form>

    <details className="desk-coverage"><summary><strong>看清这次覆盖范围</strong>
      <span>{desk.coverage.scan_complete ? "合约登记已扫描" : "登记扫描不完整"} · {desk.coverage.deepened_count} 个合约取得深层报价</span></summary>
      <div className="desk-coverage-body"><dl className="desk-facts">
        <div><dt>登记合约</dt><dd>{deskNumber(desk.coverage.registry_count, 0)}</dd></div>
        <div><dt>行情摘要</dt><dd>{deskNumber(desk.coverage.summary_count, 0)}</dd></div>
        <div><dt>符合研究范围</dt><dd>{deskNumber(desk.coverage.eligible_instrument_count, 0)}</dd></div>
        <div><dt>已排除反向合约</dt><dd>{deskNumber(desk.coverage.inverse_excluded_count, 0)}</dd></div>
      </dl><p>登记与摘要扫描用于发现范围；只对入选合约进一步取双边报价。这不是全市场所有选腿组合的穷举，也不包含反向结算合约。</p>
        {desk.coverage.formed_structure_count !== undefined ? <p>形成 {desk.coverage.formed_structure_count} 个结构 · 筛选匹配 {desk.coverage.matched_count ?? "未提供"} 个 · 进一步核验 {desk.coverage.shortlisted_count ?? desk.candidates.length} 个
          {desk.coverage.shortlist_limit !== undefined ? `（本次上限 ${desk.coverage.shortlist_limit} 个）` : ""}。未进入深层报价的结构不被当作已核验机会。</p> : null}
        {desk.coverage.expiry_counts.length > 0 ? <p>到期覆盖：{desk.coverage.expiry_counts.map((row) => `${row.expiry_date}（${row.count} 个）`).join(" · ")}</p> : null}
        {dataExclusions.length || candidateExclusions.length ? <div className="desk-exclusion-columns">
          {dataExclusions.length ? <div><h3>合约排除</h3><ul>{dataExclusions.map(([reason, count]) => <li key={reason}><code>{reason}</code><span>{count}</span></li>)}</ul></div> : null}
          {candidateExclusions.length ? <div><h3>结构排除</h3><ul>{candidateExclusions.map(([reason, count]) => <li key={reason}><code>{reason}</code><span>{count}</span></li>)}</ul></div> : null}
        </div> : null}
        {desk.coverage.failures.length ? <div className="desk-notice" role="note"><strong>本次采集缺口</strong><ul>{desk.coverage.failures.map((failure, index) => <li key={index}>{failure}</li>)}</ul></div> : null}
      </div>
    </details>

    <div className="desk-results-toolbar"><p><strong>{matched.length}</strong> 个结构 · {comparableCount} 个报价可比较{excludedCount ? ` · ${excludedCount} 个已排除` : ""}
      {matched.length > visible.length ? ` · 先显示 ${visible.length} 个` : ""}</p>
      <div><label className="desk-select-label">结构<select value={structure} onChange={(event) => setStructure(event.currentTarget.value as DeskStructure | "all")}>
        <option value="all">全部结构</option>{(Object.keys(STRUCTURE_LABELS) as DeskStructure[]).map((key) => <option key={key} value={key}>{STRUCTURE_LABELS[key]}</option>)}</select></label>
        {excludedCount ? <label className="desk-checkbox"><input type="checkbox" checked={showExcluded} onChange={(event) => setShowExcluded(event.currentTarget.checked)} />查看排除结构</label> : null}</div>
    </div>

    {visible.length === 0 ? <section className="desk-empty" role="status"><span aria-hidden="true">○</span><h2>{copy.title}</h2>
      <p>{desk.candidates.length > 0 ? "当前列表过滤没有结果，可以切换结构或查看排除结构。" : copy.detail}</p></section> : <div className="desk-opportunities">
      {visible.map((candidate) => {
        const isSelected = selectedIds.includes(candidate.candidate_id);
        const comparable = candidateComparable(candidate, nowMs);
        const differentExpiry = !!selectedExpiry && candidate.expiry_date !== selectedExpiry;
        const disabled = !isSelected && (busy || expired || !comparable || selectedIds.length >= 3 || differentExpiry);
        const unavailableReason = expired ? "快照已过期" : !comparable ? candidate.status === "comparable" ? "该结构报价需重新复核" : "报价或结构条件未通过" : differentExpiry ? "请选择同一到期日" : selectedIds.length >= 3 ? "最多比较三个结构" : null;
        return <article className="desk-opportunity" key={candidate.candidate_id} data-selected={isSelected} data-status={candidate.status}>
          <div className="desk-opportunity-heading"><div><span className="desk-pill" data-tone={comparable ? "good" : "warning"}>
            {comparable ? "报价可比较" : candidate.status === "excluded" ? "已排除" : candidate.status === "comparable" ? "报价已暂停" : "仅供研究"}</span>
            <h2>{STRUCTURE_LABELS[candidate.structure]}</h2><p>{VIEWPOINT_LABELS[candidate.viewpoint]} · {candidate.expiry_date} 到期 · {deskNumber(candidate.dte_days, 1)} 天</p></div>
            <div className="desk-opportunity-economics"><span>按结构比例的净权利金参考</span><strong>{deskNumber(candidate.economics.net_entry_cash)} <small>USDC</small></strong><small>入场费用 {deskNumber(candidate.economics.entry_fees)} USDC · 研究报价</small></div></div>
          <CandidateLegs candidate={candidate} />
          <div className="desk-opportunity-footer"><details><summary>报价时间、风险范围与排除原因</summary><div className="desk-opportunity-details">
            <p>期权到期收益损失边界：{deskNumber(candidate.economics.option_payoff_loss_bound)} USDC；不含入场、退出及交割费用，不是含费实际损失上限。</p>
            <p>复核时刻 {deskTime(candidate.recheck_at)} · 假设标识 <code>{candidate.assumptions_id}</code></p>
            {candidate.legs.map((leg) => <p key={leg.instrument_name}>{leg.instrument_name} · {deskTime(leg.quote_time ?? leg.observed_at)} · 合约单位 {leg.contract_size}</p>)}
            {candidate.reasons.map((reason) => <p key={reason.code}><strong>{reason.detail}</strong> <code>{reason.code}</code></p>)}
            {candidate.invalidation.map((reason) => <p key={reason.code}>失效条件：{reason.detail}</p>)}
          </div></details>
            <div className="desk-add-action">{unavailableReason && !isSelected ? <small>{unavailableReason}</small> : null}<button type="button" className={`desk-button ${isSelected ? "desk-button-selected" : "desk-button-secondary"}`}
              aria-pressed={isSelected} disabled={disabled} onClick={() => onSelect(candidate)}>{isSelected ? "移出比较" : "加入比较"}</button></div></div>
        </article>;
      })}
    </div>}
    {matched.length > visible.length ? <div className="desk-more-results"><p>报价可比较的结构先展示；其余研究结构与排除原因仍保留。</p>
      <button type="button" className="desk-button desk-button-secondary" onClick={() => setVisibleLimit((limit) => limit + 12)}>再查看 {Math.min(12, matched.length - visible.length)} 个结构</button></div> : null}

    <div className="desk-compare-tray" aria-label="已选比较结构"><div><strong>已选 {selectedIds.length} / 3</strong>
      <p>{selected.length ? selected.map((candidate) => STRUCTURE_LABELS[candidate.structure]).join(" · ") : "选择同一到期日的两个结构，开始比较。"}</p></div>
      <button className="desk-button desk-button-primary" type="button" disabled={selectedIds.length < 2 || busy || expired || !selected.every((candidate) => candidateComparable(candidate, nowMs))} onClick={onCompare}>比较这些结构 <span aria-hidden="true">→</span></button></div>
  </main>;
}
