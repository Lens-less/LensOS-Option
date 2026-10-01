import { useEffect, useRef, useState } from "react";

import { CandidateLegs, STRUCTURE_LABELS, VIEWPOINT_LABELS, deskNumber, deskTime } from "./DiscoverWorkspace";
import {
  OBSERVE_CONFLICT_MESSAGE, ObserveStorageConflictError,
  appendObservationNote, appendObservationReview, archiveObservation, loadObserveState, removeObservation,
  type ObservationRecord, type ObservationReviewEvent, type ObserveState,
} from "./observeStore";
import type { DeskCandidate, DeskReview } from "./types";

export interface ObserveWorkspaceProps {
  state: ObserveState;
  onChange: (state: ObserveState) => void;
  onReview: (record: ObservationRecord) => Promise<DeskReview>;
  storageError?: string | null;
}

export function ObserveWorkspace({ state, onChange, onReview, storageError }: ObserveWorkspaceProps): React.JSX.Element {
  const [showArchived, setShowArchived] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const visible = state.records.filter((record) => record.archived === showArchived);
  const selected = visible.find((record) => record.id === selectedId) ?? visible[0];
  const activeCount = state.records.filter((record) => !record.archived).length;
  const archivedCount = state.records.length - activeCount;
  const canReload = conflict || (!error && storageError === OBSERVE_CONFLICT_MESSAGE);

  function showError(message: string | null, isConflict = false): void {
    setError(message); setConflict(isConflict);
  }

  function reload(): void {
    const latest = loadObserveState();
    if (latest.error) { showError(latest.error, true); return; }
    onChange(latest.state); showError(null);
  }

  function mutate(action: () => ObserveState): void {
    try { onChange(action()); showError(null); }
    catch (failure) { showError(failure instanceof Error ? failure.message : "操作未保存，请检查浏览器的本地存储。", failure instanceof ObserveStorageConflictError); }
  }

  return <main className="desk-workspace" id="decision-desk-main">
    <div className="desk-workspace-heading"><div><p className="desk-eyebrow">03 · 观察</p>
      <h1>保留当时的判断，复核同一组合</h1>
      <p>原始快照、完整合约腿与比较假设固定保存。新报价和后续笔记另记一条，便于看清判断如何变化。</p></div>
      <span className="desk-quiet-label">仅保存在此浏览器 · 无账户同步</span></div>
    {storageError || error ? <div className="desk-notice" role="alert"><p>{error ?? storageError}</p>
      {canReload ? <button className="desk-button desk-button-secondary" type="button" onClick={reload}>重新读取观察</button> : null}
    </div> : null}
    <div className="desk-results-toolbar"><div className="desk-segmented" aria-label="观察记录范围">
      <button type="button" aria-pressed={!showArchived} onClick={() => { setShowArchived(false); setSelectedId(null); }}>观察中 {activeCount}</button>
      <button type="button" aria-pressed={showArchived} onClick={() => { setShowArchived(true); setSelectedId(null); }}>已归档 {archivedCount}</button>
    </div><p>报价变化用于研究复盘，不代表实际持仓或已实现盈亏。</p></div>
    {visible.length === 0 ? <section className="desk-empty" role="status"><span aria-hidden="true">○</span>
      <h2>{showArchived ? "还没有归档记录" : "从一个看清楚的结构开始"}</h2>
      <p>{showArchived ? "明确归档后，记录与复盘仍完整保留在这里。" : "在发现中挑选结构，完成同口径比较，再保存你愿意持续复核的组合与判断。"}</p>
      <p>清除浏览器数据会移除这些记录；本地笔记不会发送到研究服务。</p>
    </section> : <div className="desk-observe-layout">
      <nav className="desk-observe-list" aria-label="已保存的观察记录">
        {visible.map((record) => {
          const candidate = record.desk.candidates.find((item) => item.candidate_id === record.candidate_id)!;
          return <button className="desk-observe-record" type="button" key={record.id}
            data-selected={record.id === selected?.id} aria-pressed={record.id === selected?.id} onClick={() => setSelectedId(record.id)}>
            <span>{record.desk.asset} · {VIEWPOINT_LABELS[record.viewpoint]}</span>
            <strong>{STRUCTURE_LABELS[candidate.structure]}</strong><span>{candidate.expiry_date} 到期</span>
            <small>保存于 {deskTime(record.saved_at)}</small>
          </button>;
        })}
      </nav>
      {selected ? <ObservationDetail key={selected.id} record={selected} state={state} onReview={onReview}
        onChange={onChange} onError={showError} onMutate={mutate} /> : null}
    </div>}
  </main>;
}

function ObservationDetail({ record, state, onReview, onChange, onError, onMutate }: {
  record: ObservationRecord;
  state: ObserveState;
  onReview: ObserveWorkspaceProps["onReview"];
  onChange: ObserveWorkspaceProps["onChange"];
  onError: (error: string | null, conflict?: boolean) => void;
  onMutate: (action: () => ObserveState) => void;
}): React.JSX.Element {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [nowMs, setNowMs] = useState(Date.now);
  const mounted = useRef(true);
  const stateRef = useRef(state);
  useEffect(() => { stateRef.current = state; }, [state]);
  useEffect(() => {
    mounted.current = true;
    const timer = globalThis.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => { mounted.current = false; globalThis.clearInterval(timer); };
  }, []);
  const candidate = record.desk.candidates.find((item) => item.candidate_id === record.candidate_id)!;
  const events = state.reviews.filter((event) => event.observation_id === record.id);
  const latestReview = events.find((event) => event.kind === "review")?.review;
  const member = record.comparison?.members.find((item) => item.candidate_id === record.candidate_id);
  const scenario = record.comparison?.scenario;
  const expired = nowMs >= candidate.expiration_timestamp;

  async function review(): Promise<void> {
    setBusy(true); onError(null);
    let result: DeskReview;
    try { result = await onReview(record); }
    catch {
      result = {
        schema_version: "desk_review.v1", reviewed_at: new Date().toISOString(),
        original_snapshot_id: record.desk.snapshot_id, original_candidate_id: record.candidate_id,
        reviewed_candidate_id: null, desk: null, status: "unavailable",
        reasons: [{ code: "REVIEW_UNAVAILABLE", detail: "此次未能取得同一组合的新报价。原始记录保留，可以稍后重试。" }],
      };
    }
    if (!mounted.current) return;
    try {
      onChange(appendObservationReview(stateRef.current, record.id, result));
    } catch (failure) {
      onError(failure instanceof Error ? failure.message : "复查结果未保存，原始记录保持不变。", failure instanceof ObserveStorageConflictError);
    }
    setBusy(false);
  }

  function saveNote(): void {
    try {
      onChange(appendObservationNote(state, record.id, note));
      setNote(""); onError(null);
    } catch (failure) {
      onError(failure instanceof Error ? failure.message : "复盘笔记未保存，请检查浏览器存储。", failure instanceof ObserveStorageConflictError);
    }
  }

  return <article className="desk-observe-detail" aria-label="观察记录详情">
    <div className="desk-opportunity-heading"><div><span className="desk-pill" data-tone="neutral">{record.archived ? "已归档" : "原始研究记录"}</span>
      <h2>{record.desk.asset} · {STRUCTURE_LABELS[candidate.structure]}</h2>
      <p>{candidate.expiry_date} 到期 · {VIEWPOINT_LABELS[record.viewpoint]}观点 · {record.desk.source.mode === "demo" ? "离线示例" : record.desk.source.mode === "replay" ? "历史回放" : "公共行情"}</p></div>
      <button className="desk-button desk-button-primary" type="button" disabled={busy} onClick={() => void review()}>
        {busy ? "正在复核同一组合…" : expired ? "核对到期状态" : "复核同一组合"}</button></div>
    <p className="desk-filter-help">只重新查询这些合约。合约到期或报价缺失时，保留原始腿，不替换为新结构。</p>
    <section aria-labelledby={`observe-original-${record.id}`}><h3 id={`observe-original-${record.id}`}>保存时的完整合约</h3>
      <CandidateLegs candidate={candidate} detailed />
      <dl className="desk-facts">
        <div><dt>当时标的参考价</dt><dd>{deskNumber(record.desk.market.index_price)} USDC</dd></div>
        <div><dt>结构权利金参考</dt><dd>{deskNumber(candidate.economics.entry_cash)} USDC</dd></div>
        <div><dt>入场费用假设</dt><dd>{deskNumber(candidate.economics.entry_fees)} USDC</dd></div>
        <div><dt>期权到期损失边界</dt><dd>{deskNumber(candidate.economics.option_payoff_loss_bound)} USDC</dd></div>
      </dl>
      <p className="desk-filter-help">金额按保存的结构比例计算，不含动态交割费用。合约单位与比例用于识别研究结构，不是账户手数。</p>
      <details className="desk-coverage"><summary>原始比较假设与证据标识</summary><div className="desk-coverage-body">
        <dl className="desk-facts"><div><dt>采集时刻</dt><dd>{deskTime(record.desk.source.captured_at)}</dd></div>
          <div><dt>评估时刻</dt><dd>{deskTime(record.desk.generated_at)}</dd></div>
          <div><dt>当时复核期限</dt><dd>{deskTime(candidate.recheck_at)}</dd></div>
          <div><dt>保存时刻</dt><dd>{deskTime(record.saved_at)}</dd></div></dl>
        {scenario ? <p>保存的压力假设：标的变化 {deskNumber(scenario.price_change_pct)}% · 时间推进 {deskNumber(scenario.time_days)} 天 · IV 偏移 {deskNumber(scenario.iv_shift_points)} 个百分点。</p> : <p>未保存情景比较。</p>}
        {member?.stress ? <p>当时模型情景损益 {deskNumber(member.stress.hypothetical_pnl)} USDC，仅为固定假设下的理论结果。</p> : member ? <p>当时压力模型不可计算：{member.stress_reason ?? "证据不足"}。</p> : null}
        {record.comparison?.assumptions.map((assumption, index) => <p key={index}>{assumption}</p>)}
        <p>来源 <code>{record.desk.source.provider}</code></p><p>快照 <code>{record.desk.snapshot_id}</code></p>
        <p>分析 <code>{record.desk.analysis_id}</code></p><p>结构假设 <code>{candidate.assumptions_id}</code></p>
        {record.comparison ? <p>比较假设 <code>{record.comparison.assumptions_id}</code> · 情景 <code>{record.comparison.scenario_id}</code></p> : null}
        {candidate.invalidation.map((reason) => <p key={reason.code}>失效条件：{reason.detail} <code>{reason.code}</code></p>)}
      </div></details>
    </section>
    <section className="desk-observe-note" aria-labelledby={`observe-judgment-${record.id}`}><h3 id={`observe-judgment-${record.id}`}>当时的判断</h3>
      <p className="desk-original-note">{record.note || "保存时未填写判断。"}</p></section>
    <section aria-label="最新复核"><h3>同一组合的最新复核</h3>
      {latestReview ? <ReviewSummary review={latestReview} original={candidate} nowMs={nowMs} /> : <div className="desk-notice" role="note">
        尚未复核。上方报价与判断属于保存时的原始快照，不会自动变成当前行情。</div>}
    </section>
    <form className="desk-observe-note" onSubmit={(event) => { event.preventDefault(); saveNote(); }}>
      <label htmlFor={`observe-note-${record.id}`}><strong>追加复盘笔记</strong><span>记录观点、失效条件或下一次关注点；原判断继续保留。</span></label>
      <textarea id={`observe-note-${record.id}`} maxLength={2_000} rows={3} value={note} disabled={busy}
        placeholder="例如：观点仍成立，但双边价差扩大，下次先复核报价质量。"
        onChange={(event) => setNote(event.currentTarget.value)} />
      <div className="desk-observe-actions"><small>{note.length} / 2000 · 笔记仅存在此浏览器</small>
        <button className="desk-button desk-button-secondary" type="submit" disabled={busy || !note.trim()}>保存复盘笔记</button></div>
    </form>
    {events.length ? <details className="desk-coverage"><summary>复盘记录 <span>{events.length} 条 · 原始判断未改写</span></summary>
      <ol className="desk-observe-timeline">{events.map((event) => <ReviewEvent key={event.id} event={event} />)}</ol>
    </details> : null}
    <div className="desk-observe-actions"><p>归档保留完整记录。删除会移除此组合及其复盘笔记。</p>
      <div><button type="button" className="desk-button desk-button-secondary" disabled={busy}
        onClick={() => onMutate(() => archiveObservation(state, record.id, !record.archived))}>{record.archived ? "恢复观察" : "归档此记录"}</button>
        <button type="button" className="desk-button desk-button-quiet" disabled={busy} onClick={() => setConfirmRemove(true)}>删除此记录</button></div></div>
    {confirmRemove ? <div className="desk-notice" role="alert"><p>将删除此观察记录和全部复盘笔记，此操作无法撤销。</p>
      <div className="desk-observe-actions"><button type="button" className="desk-button desk-button-secondary" onClick={() => setConfirmRemove(false)}>保留记录</button>
        <button type="button" className="desk-button desk-button-danger" disabled={busy} onClick={() => onMutate(() => removeObservation(state, record.id))}>确认删除记录</button></div>
    </div> : null}
  </article>;
}

function ReviewSummary({ review, original, nowMs }: { review: DeskReview; original: DeskCandidate; nowMs: number }): React.JSX.Element {
  const current = review.desk?.candidates.find((candidate) => candidate.candidate_id === review.reviewed_candidate_id);
  const stale = review.status === "current" && review.desk !== null && (
    nowMs >= Date.parse(review.desk.expires_at) || nowMs >= original.expiration_timestamp
      || (current !== undefined && nowMs >= Date.parse(current.recheck_at))
  );
  const blocked = review.status === "current" && (!current || current.status !== "comparable"
    || review.desk?.qualification.data_status === "stale" || review.desk?.qualification.data_status === "unavailable");
  const status = stale ? "expired" : blocked ? "unavailable" : review.status;
  const title = status === "current" ? "已取得同一合约的新报价" : status === "expired" ? "已到期或本次报价已过复核期限" : "暂未取得可复核的新报价";
  return <div className="desk-review-summary"><div className="desk-notice" role="status"><strong>{title}</strong>
    <p>复核于 {deskTime(review.reviewed_at)}。{status !== "current" ? "原始记录完整保留，不能据此判断当前可比较性。" : "下表只描述双边报价变化，不计算实际持仓盈亏。"}</p>
    {review.desk ? <p>本次来源：{review.desk.source.mode === "demo" ? "离线合成样例" : review.desk.source.mode === "replay" ? "历史回放" : "公共行情"}
      · {review.desk.source.provider} · 采集于 {deskTime(review.desk.source.captured_at)}。</p> : null}
    {review.reasons.map((reason, index) => <p key={`${reason.code}:${index}`}>{reason.detail} <code>{reason.code}</code></p>)}</div>
    {current && status === "current" ? <div className="desk-quote-table-wrap"><table className="desk-quote-table">
      <caption>同一合约的双边报价变化 · USDC</caption><thead><tr><th scope="col">合约</th><th scope="col">原 Bid / Ask</th><th scope="col">复核 Bid / Ask</th><th scope="col">复核报价时刻</th></tr></thead>
      <tbody>{original.legs.map((leg, index) => {
        const latest = current.legs[index];
        return <tr key={leg.instrument_name}><th scope="row">{leg.instrument_name}<small>{leg.side === "BUY" ? "买入腿" : "卖出腿"} · 比例 {leg.ratio}</small></th>
          <td>{quote(leg.bid)} / {quote(leg.ask)}</td><td>{quote(latest?.bid)} / {quote(latest?.ask)}</td>
          <td>{deskTime(latest?.quote_time ?? latest?.observed_at)}</td></tr>;
      })}</tbody></table></div> : null}
    {review.desk ? <p className="desk-filter-help">复核快照 <code>{review.desk.snapshot_id}</code> · 复核分析 <code>{review.desk.analysis_id}</code></p> : null}
  </div>;
}

function ReviewEvent({ event }: { event: ObservationReviewEvent }): React.JSX.Element {
  return <li><p><strong>{event.kind === "note" ? "追加判断" : "同组合复核"}</strong><time dateTime={event.saved_at}>{deskTime(event.saved_at)}</time></p>
    {event.kind === "note" ? <p className="desk-original-note">{event.note}</p> : <p>{event.review?.status === "current" ? "当次取得新报价" : event.review?.status === "expired" ? "当次到期或报价失效" : "当次报价不可用"}
      {event.review?.reasons.map((reason) => ` · ${reason.detail}`).join("")}</p>}</li>;
}

function quote(value: number | null | undefined): string { return typeof value === "number" && Number.isFinite(value) ? String(value) : "—"; }
