import { useEffect, useId, useState } from "react";

import type { DecisionDesk, DeskCandidate, DeskComparison, DeskScenario } from "./types";
import { CandidateLegs, candidateComparable, deskExpired, deskNumber, deskTime, STRUCTURE_LABELS, VIEWPOINT_LABELS } from "./DiscoverWorkspace";

const COLORS = ["#176b52", "#4967a1", "#956324"];

export function buildDeskResearchCopy(desk: DecisionDesk, candidate: DeskCandidate, comparison: DeskComparison): string {
  return [
    "RESEARCH_ONLY / execution_allowed=false / NOT AN ORDER",
    `SOURCE MODE: ${desk.source.mode}${desk.source.mode === "demo" ? " / SYNTHETIC OFFLINE EXAMPLE; NOT CURRENT MARKET EVIDENCE" : ""}`,
    `SOURCE: ${desk.source.provider}`,
    `ASSET: ${desk.asset} / DERIBIT LINEAR_USDC`,
    `SNAPSHOT ID: ${desk.snapshot_id}`,
    `ANALYSIS ID: ${desk.analysis_id}`,
    `CANDIDATE ID: ${candidate.candidate_id}`,
    `SCENARIO ID: ${comparison.scenario_id}`,
    `ASSUMPTIONS ID: ${comparison.assumptions_id}`,
    `CAPTURED AT: ${desk.source.captured_at}`,
    `EVALUATED AT: ${desk.generated_at}`,
    `COMPARISON AT: ${comparison.generated_at}`,
    `VALID UNTIL: ${desk.expires_at}`,
    `STRUCTURE: ${candidate.structure} / VIEWPOINT: ${VIEWPOINT_LABELS[candidate.viewpoint]}`,
    `CONTRACT EXPIRY: ${candidate.expiry_date} / ${new Date(candidate.expiration_timestamp).toISOString()}`,
    ...candidate.legs.map((leg) => `LEG: ${leg.side} ${leg.instrument_name} / STRUCTURE RATIO ${leg.ratio} / CONTRACT SIZE ${leg.contract_size} / BID ${leg.bid} / ASK ${leg.ask} ${leg.price_currency} / SETTLEMENT ${leg.settlement_currency} / QUOTED AT ${leg.quote_time ?? leg.observed_at}`),
    `NET ENTRY CASH REFERENCE: ${candidate.economics.net_entry_cash} USDC`,
    `ENTRY FEES: ${candidate.economics.entry_fees} USDC / POLICY ${candidate.economics.fee_policy_id}`,
    `MID-TO-TOUCH DRAG: ${candidate.economics.mid_to_touch_drag} USDC`,
    `GROSS OPTION PAYOFF LOSS BOUND: ${candidate.economics.option_payoff_loss_bound} USDC / EXCLUDES ENTRY, EXIT AND DELIVERY FEES; NOT AN ACTUAL LOSS GUARANTEE`,
    `SCENARIO: PRICE CHANGE ${comparison.scenario.price_change_pct}% / ELAPSED ${comparison.scenario.time_days} DAYS / IV SHIFT ${comparison.scenario.iv_shift_points} PERCENTAGE POINTS`,
    ...comparison.assumptions.map((assumption) => `ASSUMPTION: ${assumption}`),
    ...candidate.reasons.map((reason) => `RESEARCH REASON: ${reason.code} / ${reason.detail}`),
    ...candidate.invalidation.map((reason) => `INVALID IF: ${reason.code} / ${reason.detail}`),
    `RECHECK AT: ${candidate.recheck_at}`,
    "RECHECK: Obtain fresh positive synchronized bid/ask for every exact leg, verify currencies and fees, and recompute all evidence. Do not reuse after VALID UNTIL.",
    "结构比例只定义研究计算口径，不是推荐手数或仓位。模型情景不代表实际成交、未来收益或盈利概率；本记录不构成执行授权。",
  ].join("\n");
}

function ExpiryComparisonChart({ candidates, comparison, spot }: {
  candidates: DeskCandidate[]; comparison: DeskComparison; spot: number | null;
}): React.JSX.Element {
  const titleId = useId();
  const [compact, setCompact] = useState(() => window.matchMedia?.("(max-width: 699px)").matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.("(max-width: 699px)");
    if (!media) return;
    const sync = () => setCompact(media.matches);
    sync(); media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);
  const points = comparison.members.flatMap((member) => member.expiry_points);
  if (points.length < 2) return <p className="desk-muted">到期情景数据未提供。</p>;
  const minimumPrice = Math.min(...points.map((point) => point.price));
  const maximumPrice = Math.max(...points.map((point) => point.price));
  const minimumPnl = Math.min(0, ...points.map((point) => point.pnl));
  const maximumPnl = Math.max(0, ...points.map((point) => point.pnl));
  const width = compact ? 360 : 748;
  const left = compact ? 52 : 66;
  const right = width - (compact ? 12 : 32);
  const x = (price: number) => left + ((price - minimumPrice) / (maximumPrice - minimumPrice || 1)) * (right - left);
  const y = (pnl: number) => 24 + ((maximumPnl - pnl) / (maximumPnl - minimumPnl || 1)) * 210;
  const ticks = Array.from(new Set([maximumPnl, 0, minimumPnl]));
  return <figure className="desk-expiry-chart">
    <svg viewBox={`0 0 ${width} 280`} role="img" aria-labelledby={titleId}>
      <title id={titleId}>同一到期日各结构的条件到期损益，USDC；按列明入场费与标准交割费计算</title>
      {ticks.map((tick) => <g key={tick}><line x1={left} x2={right} y1={y(tick)} y2={y(tick)} stroke={tick === 0 ? "#89978f" : "#e4eae6"} />
        <text x={left - 8} y={y(tick) + 4} textAnchor="end">{compact && Math.abs(tick) >= 1000 ? `${deskNumber(tick / 1000, 1)}k` : deskNumber(tick, 0)}</text></g>)}
      {spot !== null && spot >= minimumPrice && spot <= maximumPrice ? <g><line x1={x(spot)} x2={x(spot)} y1={18} y2={234} stroke="#a7b4ad" strokeDasharray="4 4" />
        <text x={x(spot)} y={14} textAnchor="middle">快照标的价格</text></g> : null}
      {comparison.members.map((member) => {
        const index = candidates.findIndex((candidate) => candidate.candidate_id === member.candidate_id);
        return <path key={member.candidate_id} fill="none" stroke={COLORS[index % COLORS.length]} strokeWidth={2.5}
          strokeDasharray={index === 2 ? "7 3" : undefined} d={member.expiry_points.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${x(point.price).toFixed(2)},${y(point.pnl).toFixed(2)}`).join(" ")} />;
      })}
      {(compact ? [minimumPrice, maximumPrice] : [minimumPrice, (minimumPrice + maximumPrice) / 2, maximumPrice]).map((tick, index, all) => <text key={index} x={x(tick)} y={254}
        textAnchor={index === 0 ? "start" : index === all.length - 1 ? "end" : "middle"}>{deskNumber(tick, 0)}</text>)}
      <text x={right} y={276} textAnchor="end">到期标的价格 · USDC</text>
    </svg>
    <figcaption>{candidates.map((candidate, index) => <span key={candidate.candidate_id}><i style={{ background: COLORS[index % COLORS.length] }} aria-hidden="true" />
      {index + 1} · {STRUCTURE_LABELS[candidate.structure]}</span>)}</figcaption>
  </figure>;
}

function CopyReview({ text, disabled, current }: { text: string; disabled: boolean; current: () => boolean }): React.JSX.Element {
  const [status, setStatus] = useState<"idle" | "copied" | "failed" | "expired">("idle");
  const textareaId = useId();
  useEffect(() => { setStatus("idle"); }, [text, disabled]);
  return <div className="desk-copy"><button type="button" className="desk-button desk-button-secondary" disabled={disabled}
    onClick={() => { void (async () => {
      if (!current()) { setStatus("expired"); return; }
      try {
        if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(text); setStatus("copied");
      } catch { setStatus("failed"); }
    })(); }}>{status === "copied" ? "已复制研究复核" : "复制研究复核"}</button>
    <p className="desk-action-feedback" role="status">{status === "copied" ? "已保留选腿、报价、共同假设和复核时刻；不产生订单。" : status === "failed" ? "剪贴板不可用，可在下方手动复制。" : status === "expired" ? "报价刚刚过期，复制已暂停，请重新读取数据。" : ""}</p>
    {status === "failed" && !disabled ? <div className="desk-copy-fallback"><label htmlFor={textareaId}>研究复核文本</label>
      <textarea id={textareaId} rows={8} readOnly value={text} onFocus={(event) => event.currentTarget.select()} /></div> : null}
  </div>;
}

export interface CompareWorkspaceProps {
  desk: DecisionDesk;
  candidates: DeskCandidate[];
  comparison: DeskComparison | null;
  scenario: DeskScenario;
  busy: boolean;
  nowMs: number;
  error?: string | null;
  scenarioAdjusted?: boolean;
  onScenarioChange: (scenario: DeskScenario) => void;
  onRunComparison: () => void;
  onRemove: (candidateId: string) => void;
  onSave: (candidateId: string, note: string) => void;
  onBack: () => void;
}

export function CompareWorkspace({ desk, candidates, comparison, scenario, busy, nowMs, error, scenarioAdjusted = false,
  onScenarioChange, onRunComparison, onRemove, onSave, onBack }: CompareWorkspaceProps): React.JSX.Element {
  const [chosenId, setChosenId] = useState("");
  const [note, setNote] = useState("");
  const ids = candidates.map((candidate) => candidate.candidate_id).join("|");
  useEffect(() => { setChosenId(""); setNote(""); }, [ids, desk.snapshot_id]);
  const expired = deskExpired(desk, nowMs) || candidates.some((candidate) => !candidateComparable(candidate, nowMs));
  const sameExpiry = candidates.length > 0 && candidates.every((candidate) => candidate.expiry_date === candidates[0].expiry_date);
  const matches = comparison !== null && comparison.snapshot_id === desk.snapshot_id && comparison.analysis_id === desk.analysis_id
    && comparison.members.length === candidates.length
    && comparison.members.every((member) => candidates.some((candidate) => candidate.candidate_id === member.candidate_id));
  const scenarioChanged = matches && (comparison.scenario.price_change_pct !== scenario.price_change_pct
    || comparison.scenario.time_days !== scenario.time_days || comparison.scenario.iv_shift_points !== scenario.iv_shift_points);
  const canUse = matches && !scenarioChanged && !expired && !busy;
  const maximumDays = Math.max(0, Math.floor(Math.min(...candidates.map((candidate) => candidate.dte_days))));

  if (candidates.length < 2 || !sameExpiry) return <main className="desk-workspace" id="decision-desk-main">
    <div className="desk-workspace-heading"><div><p className="desk-eyebrow">02 · 比较与决策</p><h1>让结构在同一假设下比较</h1></div></div>
    <section className="desk-empty"><span aria-hidden="true">⇄</span><h2>先选择同一到期日的两个结构</h2>
      <p>最多比较三个；每项保留完整合约腿，不合并为账户组合，也不建议手数。</p>
      <button className="desk-button desk-button-primary" onClick={onBack} type="button">返回发现机会</button></section>
  </main>;

  return <main className="desk-workspace" id="decision-desk-main">
    <div className="desk-workspace-heading"><div><p className="desk-eyebrow">02 · 比较与决策</p><h1>在同一假设下，做出研究选择</h1>
      <p>{desk.asset} · 同于 {candidates[0].expiry_date} 到期 · 一个快照、一套成本口径。每条曲线分别表示一个结构，不叠加成仓位。</p></div>
      <button className="desk-button desk-button-quiet" onClick={onBack} type="button">调整所选结构</button></div>
    {expired ? <div className="desk-notice" role="alert"><strong>当前比较已暂停</strong><p>快照或所选结构报价已到复核期限。历史图表保留用于理解；取得新数据并重新选择后才可保存观察或复制复核。</p></div> : null}
    {error ? <div className="desk-notice" role="alert"><strong>比较暂未完成</strong><p>{error}</p></div> : null}

    <div className="desk-comparison-cards" style={{ "--desk-compare-count": candidates.length } as React.CSSProperties}>
      {candidates.map((candidate, index) => <article className="desk-comparison-card" key={candidate.candidate_id}>
        <header><span className="desk-comparison-number" style={{ background: COLORS[index % COLORS.length] }}>{index + 1}</span><div><h2>{STRUCTURE_LABELS[candidate.structure]}</h2>
          <p>{VIEWPOINT_LABELS[candidate.viewpoint]} · {candidate.expiry_date}</p></div><button className="desk-icon-button" onClick={() => onRemove(candidate.candidate_id)} type="button" aria-label={`移除${STRUCTURE_LABELS[candidate.structure]}`}>×</button></header>
        <CandidateLegs candidate={candidate} detailed />
        <dl className="desk-comparison-metrics"><div><dt>净权利金参考</dt><dd>{deskNumber(candidate.economics.net_entry_cash)} USDC</dd></div>
          <div><dt>入场费用预算</dt><dd>{deskNumber(candidate.economics.entry_fees)} USDC</dd></div>
          <div><dt>从中间价到双边报价的差额</dt><dd>{deskNumber(candidate.economics.mid_to_touch_drag)} USDC</dd></div>
          <div><dt>期权到期收益损失边界</dt><dd>{deskNumber(candidate.economics.option_payoff_loss_bound)} USDC</dd></div></dl>
        <p className="desk-risk-scope">期权收益损失边界不含入场、退出及交割费用，不是含费实际损失上限。结构比例是比较口径，不是推荐手数。</p>
        <details className="desk-evidence-details"><summary>研究证据与失效条件</summary><div><p>假设 <code>{candidate.assumptions_id}</code></p>
          {candidate.reasons.map((reason) => <p key={reason.code}>{reason.detail} <code>{reason.code}</code></p>)}
          {candidate.invalidation.map((reason) => <p key={reason.code}>{reason.detail}</p>)}
          <p>建议复核 {deskTime(candidate.recheck_at)}</p></div></details>
      </article>)}
    </div>

    <section className="desk-scenario-panel" aria-labelledby="desk-scenario-title"><div className="desk-section-heading"><div><h2 id="desk-scenario-title">共同情景</h2>
      <p>价格、时间与 IV 对所有结构同时生效；到期图与到期前模型压力分开解释。</p></div></div>
      <form onSubmit={(event) => { event.preventDefault(); onRunComparison(); }}><div className="desk-scenario-controls">
        <label>标的价格变化 <output>{scenario.price_change_pct > 0 ? "+" : ""}{scenario.price_change_pct}%</output>
          <input aria-label="标的价格变化百分比" type="range" min={-40} max={40} step={1} value={scenario.price_change_pct}
            onChange={(event) => onScenarioChange({ ...scenario, price_change_pct: Number(event.currentTarget.value) })} /></label>
        <label>经过时间 <output>{scenario.time_days} 天</output><input aria-label="经过时间天数" type="range" min={0} max={maximumDays} step={1} value={Math.min(scenario.time_days, maximumDays)}
          onChange={(event) => onScenarioChange({ ...scenario, time_days: Number(event.currentTarget.value) })} /></label>
        <label>IV 平移 <output>{scenario.iv_shift_points > 0 ? "+" : ""}{scenario.iv_shift_points} 个百分点</output>
          <input aria-label="IV平移百分点" type="range" min={-20} max={20} step={1} value={scenario.iv_shift_points}
            onChange={(event) => onScenarioChange({ ...scenario, iv_shift_points: Number(event.currentTarget.value) })} /></label>
        <button className="desk-button desk-button-primary" disabled={expired || busy} type="submit">{busy ? "正在计算…" : matches ? "更新情景比较" : "计算共同情景"}</button>
      </div></form>
      {scenarioAdjusted || scenarioChanged ? <p className="desk-action-feedback" role="status">情景已调整，请重新计算共同情景。{scenarioChanged ? "下方仍是上次计算结果，更新后再保存或复制。" : ""}</p> : null}
      {!comparison || !matches ? <div className="desk-chart-placeholder" role="status">{busy ? "正在按相同报价、费用和情景核验各结构…" : "计算后显示条件到期图和到期前模型压力。"}</div> : <>
        <div className="desk-chart-heading"><h3>条件到期损益</h3><span>不受当前时间 / IV 平移影响</span></div>
        <ExpiryComparisonChart candidates={candidates} comparison={comparison} spot={desk.market.index_price} />
        <p className="desk-chart-caption">使用本次结构比例与双边报价，按列明入场费与标准交割费计算；实际费率与结算价需复核。条件曲线解释结构，不代表实际成交或未来收益。</p>
        <div className="desk-chart-heading"><h3>到期前模型压力</h3><span>价格 {comparison.scenario.price_change_pct}% · 时间 {comparison.scenario.time_days} 天 · IV {comparison.scenario.iv_shift_points} 点</span></div>
        <div className="desk-stress-grid">{candidates.map((candidate, index) => {
          const member = comparison.members.find((item) => item.candidate_id === candidate.candidate_id)!;
          return <div key={member.candidate_id}><p><span style={{ color: COLORS[index % COLORS.length] }}>{index + 1}</span> · {STRUCTURE_LABELS[candidate.structure]}</p>
          <strong>{member.stress ? `${deskNumber(member.stress.hypothetical_pnl)} USDC` : "模型值不可用"}</strong><small>{member.stress ? "共同假设下的理论损益，不是预计利润" : member.stress_reason ?? "报价 IV 或模型输入不足"}</small></div>;
        })}</div>
        <details className="desk-evidence-details"><summary>本次共同假设与分析身份</summary><div><ul>{comparison.assumptions.map((assumption, index) => <li key={index}>{assumption}</li>)}</ul>
          <p>快照 <code>{comparison.snapshot_id}</code></p><p>情景 <code>{comparison.scenario_id}</code></p><p>假设 <code>{comparison.assumptions_id}</code></p>
          <p>计算于 {deskTime(comparison.generated_at)} · 快照有效至 {deskTime(desk.expires_at)}</p></div></details>
      </>}
    </section>

    <section className="desk-decision-panel" aria-labelledby="desk-decision-title"><div className="desk-section-heading"><div><h2 id="desk-decision-title">留下你的研究判断</h2>
      <p>选择一个结构继续观察，把选腿、原始报价和比较假设一并保留在此浏览器本地。</p></div></div>
      <form onSubmit={(event) => { event.preventDefault(); if (chosenId && canUse) onSave(chosenId, note.trim()); }}>
        <fieldset className="desk-decision-options"><legend>继续观察哪一个？</legend>{candidates.map((candidate, index) => <label key={candidate.candidate_id}>
          <input type="radio" name="desk-choice" value={candidate.candidate_id} checked={chosenId === candidate.candidate_id} onChange={() => setChosenId(candidate.candidate_id)} />
          <span>{index + 1} · {STRUCTURE_LABELS[candidate.structure]}</span></label>)}</fieldset>
        <label className="desk-note-label">选择依据 <span>可选，不填也能保存</span><textarea rows={3} maxLength={600} value={note}
          placeholder="例如：更重视保护翼距离；等待双边价差收窄后复核。" onChange={(event) => setNote(event.currentTarget.value)} /></label>
        <div className="desk-decision-actions"><button className="desk-button desk-button-primary" disabled={!chosenId || !canUse} type="submit">保存到本地观察</button>
          {chosenId && comparison && matches ? <CopyReview text={buildDeskResearchCopy(desk, candidates.find((candidate) => candidate.candidate_id === chosenId)!, comparison)} disabled={!canUse}
            current={() => !deskExpired(desk, Date.now()) && candidates.every((candidate) => candidateComparable(candidate))} /> : <p className="desk-muted">暂不选择也是合理判断；不会自动生成订单。</p>}</div>
      </form>
    </section>
  </main>;
}
