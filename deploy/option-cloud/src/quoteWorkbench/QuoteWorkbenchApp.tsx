import { useEffect, useMemo, useRef, useState } from 'react';
import { ImportPanel } from './ImportPanel';
import { quoteGroups, type QuoteSource } from './csv';
import { candidateFailure, discover, EXCLUSION_LABELS, initialCriteria, validateCriteria, type Candidate, type Criteria, type Discovery } from './engine';
import { appendPlanEvent, createPlan, importPlan, loadPlans, persistPlans, recheckPlan, type DecisionPlan, type PlanDecision, type ReviewEvidence } from './plans';
import { breakeven, ComparePanel, expiryLabel, LegsTable, money, PlanDetail, RiskScope, shortName, structureName, when } from './Views';
import { downloadText } from './samples';
import './workbench.css';

type Workspace='research'|'compare'|'plans';
export function QuoteWorkbenchApp():React.JSX.Element {
  const [workspace,setWorkspace]=useState<Workspace>('research');const [source,setSource]=useState<QuoteSource|null>(null);
  const [draft,setDraft]=useState<Criteria|null>(null);const [applied,setApplied]=useState<Criteria|null>(null);const [result,setResult]=useState<Discovery|null>(null);
  const [selected,setSelected]=useState<string[]>([]);const [feesConfirmed,setFeesConfirmed]=useState(false);const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState<string|null>(null);const [error,setError]=useState<string|null>(null);const [showImport,setShowImport]=useState(true);
  const [initialPlans]=useState(loadPlans);const [planState,setPlanState]=useState(initialPlans.state);const [storageError,setStorageError]=useState(initialPlans.error);
  const [selectedPlan,setSelectedPlan]=useState<string|null>(initialPlans.state.plans[0]?.id??null);const [pendingPlan,setPendingPlan]=useState<DecisionPlan|null>(null);
  const [reviewing,setReviewing]=useState<string|null>(null);const [reviewDraft,setReviewDraft]=useState<{planId:string;evidence:ReviewEvidence}|null>(null);
  const [sort,setSort]=useState('expiry');const [limit,setLimit]=useState(30);const importPlanRef=useRef<HTMLInputElement>(null);const run=useRef(0);
  const planImportSequence=useRef(0);const [planImportBusy,setPlanImportBusy]=useState(false);
  useEffect(()=>()=>{++planImportSequence.current;++run.current;},[]);
  const dirty=!!draft&&!!applied&&JSON.stringify(draft)!==JSON.stringify(applied);
  const candidates=selected.map(id=>result?.candidates.find(c=>c.id===id)).filter((c):c is Candidate=>!!c);
  const ordered=useMemo(()=>[...(result?.candidates??[])].sort((a,b)=>sort==='credit'?b.netCredit-a.netCredit||a.id.localeCompare(b.id):sort==='loss'?(a.profile.maxLoss??Infinity)-(b.profile.maxLoss??Infinity)||a.id.localeCompare(b.id):a.expiry.localeCompare(b.expiry)||a.short.strike-b.short.strike||a.long.strike-b.long.strike),[result,sort]);
  const plan=planState.plans.find(p=>p.id===selectedPlan)??planState.plans[0]??null;
  const navigate=(next:Workspace)=>{++planImportSequence.current;setPlanImportBusy(false);setReviewing(null);setWorkspace(next);setError(null);window.scrollTo({top:0,behavior:'instant'});};
  const receiveSource=(next:QuoteSource)=>{
    if(reviewing){const original=planState.plans.find(p=>p.id===reviewing);if(original){setReviewDraft({planId:original.id,evidence:recheckPlan(original,next)});setSelectedPlan(original.id);}setReviewing(null);setWorkspace('plans');return;}
    ++run.current;setSource(next);setDraft(initialCriteria(next));setApplied(null);setResult(null);setSelected([]);setFeesConfirmed(false);setShowImport(false);setWorkspace('research');setNotice(null);setError(null);setBusy(false);
  };
  const apply=async()=>{
    if(!source||!draft||!feesConfirmed)return;const sequence=++run.current;setBusy(true);setError(null);const chosen={...draft};
    try{validateCriteria(chosen);await new Promise(resolve=>setTimeout(resolve,0));const found=discover(source,chosen);if(sequence!==run.current)return;setResult(found);setApplied(chosen);setSelected([]);setLimit(30);setNotice(`已按${chosen.direction==='bullish'?'偏多':'偏空'}条件重新筛选，${found.candidates.length} 个结构通过。`);}
    catch(failure){setError(failure instanceof Error?failure.message:'无法按这些条件计算');}finally{if(sequence===run.current)setBusy(false);}
  };
  const savePlan=(candidate:Candidate,note:string)=>{
    if(!source||!applied||dirty||candidateFailure(candidate,applied))return;
    try{const next=createPlan(source,candidate,applied,note);setPendingPlan(next);const saved=persistPlans(planState,[next,...planState.plans]);setPlanState(saved);setPendingPlan(null);setSelectedPlan(next.id);setStorageError(null);setReviewDraft(null);setNotice('研究计划已保存在此浏览器。原始合约、报价、费用与理由已冻结。');navigate('plans');}
    catch(failure){setStorageError(failure instanceof Error?failure.message:'本地保存失败');}
  };
  const saveEvent=(decision:PlanDecision,note:string,evidence:ReviewEvidence|null)=>{
    if(!plan)return false;try{const next=appendPlanEvent(plan,decision,note,evidence);setPendingPlan(next);const saved=persistPlans(planState,planState.plans.map(p=>p.id===next.id?next:p));setPlanState(saved);setPendingPlan(null);setReviewDraft(null);setStorageError(null);setNotice('已追加新版本；原始报价与理由未改写。');return true;}
    catch(failure){setStorageError(failure instanceof Error?failure.message:'本地保存失败');return false;}
  };
  const readPlan=async(file:File)=>{
    if(file.size>2*1024*1024){setError('研究计划文件超过 2 MB');return;}const request=++planImportSequence.current;setPlanImportBusy(true);
    try{const body=await file.text();if(request!==planImportSequence.current)return;const next=importPlan(body);if(planState.plans.some(p=>p.id===next.id))throw new Error('此计划已经在本地；不会用导入文件覆盖原有版本');
      const saved=persistPlans(planState,[next,...planState.plans]);setPlanState(saved);setSelectedPlan(next.id);setStorageError(null);setReviewDraft(null);setNotice('研究计划已导入；金额已根据冻结合约重新校验。');navigate('plans');}
    catch(failure){if(request===planImportSequence.current)setError(failure instanceof Error?failure.message:'计划文件无法读取');}finally{if(request===planImportSequence.current)setPlanImportBusy(false);}
  };
  const patch=(value:Partial<Criteria>)=>{if(draft)setDraft({...draft,...value});};
  const changeAsset=(asset:Criteria['asset'])=>{if(!source||!draft)return;const row=source.rows.find(r=>r.asset===asset);if(row)patch({asset,currency:row.currency,multiplier:row.multiplier,expiry:'all'});};
  const changeCurrency=(currency:Criteria['currency'])=>{if(!source||!draft)return;const row=source.rows.find(r=>r.asset===draft.asset&&r.currency===currency);if(row)patch({currency,multiplier:row.multiplier,expiry:'all'});};
  const groups=source?quoteGroups(source):[];
  return <div className="q-app"><a className="q-skip" href="#quote-workspace">跳到工作区</a>
    <header className="q-header"><a className="q-brand" href="/" aria-label="Option 研究台首页"><b aria-hidden="true">O<span>↗</span></b><div><strong>OPTION / 研究台</strong><small>从自己的报价，形成可复核的判断</small></div></a>
      <nav aria-label="工作区"><button aria-current={workspace==='research'?'page':undefined} onClick={()=>navigate('research')}>01 <span>导入与筛选</span></button>
        <button aria-current={workspace==='compare'?'page':undefined} onClick={()=>{if(dirty){setNotice('筛选条件已更改，请重新筛选后比较');navigate('research');}else navigate('compare');}}>02 <span>比较</span>{selected.length?<i>{selected.length}</i>:null}</button>
        <button aria-current={workspace==='plans'?'page':undefined} onClick={()=>navigate('plans')}>03 <span>研究计划</span>{planState.plans.length?<i>{planState.plans.length}</i>:null}</button></nav>
      <span className="q-private"><i />私有 · 本地文件处理</span></header>
    <main id="quote-workspace" className="q-main">
      {notice?<div className="q-notice" role="status">{notice}<button aria-label="关闭提示" onClick={()=>setNotice(null)}>×</button></div>:null}
      {error?<div className="q-alert" role="alert">{error}</div>:null}
      {storageError?<div className="q-alert" role="alert"><p>{storageError}</p><button className="q-button" onClick={()=>{const latest=loadPlans();setPlanState(latest.state);setStorageError(latest.error);}}>重新读取本地列表</button>
        {pendingPlan?<button className="q-button" onClick={()=>downloadText(`option-plan-${pendingPlan.id.slice(0,8)}.json`,JSON.stringify(pendingPlan,null,2),'application/json')}>直接导出未保存的计划</button>:null}</div>:null}
      {reviewing?<ImportPanel review onSource={receiveSource} onCancel={()=>setReviewing(null)} />:
      workspace==='research'?<>
        {!source?<div className="q-intro"><span className="q-eyebrow">报价 → 条件 → 判断 → 复核</span><h1>找出符合你的条件的期权价差</h1><p>导入合法来源的报价链，比较有保护腿的结构，再把选择理由和原始证据一起保存。</p></div>:<div className="q-source-bar"><div><span className={source.synthetic?'q-pill q-amber':'q-pill'}>{source.synthetic?'合成演练':'导入快照 · 非实时'}</span><strong>{source.name}</strong><small>报价范围 {when(source.firstQuote)} — {when(source.lastQuote)}</small></div><button className="q-button" onClick={()=>setShowImport(!showImport)}>{showImport?'收起导入':'换一份报价 CSV'}</button></div>}
        {showImport?<ImportPanel onSource={receiveSource} onCancel={source?()=>setShowImport(false):undefined} />:null}
        {source&&draft?<>
          <section className="q-panel q-filter-panel"><div className="q-section-heading"><div><span className="q-eyebrow">02 / 你的研究约束</span><h2>先定方向，再比较同方向结构</h2><p>只支持两类完整 1:1 信用价差；不代表收取权利金优于借记结构或适合你。</p></div><span className="q-muted">没有综合机会分或默认“最佳”</span></div>
            <fieldset className="q-directions"><legend>研究观点</legend><label className={draft.direction==='bullish'?'selected':''}><input type="radio" name="direction" value="bullish" checked={draft.direction==='bullish'} onChange={()=>patch({direction:'bullish'})} /><strong>偏多</strong><span>买低执行价 Put + 卖高执行价 Put</span></label>
              <label className={draft.direction==='bearish'?'selected':''}><input type="radio" name="direction" value="bearish" checked={draft.direction==='bearish'} onChange={()=>patch({direction:'bearish'})} /><strong>偏空</strong><span>卖低执行价 Call + 买高执行价 Call</span></label></fieldset>
            <div className="q-field-grid q-main-filters"><label>标的<select value={draft.asset} onChange={e=>changeAsset(e.target.value as Criteria['asset'])}>{[...new Set(source.rows.map(r=>r.asset))].map(a=><option key={a}>{a}</option>)}</select></label>
              <label>独立计价币种<select value={draft.currency} onChange={e=>changeCurrency(e.target.value as Criteria['currency'])}>{[...new Set(source.rows.filter(r=>r.asset===draft.asset).map(r=>r.currency))].map(c=><option key={c}>{c}</option>)}</select></label>
              <label>每张合约乘数<select value={draft.multiplier} onChange={e=>patch({multiplier:Number(e.target.value),expiry:'all'})}>{[...new Set(source.rows.filter(r=>r.asset===draft.asset&&r.currency===draft.currency).map(r=>r.multiplier))].map(v=><option key={v}>{v}</option>)}</select></label>
              <label>到期范围<select value={draft.expiry} onChange={e=>patch({expiry:e.target.value})}><option value="all">所有到期，分别计算</option>{groups.filter(g=>g.asset===draft.asset&&g.currency===draft.currency&&g.multiplier===draft.multiplier).map(g=><option key={g.key} value={g.expiry}>{expiryLabel(g.expiry)}</option>)}</select></label>
              <label>理论到期损失限额 · {draft.currency}<input type="number" min="0.01" step="any" value={draft.maxLoss} onChange={e=>patch({maxLoss:Number(e.target.value)})} /></label>
              <label>最低净入场现金 · {draft.currency}<input type="number" min="0" step="any" value={draft.minCredit} onChange={e=>patch({minCredit:Number(e.target.value)})} /></label>
              <label>结构份数（自行填写）<input type="number" min="1" max="10000" step="1" value={draft.contracts} onChange={e=>patch({contracts:Number(e.target.value)})} /></label>
              <label>研究时点（取自文件）<input type="text" value={draft.asOf} onChange={e=>patch({asOf:e.target.value})} spellCheck={false} /></label>
            </div>
            <details className="q-advanced" open><summary>费用与报价质量假设</summary><div className="q-field-grid">
              {([['entryFee','每张入场固定费'],['expiryFee','每张到期固定费'],['closeFee','每张平仓固定费']] as const).map(([field,label])=><label key={field}>{label} · {draft.currency}<input type="number" min="0" step="any" value={draft[field]} onChange={e=>{patch({[field]:Number(e.target.value)});setFeesConfirmed(false);}} /></label>)}
              <label>单腿最大买卖价差 · % 中间价<input type="number" min="0" max="200" step="any" value={draft.maxSpreadPct} onChange={e=>patch({maxSpreadPct:Number(e.target.value)})} /></label>
              <label>相对研究时点最多陈旧 · 分钟<input type="number" min="0.01" step="any" value={draft.maxAgeMinutes} onChange={e=>patch({maxAgeMinutes:Number(e.target.value)})} /></label>
              <label>两腿最大报价间隔 · 秒<input type="number" min="1" step="any" value={draft.maxGapSeconds} onChange={e=>patch({maxGapSeconds:Number(e.target.value)})} /></label>
            </div><p className="q-muted">费用按每张合约的现金金额计，不再乘合约乘数；每份两条腿各收一次。0 表示本次假设不计该费用，不代表交易所免费。初始限额与份数只是可编辑起点，不是仓位建议。</p></details>
            <label className="q-confirm"><input type="checkbox" checked={feesConfirmed} onChange={e=>setFeesConfirmed(e.target.checked)} />我确认费用、份数与限额是本次研究假设；理解结果只是配置费用下的理论到期边界</label>
            <div className="q-filter-action"><RiskScope /><button className="q-button q-primary" disabled={!feesConfirmed||busy} onClick={()=>void apply()}>{busy?'正在本地枚举…':result?'按新条件重新筛选':'枚举并筛选完整价差 →'}</button></div>
          </section>
          {dirty?<div className="q-alert" role="status">条件已更改。下方保留上次结果，请重新筛选后再选择比较。</div>:null}
          {result&&applied?<section className="q-results"><div className="q-counts"><div><span>文件行</span><strong>{source.totalRows}</strong></div><div><span>定义有效</span><strong>{source.rows.length}</strong></div><div><span>当前范围报价</span><strong>{result.groupRows}</strong></div><div><span>已核对组合</span><strong>{result.processed}</strong></div><div className="q-count-pass"><span>通过当前条件</span><strong>{result.candidates.length}</strong></div></div>
            {result.limited?<div className="q-alert">当前范围超过 100000 对组合，仅核对了前 100000 对，不是完整穷举。请缩小到期范围再判断。</div>:null}
            <div className="q-results-heading"><div><h2>{structureName({direction:applied.direction})}</h2><p>{applied.contracts} 份结构的总现金流 · {applied.currency} · 快照研究时点 {when(applied.asOf)}</p></div><label>排序<select value={sort} onChange={e=>setSort(e.target.value)}><option value="expiry">到期 / 执行价</option><option value="credit">净入场现金从高到低</option><option value="loss">到期损失界限从低到高</option></select></label></div>
            <details className="q-exclusions"><summary>查看排除原因与覆盖缺口 <span>{source.issues.length} 个输入问题 · {result.processed-result.candidates.length} 个组合未通过</span></summary><div>
              <p>组合按第一个阻断原因计数。不同到期、币种或乘数不会拼成同一结构。报价数量缺失只标“容量未知”。</p><ul>{Object.entries(result.excluded).map(([reason,count])=><li key={reason}><span>{EXCLUSION_LABELS[reason]??reason}</span><strong>{count}</strong></li>)}</ul>
              {source.issues.length?<div className="q-row-errors"><h3>输入行问题</h3><ul>{source.issues.slice(0,40).map((item,i)=><li key={i}><strong>第 {item.row} 行 · {item.instrument}</strong><span>{item.detail}</span></li>)}</ul></div>:null}</div></details>
            {!result.candidates.length?<div className="q-empty"><span>∅</span><h2>没有结构满足这组条件</h2><p>这是完整的筛选结果，不代表市场没有机会。先看排除原因，再决定是否改变约束；不会用示例补满结果。</p></div>:<>
              <div className="q-table-scroll q-candidate-table"><table className="q-table"><caption>卖腿按 Bid、买腿按 Ask；同方向比较，不保证两腿同时成交</caption><thead><tr><th>比较</th><th>卖腿 / 买腿执行价</th><th>各自到期 UTC</th><th>净入场现金</th><th>到期损失界限 *</th><th>盈亏平衡</th><th>报价证据</th></tr></thead><tbody>{ordered.slice(0,limit).map(c=><tr key={c.id} data-selected={selected.includes(c.id)}>
                <td><input type="checkbox" aria-label={`比较 ${shortName(c)} ${c.expiry}`} checked={selected.includes(c.id)} disabled={dirty||busy||(!selected.includes(c.id)&&selected.length>=3)} onChange={()=>setSelected(ids=>ids.includes(c.id)?ids.filter(id=>id!==c.id):[...ids,c.id])} /></td>
                <td><strong>{shortName(c)}</strong><small>卖 {c.contracts} + 买 {c.contracts} 张 · 乘数 {c.multiplier}</small></td><td>{expiryLabel(c.expiry)}<small>距研究时点 {money((Date.parse(c.expiry)-Date.parse(applied.asOf))/86400000,1)} 天</small></td>
                <td className="q-cash">{money(c.netCredit)}<small>入场费 {money(c.entryFees)}</small></td><td>{money(c.profile.maxLoss)}<small>含配置到期费 {money(c.expiryFees)}</small></td><td>{breakeven(c)}</td>
                <td><details><summary>原行 {c.short.row} / {c.long.row}<small>{c.capacityKnown?'可见数量覆盖填写份数':'容量未知'}</small></summary><LegsTable candidate={c} /></details></td></tr>)}</tbody></table></div>
              {ordered.length>limit?<button className="q-button q-more" onClick={()=>setLimit(value=>value+30)}>再显示 {Math.min(30,ordered.length-limit)} 个 · 当前 {limit} / {ordered.length}</button>:null}
            </>}
            <div className="q-compare-tray"><div><strong>已选 {selected.length} / 3</strong><p>同方向、同币种与单位；每个期限单独计算到期损益</p></div><button className="q-button q-primary" disabled={candidates.length<2||dirty||busy} onClick={()=>navigate('compare')}>比较已选结构 →</button></div>
          </section>:<div className="q-ready-note">报价定义已确认。填写本次约束并点击“枚举并筛选”，结果会由你的文件即时计算。</div>}
        </>:null}
      </>:workspace==='compare'?<ComparePanel candidates={candidates} sourceContext={source?`${source.synthetic?'合成演练 · 不是真实市场报价':'用户导入快照 · 非实时，来源未独立核验'}｜${source.name}｜报价时点 ${when(source.lastQuote)}`:undefined} criteria={applied??draft??({} as Criteria)} onRemove={id=>setSelected(ids=>ids.filter(value=>value!==id))} onBack={()=>navigate('research')} onSave={savePlan} />:
      <section className="q-plans"><div className="q-section-heading"><div><span className="q-eyebrow">04 / 可复核的研究记录</span><h1>让后来的你知道，当时为什么选</h1><p>原始证据不覆盖。新报价、不同意或放弃，都追加成新的研究版本。</p></div><button className="q-button" disabled={planImportBusy} onClick={()=>importPlanRef.current?.click()}>{planImportBusy?'正在读取本地计划…':'导入计划 JSON'}</button></div>
        <input className="q-file-input" ref={importPlanRef} type="file" accept=".json,application/json" aria-label="导入本地研究计划 JSON" onChange={e=>{const file=e.target.files?.[0];if(file)void readPlan(file);e.target.value='';}} />
        <div className="q-local-note">仅存在此浏览器，无账户或云同步。清除浏览器数据会移除记录；导出 JSON 才能在其他设备继续。</div>
        {!plan?<div className="q-empty"><span>↗</span><h2>第一份计划，从你的选择开始</h2><p>导入报价，比较两个候选，写下一句理由。也可以导入之前导出的计划。</p><button className="q-button q-primary" onClick={()=>navigate('research')}>开始研究</button></div>:<div className="q-plan-layout"><nav className="q-plan-list" aria-label="已保存研究计划">{planState.plans.map(item=><button key={item.id} aria-pressed={item.id===plan.id} onClick={()=>{setSelectedPlan(item.id);setReviewDraft(null);}}><span>{item.criteria.asset} · {item.criteria.direction==='bullish'?'偏多':'偏空'}</span><strong>{money(item.short.strike,4)} / {money(item.long.strike,4)}</strong><small>{expiryLabel(item.long.expiry)}</small><i>{item.events[item.events.length-1]?.decision==='abandon'?'已放弃':item.events[item.events.length-1]?.decision==='revise'?'需改版':'研究中'} · V{item.events.length+1}</i></button>)}</nav>
          <PlanDetail key={plan.id} plan={plan} review={reviewDraft?.planId===plan.id?reviewDraft.evidence:null} onReview={()=>setReviewing(plan.id)} onEvent={saveEvent} /></div>}
      </section>}
    </main><footer className="q-footer"><span>OPTION / RESEARCH WORKBENCH</span><p>用户提供的离线证据 · 确定性到期计算 · 不连接交易</p><details><summary>能力与数据边界</summary><p>没有实时数据源、自动监控、胜率或预测定价。没有做市商、券商或交易所背书。当前只支持明确的欧式线性现金期权定义；动态费用、保证金和生命周期风险需另行核对。旧版固定演练仍可通过 <a href="?legacy=1">合成回放页</a> 查看。</p></details></footer>
  </div>;
}
