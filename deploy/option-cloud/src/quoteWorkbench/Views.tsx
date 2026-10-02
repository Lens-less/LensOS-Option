import { useEffect, useId, useState } from 'react';
import { expiryPnl } from './payoff';
import type { Candidate, Criteria } from './engine';
import { EXCLUSION_LABELS, makeCandidate } from './engine';
import type { DecisionPlan, PlanDecision, ReviewEvidence } from './plans';
import { downloadText } from './samples';

export const money=(value:number|null|undefined,digits=2):string=>value===null?'无有限界限':value===undefined?'—':value.toLocaleString('zh-CN',{maximumFractionDigits:digits});
export const when=(value:string|null):string=>value?new Date(value).toISOString().replace('T',' ').replace('.000Z',' UTC'):'未提供';
export const expiryLabel=(value:string):string=>new Date(value).toISOString().slice(0,16).replace('T',' ')+' UTC';
export const structureName=(candidate:Pick<Candidate,'direction'>):string=>candidate.direction==='bullish'?'牛市看跌信用价差':'熊市看涨信用价差';
export const shortName=(candidate:Candidate):string=>`${money(candidate.short.strike,4)} / ${money(candidate.long.strike,4)}`;
export const breakeven=(candidate:Candidate):string=>[...candidate.profile.breakevens.map(value=>money(value,4)),
  ...candidate.profile.zeroRanges.map(range=>`${money(range.from,4)}–${range.to===null?'∞':money(range.to,4)}`)].join('、')||'无';
export function RiskScope():React.JSX.Element{return <p className="q-risk-note">损失界限只适用于各自到期、完整保护腿及配置的固定费用。未覆盖动态交割费、清算费、保证金需求、滑点与提前平仓风险；这里没有胜率、预测收益或下单建议。</p>;}

export function LegsTable({candidate}:{candidate:Candidate}):React.JSX.Element {
  return <div className="q-table-scroll"><table className="q-table q-leg-table"><caption>{candidate.contracts} 份结构 = 卖 {candidate.contracts} 张 + 买 {candidate.contracts} 张；每张乘数 {candidate.multiplier}</caption>
    <thead><tr><th>方向 / 原 CSV 行</th><th>精确合约</th><th>Bid / Ask</th><th>报价时刻 UTC</th><th>可见数量</th></tr></thead><tbody>
      {[{row:candidate.short,side:'卖出',size:candidate.short.bidSize},{row:candidate.long,side:'买入',size:candidate.long.askSize}].map(({row,side,size})=><tr key={row.instrument}>
        <td><span className={side==='卖出'?'q-sell':'q-buy'}>{side} {candidate.contracts} 张</span><small>原第 {row.row} 行</small></td><td>{row.instrument}<small>{row.optionType==='put'?'看跌':'看涨'} · K {money(row.strike,4)} · {expiryLabel(row.expiry)}</small></td>
        <td>{money(row.bid,6)} / {money(row.ask,6)}<small>{row.currency} / 基础资产单位{row.quoteUnit==='per_contract'?` · 原每张 ${row.rawBid} / ${row.rawAsk}`:''}</small></td>
        <td>{when(row.quotedAt)}<small>{row.tickSize===null?'最小跳动未提供':`原报价最小跳动 ${row.tickSize}`}</small></td><td>{size===null?'未知，不能判断容量':`${money(size,4)} 张`}</td></tr>)}</tbody></table></div>;
}

function ExpiryChart({candidates,price}:{candidates:Candidate[];price:number}):React.JSX.Element {
  const id=useId();const strikes=candidates.flatMap(c=>[c.long.strike,c.short.strike]);const min=Math.max(0,Math.min(...strikes)*.85),max=Math.max(...strikes)*1.15;
  const prices=[...new Set([min,...strikes,...candidates.flatMap(c=>c.profile.breakevens),max])].filter(p=>p>=min&&p<=max).sort((a,b)=>a-b);
  const curves=candidates.map(c=>prices.map(p=>({price:p,pnl:expiryPnl(c.legs,p,c.netCredit,c.expiryFees)})));
  const lo=Math.min(0,...curves.flatMap(c=>c.map(p=>p.pnl)));const hi=Math.max(0,...curves.flatMap(c=>c.map(p=>p.pnl)));
  const x=(p:number)=>60+(p-min)/(max-min||1)*840;const y=(p:number)=>28+(hi-p)/(hi-lo||1)*210;
  return <figure className="q-payoff"><svg viewBox="0 0 940 295" role="img" aria-labelledby={id}><title id={id}>各结构在各自到期日的条件损益；含配置固定费用，不是未来预测</title>
    {[hi,0,lo].filter((v,i,a)=>a.indexOf(v)===i).map(tick=><g key={tick}><line x1="60" x2="900" y1={y(tick)} y2={y(tick)} className={tick===0?'q-zero-line':'q-grid-line'} /><text x="50" y={y(tick)+4} textAnchor="end">{money(tick,0)}</text></g>)}
    {curves.map((curve,i)=><path key={candidates[i].id} d={curve.map((point,j)=>`${j?'L':'M'}${x(point.price)},${y(point.pnl)}`).join(' ')} fill="none" stroke={['#117859','#3f67c3','#b16c20'][i]} strokeWidth="3" strokeDasharray={i===2?'8 4':undefined} />)}
    {price>=min&&price<=max?<line x1={x(price)} x2={x(price)} y1="22" y2="242" stroke="#68726d" strokeDasharray="3 5" />:null}
    {[min,(min+max)/2,max].map((tick,i)=><text key={tick} x={x(tick)} y="264" textAnchor={i===0?'start':i===2?'end':'middle'}>{money(tick,0)}</text>)}
    <text x="900" y="288" textAnchor="end">假设到期标的价格 · {candidates[0].currency}</text></svg>
    <figcaption>{candidates.map((c,i)=><span key={c.id}><i style={{background:['#117859','#3f67c3','#b16c20'][i]}} />{i+1} · {shortName(c)} · {expiryLabel(c.expiry)}</span>)}</figcaption></figure>;
}

export function ComparePanel({candidates,criteria,onRemove,onBack,onSave}:{candidates:Candidate[];criteria:Criteria;onRemove:(id:string)=>void;onBack:()=>void;onSave:(candidate:Candidate,note:string)=>void}):React.JSX.Element {
  const key=candidates.map(c=>c.id).join('|');const [price,setPrice]=useState(0);const [chosen,setChosen]=useState('');const [note,setNote]=useState('');
  useEffect(()=>{setPrice(candidates.length?candidates.reduce((s,c)=>s+c.short.strike,0)/candidates.length:0);setChosen('');setNote('');},[key]);
  if(candidates.length<2)return <section className="q-empty"><span>⇄</span><h2>先选择同一方向的两个候选</h2><p>最多比较三个。跨期限时分别解释各自到期损益，不叠加仓位、不比较虚构年化收益。</p><button className="q-button q-primary" onClick={onBack}>回到候选列表</button></section>;
  return <section className="q-compare"><div className="q-section-heading"><div><span className="q-eyebrow">03 / 同方向比较</span><h1>相同假设，看看你更在意什么</h1><p>{structureName(candidates[0])} · {criteria.asset} / {criteria.currency} · 每张乘数 {criteria.multiplier} · {criteria.contracts} 份结构</p></div><button className="q-button" onClick={onBack}>调整候选</button></div>
    <div className="q-selected-cards">{candidates.map((c,i)=><article key={c.id}><button className="q-remove" aria-label={`移除比较 ${shortName(c)}`} onClick={()=>onRemove(c.id)}>×</button><span className="q-eyebrow">候选 {i+1}</span><h3>{shortName(c)}</h3><p>卖腿 / 买腿执行价</p><small>{expiryLabel(c.expiry)}</small></article>)}</div>
    <div className="q-panel"><div className="q-table-scroll"><table className="q-table q-compare-table"><caption>总现金额 · {criteria.currency} · 都按 {criteria.contracts} 份结构计算</caption><thead><tr><th>口径</th>{candidates.map((c,i)=><th key={c.id}>候选 {i+1}</th>)}</tr></thead><tbody>
      <tr><th>净入场现金（扣入场费）</th>{candidates.map(c=><td key={c.id}>{money(c.netCredit)}</td>)}</tr>
      <tr><th>配置费用下的到期损失界限</th>{candidates.map(c=><td key={c.id}>{money(c.profile.maxLoss)}</td>)}</tr>
      <tr><th>配置费用下的最佳到期结果</th>{candidates.map(c=><td key={c.id}>{money(c.profile.bestPnl)}</td>)}</tr>
      <tr><th>到期盈亏平衡价格</th>{candidates.map(c=><td key={c.id}>{breakeven(c)}</td>)}</tr>
      <tr><th>入场 / 到期固定费用</th>{candidates.map(c=><td key={c.id}>{money(c.entryFees)} / {money(c.expiryFees)}</td>)}</tr>
      <tr><th>两腿报价间隔</th>{candidates.map(c=><td key={c.id}>{money(c.quoteGapSeconds)} 秒<small>{c.capacityKnown?'当前可见数量满足填写的份数':'有数量缺失，容量未知'}</small></td>)}</tr>
    </tbody></table></div><p className="q-muted">净入场现金不是净利润。卖腿取 Bid、买腿取 Ask；把两条腿拼在一起不保证能同时成交。</p><RiskScope /></div>
    <div className="q-panel"><div className="q-section-heading"><div><h2>各自到期日的条件损益</h2><p>改变到期价格，直接计算内在价值。跨期限曲线不是同一时刻的估值；不计算到期前时间价值。</p></div>
      <label className="q-price-input">假设到期价格<input type="number" min="0" max="1000000000" step="any" value={price} onChange={e=>setPrice(Number(e.target.value))} /></label></div>
      {new Set(candidates.map(c=>c.expiry)).size===1?<ExpiryChart candidates={candidates} price={Number.isFinite(price)&&price>=0?price:0} />:
        <div className="q-separate-expiries"><p className="q-muted">期限不同，分开作图。下列价格只作独立敏感度假设，不表示这些到期日会达到同一价格，不能视为同一时点的估值。</p>
          {candidates.map((candidate,i)=><section key={candidate.id}><h3>候选 {i+1} · 单独到期 {expiryLabel(candidate.expiry)}</h3><ExpiryChart candidates={[candidate]} price={Number.isFinite(price)&&price>=0?price:0} /></section>)}</div>}
      <div className="q-scenario-values">{candidates.map((c,i)=><div key={c.id}><span>候选 {i+1} · {expiryLabel(c.expiry)}</span><strong>{Number.isFinite(price)&&price>=0?money(expiryPnl(c.legs,price,c.netCredit,c.expiryFees)):'请输入有效价格'} <small>{criteria.currency}</small></strong></div>)}</div>
    </div>
    <div className="q-panel q-save-panel"><span className="q-eyebrow">冻结理由，不是下单</span><h2>留下这次研究判断</h2><p>只保存你选中的精确合约与原报价，之后可用下一份 CSV 复核；不是实际持仓。</p>
      <fieldset><legend>继续研究哪一个？</legend>{candidates.map((c,i)=><label className="q-choice" key={c.id}><input type="radio" name="chosen-plan" value={c.id} checked={chosen===c.id} onChange={()=>setChosen(c.id)} />候选 {i+1} · {shortName(c)}</label>)}</fieldset>
      <label className="q-note-label">选择理由或尚待验证的问题<textarea rows={3} maxLength={2000} value={note} onChange={e=>setNote(e.target.value)} placeholder="例如：同方向下优先控制理论到期损失，仍需核对真实费用与两腿成交能力。" /></label>
      <button className="q-button q-primary" disabled={!chosen||!note.trim()} onClick={()=>{const c=candidates.find(item=>item.id===chosen);if(c)onSave(c,note);}}>冻结为研究计划</button>
    </div>
    <div className="q-panel"><h2>逐腿核对原始证据</h2>{candidates.map((c,i)=><details className="q-evidence" key={c.id}><summary>候选 {i+1} · {shortName(c)} · {expiryLabel(c.expiry)}</summary><LegsTable candidate={c} /></details>)}</div>
  </section>;
}

const DECISION_LABELS:Record<PlanDecision,string>={continue:'继续观察',revise:'需要改版',abandon:'放弃研究'};
export function PlanDetail({plan,review,onReview,onEvent}:{plan:DecisionPlan;review:ReviewEvidence|null;onReview:()=>void;onEvent:(decision:PlanDecision,note:string,review:ReviewEvidence|null)=>boolean}):React.JSX.Element {
  const original=makeCandidate(plan.long,plan.short,plan.criteria);const [decision,setDecision]=useState<PlanDecision>('continue');const [note,setNote]=useState('');
  const [showOriginal,setShowOriginal]=useState(false);
  useEffect(()=>{setDecision('continue');setNote('');},[plan.id]);
  const latest=plan.events[plan.events.length-1];
  return <article className="q-plan-detail"><div className="q-section-heading"><div><span className="q-pill">研究计划 · {latest?DECISION_LABELS[latest.decision]:'待复核'}</span><h2>{plan.criteria.asset} · {shortName(original)}</h2><p>{structureName(original)} · {expiryLabel(original.expiry)} · {plan.source.synthetic?'合成演练':'用户文件'}</p></div>
      <button className="q-button" onClick={()=>downloadText(`option-plan-${plan.id.slice(0,8)}.json`,JSON.stringify(plan,null,2),'application/json')}>导出计划 JSON ↗</button></div>
    <div className="q-frozen"><span className="q-eyebrow">原始判断永久保留</span><p>{plan.rationale}</p><small>冻结于 {when(plan.createdAt)} · 文件 {plan.source.name}</small></div>
    <div className="q-plan-facts"><div><span>原净入场现金</span><strong>{money(original.netCredit)} <small>{original.currency}</small></strong></div><div><span>原配置费用下到期损失界限</span><strong>{money(original.profile.maxLoss)} <small>{original.currency}</small></strong></div><div><span>原报价时点</span><strong className="q-time-value">{when(original.newestQuote)}</strong></div></div>
    <details className="q-evidence" open={showOriginal} onToggle={e=>setShowOriginal(e.currentTarget.open)}><summary>查看冻结合约、费用和文件标识</summary><LegsTable candidate={original} />
      <p>每张固定费用：入场 {money(plan.criteria.entryFee)} / 到期 {money(plan.criteria.expiryFee)} / 平仓 {money(plan.criteria.closeFee)} {original.currency}；数量 {original.contracts} 份。</p><p className="q-fingerprint">原文件 SHA-256：{plan.source.id}</p><p>原研究时点 {when(plan.criteria.asOf)}；最小净现金 {money(plan.criteria.minCredit)}，到期损失限额 {money(plan.criteria.maxLoss)} {original.currency}。</p></details>
    <RiskScope />
    <section className="q-plan-review"><div className="q-section-heading"><div><span className="q-eyebrow">下一份证据</span><h3>同一合约现在发生了什么变化？</h3><p>必须是原合约、原单位且晚于已保存报价；不会换成另一笔结构。</p></div><button className="q-button q-primary" onClick={onReview}>选择下一份报价 CSV</button></div>
      {review?<div className={review.status==='matched'?'q-review-ready':'q-alert'} role="status"><strong>{review.status==='matched'?'精确合约匹配，等待你记录判断':'本次不能形成完整复核'}</strong><p>{review.source.name} · {when(review.source.lastQuote)}</p>
        {review.reasons.map((reason,i)=><p key={i}>{reason}</p>)}
        {review.status==='matched'&&review.newCandidate?<><div className="q-table-scroll"><table className="q-table"><caption>原始 → 新报价变化，不是实际成交</caption><thead><tr><th>项目</th><th>冻结值</th><th>新快照</th></tr></thead><tbody>
          <tr><th>卖腿 Bid / Ask</th><td>{money(plan.short.bid,6)} / {money(plan.short.ask,6)}</td><td>{money(review.short?.bid,6)} / {money(review.short?.ask,6)}</td></tr>
          <tr><th>买腿 Bid / Ask</th><td>{money(plan.long.bid,6)} / {money(plan.long.ask,6)}</td><td>{money(review.long?.bid,6)} / {money(review.long?.ask,6)}</td></tr>
          <tr><th>按相同条件重新建立的净入场现金</th><td>{money(original.netCredit)}</td><td>{money(review.newCandidate.netCredit)}</td></tr>
          <tr><th>重新建立的到期损失界限</th><td>{money(original.profile.maxLoss)}</td><td>{money(review.newCandidate.profile.maxLoss)}</td></tr>
        </tbody></table></div><p><strong>按新 Bid / Ask 反向平仓的净现金参考：{review.closeReference===null?'暂不提供（平仓方向数量不足）':`${money(review.closeReference)} ${original.currency}`}</strong>（含原配置平仓费，负数表示支付现金）</p>
          {review.referenceChange!==null?<p>原入场参考 + 新反向现金参考 = {money(review.referenceChange)} {original.currency}。这是报价参考差额；没有实际成交记录，不是持仓或已实现盈亏。</p>:null}
          <p>{review.criteriaFailure?`已不满足原条件：${EXCLUSION_LABELS[review.criteriaFailure]??review.criteriaFailure}`:'在原设置下仍满足筛选条件；这不是继续交易的建议。'}</p></>:null}
      </div>:<p className="q-muted">尚未载入下一份 CSV。文件不会自动刷新，原判断不会被新报价覆盖。</p>}
      <div className="q-review-form"><label>本次研究状态<select value={decision} onChange={e=>setDecision(e.target.value as PlanDecision)}>{(Object.keys(DECISION_LABELS) as PlanDecision[]).map(d=><option key={d} value={d}>{DECISION_LABELS[d]}</option>)}</select></label>
        <label>记录理由<textarea rows={3} maxLength={2000} value={note} onChange={e=>setNote(e.target.value)} placeholder="哪些条件变了？继续观察、需要改版或放弃的理由是什么？" /></label>
        <button className="q-button q-primary" disabled={!note.trim()} onClick={()=>{if(onEvent(decision,note,review))setNote('');}}>追加一条记录，不覆盖原版</button></div>
    </section>
    {plan.events.length?<section className="q-history"><h3>研究版本历史 · {plan.events.length} 次</h3><ol>{[...plan.events].reverse().map((event,i)=><li key={event.id}><div><strong>V{plan.events.length-i+1} · {DECISION_LABELS[event.decision]}</strong><time>{when(event.at)}</time></div><p>{event.note}</p>
      {event.review?<small>{event.review.status==='matched'?'精确匹配复核':'复核被阻断'} · {event.review.source.name} · {when(event.review.source.lastQuote)}</small>:<small>判断追加，未导入新报价</small>}</li>)}</ol></section>:null}
  </article>;
}
