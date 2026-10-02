import { closeCashAtTouch, roundCash } from './payoff';
import { candidateFailure, makeCandidate, validateCriteria, type Candidate, type Criteria } from './engine';
import { EMPTY_DEFAULTS, normalizeCsv, parseCsv, suggestMapping, type QuoteRow, type QuoteSource } from './csv';
import { isoInstant } from './time';

export const PLAN_STORAGE_KEY='lensos-option.research-plans.v2';
export const MAX_PLAN_STORAGE_CHARS=3_000_000;
export type PlanDecision='continue'|'revise'|'abandon';
export interface SourceStamp {id:string;name:string;synthetic:boolean;firstQuote:string|null;lastQuote:string|null;totalRows:number}
export interface ReviewEvidence {
  status:'matched'|'blocked';source:SourceStamp;reasons:string[];long:QuoteRow|null;short:QuoteRow|null;
  newCandidate:Candidate|null;closeReference:number|null;referenceChange:number|null;criteriaFailure:string|null;
  closeCapacity:'known'|'unknown'|'insufficient'|'unverified';
}
export interface PlanEvent {id:string;at:string;decision:PlanDecision;note:string;review:ReviewEvidence|null}
export interface DecisionPlan {
  schema:'decision-plan.v1';id:string;createdAt:string;source:SourceStamp;criteria:Criteria;long:QuoteRow;short:QuoteRow;
  rationale:string;events:PlanEvent[];
}
export interface PlanState {revision:string;plans:DecisionPlan[]}
export const sourceStamp=(source:QuoteSource):SourceStamp=>({id:source.id,name:source.name,synthetic:source.synthetic,firstQuote:source.firstQuote,lastQuote:source.lastQuote,totalRows:source.totalRows});
export function createPlan(source:QuoteSource,candidate:Candidate,criteria:Criteria,rationale:string):DecisionPlan {
  if(!rationale.trim())throw new Error('请写一句选择或继续研究的理由');
  if(rationale.length>2000)throw new Error('研究理由最多 2000 字');
  const failure=candidateFailure(candidate,criteria);if(failure)throw new Error('候选已不满足当前条件，请先重新筛选');
  return {schema:'decision-plan.v1',id:crypto.randomUUID(),createdAt:new Date().toISOString(),source:sourceStamp(source),criteria:{...criteria},
    long:structuredClone(candidate.long),short:structuredClone(candidate.short),rationale:rationale.trim(),events:[]};
}

export function recheckPlan(plan:DecisionPlan,source:QuoteSource):ReviewEvidence {
  const reasons:string[]=[];const long=source.rows.find(row=>row.instrument===plan.long.instrument)??null;
  const short=source.rows.find(row=>row.instrument===plan.short.instrument)??null;
  const base:ReviewEvidence={status:'blocked',source:sourceStamp(source),reasons,long,short,newCandidate:null,closeReference:null,referenceChange:null,criteriaFailure:null,closeCapacity:'unverified'};
  if(!source.lastQuote){reasons.push('新文件没有可用报价，无法逐腿复核');return base;}
  if(source.synthetic!==plan.source.synthetic){reasons.push('合成示例和用户文件来源类型不同，不能互相冒充复核');return base;}
  if(Date.parse(source.lastQuote)>=Date.parse(plan.long.expiry)){reasons.push('新快照时点已到或超过原合约到期；不能据此估算到期前平仓');return base;}
  for(const [old,row] of [[plan.long,long],[plan.short,short]] as const) {
    if(!row){reasons.push(`缺少原合约 ${old.instrument}；没有替换为其他行权价`);continue;}
    const fields=['asset','currency','expiry','multiplier','optionType','strike','exercise','settlement'] as const;
    if(fields.some(key=>row[key]!==old[key]))reasons.push(`${old.instrument} 的标的、币种、单位、到期或合约定义发生变化`);
    // Same timestamps with changed prices are not fresh evidence either.
    const latestMatched=plan.events.flatMap(event=>event.review?.status==='matched'?[event.review.long,event.review.short]:[])
      .filter((quote):quote is QuoteRow=>quote!==null&&quote.instrument===old.instrument);
    const lastTime=Math.max(Date.parse(old.quotedAt),...latestMatched.map(quote=>Date.parse(quote.quotedAt)));
    if(Date.parse(row.quotedAt)<=lastTime)reasons.push(`${old.instrument} 的报价没有晚于已保存证据，旧版本不会被覆盖`);
  }
  if(reasons.length||!long||!short)return base;
  const criteria={...plan.criteria,asOf:source.lastQuote};
  try {
    const candidate=makeCandidate(long,short,criteria);const failure=candidateFailure(candidate,criteria);
    // Quality failures prohibit a close estimate; a changed economic condition is itself useful evidence.
    const quality=['ZERO_BID','WIDE_SPREAD','STALE','FUTURE','EXPIRED','QUOTE_GAP'];
    if(failure&&quality.includes(failure)){reasons.push(`原条件下报价质量不合格：${failure}`);return {...base,criteriaFailure:failure};}
    const closeCapacity=(long.bidSize!==null&&long.bidSize<plan.criteria.contracts)||(short.askSize!==null&&short.askSize<plan.criteria.contracts)?'insufficient':long.bidSize===null||short.askSize===null?'unknown':'known';
    if(closeCapacity==='insufficient')reasons.push('平仓方向可见数量不足（卖回买腿取 Bid 数量、买回卖腿取 Ask 数量），未提供反向现金参考');
    if(closeCapacity==='unknown')reasons.push('平仓方向数量缺失，不能验证容量；反向现金值仅是报价点换算，不保证成交');
    const closeReference=closeCapacity==='insufficient'?null:closeCashAtTouch(candidate.legs,plan.criteria.closeFee);
    const original=makeCandidate(plan.long,plan.short,plan.criteria);
    return {...base,status:'matched',newCandidate:candidate,closeReference,referenceChange:closeReference===null?null:roundCash(original.netCredit+closeReference),criteriaFailure:failure,closeCapacity};
  }catch{reasons.push('新报价不能按原始合约口径重新计算');return base;}
}

export function appendPlanEvent(plan:DecisionPlan,decision:PlanDecision,note:string,review:ReviewEvidence|null):DecisionPlan {
  if(!['continue','revise','abandon'].includes(decision))throw new Error('请选择本次研究状态');
  if(!note.trim())throw new Error('请写下这次复核的理由');
  if(note.length>2000||plan.events.length>=100)throw new Error('笔记或历史记录已达到本地上限，请先导出保留');
  return {...plan,events:[...plan.events,{id:crypto.randomUUID(),at:new Date().toISOString(),decision,note:note.trim(),review:review?structuredClone(review):null}]};
}

const text=(value:unknown,max=2000):string=>{if(typeof value!=='string'||value.length>max)throw new Error('研究计划的文字字段无效');return value;};
const obj=(value:unknown):Record<string,unknown>=>{if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('研究计划格式无效');return value as Record<string,unknown>;};
const time=(value:unknown):string=>{const s=text(value,64);if(!isoInstant(s))throw new Error('研究计划的时刻无效');return s;};
function validateStamp(value:unknown):SourceStamp {
  const s=obj(value);const id=text(s.id,100);if(!/^[a-f0-9]{64}$/.test(id)||typeof s.synthetic!=='boolean'||!Number.isInteger(s.totalRows)||Number(s.totalRows)<1||Number(s.totalRows)>5000)throw new Error('研究计划的来源标识无效');
  return {id,name:text(s.name,300),synthetic:s.synthetic,totalRows:Number(s.totalRows),firstQuote:s.firstQuote===null?null:time(s.firstQuote),lastQuote:s.lastQuote===null?null:time(s.lastQuote)};
}
function quoteCsv(row:Record<string,unknown>):string {
  const values=[row.instrument,row.asset,row.expiry,row.optionType,row.strike,row.rawBid,row.rawAsk,row.quotedAt,row.currency,row.multiplier,row.quoteUnit,row.exercise,row.settlement,row.bidSize??'',row.askSize??'',row.tickSize??''];
  return values.map(value=>`"${String(value??'').replaceAll('"','""')}"`).join(',');
}
function validateQuote(value:unknown):QuoteRow {
  const row=obj(value);const header='instrument_id,underlying,expiry,option_type,strike,bid,ask,quote_timestamp,settlement_currency,contract_multiplier,quote_unit,exercise_style,settlement_type,bid_size,ask_size,tick_size';
  const table=parseCsv(`${header}\n${quoteCsv(row)}`);const result=normalizeCsv(table,suggestMapping(table.headers),EMPTY_DEFAULTS);
  if(result.rows.length!==1||result.issues.length)throw new Error('计划包含无效合约或报价');
  if(!Number.isInteger(row.row)||Number(row.row)<2||Number(row.row)>50000)throw new Error('原始行号无效');
  const canonical=result.rows[0];
  if(canonical.bid!==row.bid||canonical.ask!==row.ask)throw new Error('报价单位与归一化金额不一致');
  return {...canonical,row:Number(row.row)};
}

/** Import reconstructs calculations from preserved quotes; imported money summaries are never trusted. */
export function validatePlan(value:unknown):DecisionPlan {
  const raw=obj(value);if(raw.schema!=='decision-plan.v1')throw new Error('不是此工作台支持的研究计划版本');
  const id=text(raw.id,100);if(!id)throw new Error('计划标识缺失');
  const source=validateStamp(raw.source);const criteria=obj(raw.criteria) as unknown as Criteria;validateCriteria(criteria);
  const long=validateQuote(raw.long),short=validateQuote(raw.short);const original=makeCandidate(long,short,criteria);
  if(candidateFailure(original,criteria))throw new Error('基准计划不满足冻结的研究条件');
  if((long.instrument.startsWith('SYNTHETIC-')||short.instrument.startsWith('SYNTHETIC-'))&&!source.synthetic)throw new Error('合成示例不能重新标成用户市场证据');
  if(!source.firstQuote||!source.lastQuote||Date.parse(source.firstQuote)>Math.min(Date.parse(long.quotedAt),Date.parse(short.quotedAt))
    ||Date.parse(source.lastQuote)<Math.max(Date.parse(long.quotedAt),Date.parse(short.quotedAt)))throw new Error('来源时段与原始合约报价不一致');
  if(!Array.isArray(raw.events)||raw.events.length>100)throw new Error('复核记录格式无效');
  const plan:DecisionPlan={schema:'decision-plan.v1',id,source,criteria:{...criteria},long,short,createdAt:time(raw.createdAt),rationale:text(raw.rationale),events:[]};
  for(const value of raw.events) {
    const event=obj(value);if(!['continue','revise','abandon'].includes(String(event.decision)))throw new Error('复核状态无效');
    let review:ReviewEvidence|null=null;
    if(event.review!==null) {
      const r=obj(event.review);const stamp=validateStamp(r.source);const l=r.long===null?null:validateQuote(r.long);const s=r.short===null?null:validateQuote(r.short);
      const sourceForReview:QuoteSource={schema:'quote-source.v1',...stamp,importedAt:time(event.at),rows:[l,s].filter((row):row is QuoteRow=>row!==null),issues:[]};
      review=recheckPlan(plan,sourceForReview);
      // Preserve blocked reasons after independent safety checks; never accept a claimed success with mismatched legs.
      if(r.status==='matched'&&review.status!=='matched')throw new Error('导入的复核身份、时序或定义不一致');
    }
    plan.events.push({id:text(event.id,100),at:time(event.at),decision:event.decision as PlanDecision,note:text(event.note),review});
  }
  return plan;
}
export function importPlan(textValue:string):DecisionPlan {
  if(new TextEncoder().encode(textValue).length>2*1024*1024)throw new Error('研究计划文件超过 2 MB');
  try{return validatePlan(JSON.parse(textValue));}catch(error){throw new Error(error instanceof Error?error.message:'研究计划 JSON 无法读取');}
}
export function loadPlans():{state:PlanState;error:string|null} {
  try {
    const raw=localStorage.getItem(PLAN_STORAGE_KEY);if(!raw)return {state:{revision:'empty',plans:[]},error:null};
    if(raw.length>MAX_PLAN_STORAGE_CHARS)throw new Error('too large');const body=obj(JSON.parse(raw));
    if(!Array.isArray(body.plans)||body.plans.length>50)throw new Error('bad plans');
    return {state:{revision:text(body.revision,100),plans:body.plans.map(validatePlan)},error:null};
  }catch{return {state:{revision:'blocked',plans:[]},error:'本地记录读取失败，原始数据未改动。请先使用已导出的 JSON；浏览器存储可能受限或文件损坏。'};}
}
export function persistPlans(base:PlanState,plans:DecisionPlan[]):PlanState {
  if(plans.length>50)throw new Error('最多保存 50 份计划；请先导出需要的记录');
  const current=loadPlans();if(current.error)throw new Error(current.error);
  if(current.state.revision!==base.revision)throw new Error('另一个页面已更新本地记录，请先重新读取列表，避免覆盖');
  const next={revision:crypto.randomUUID(),plans:plans.map(validatePlan)};
  const serialized=JSON.stringify(next);
  if(serialized.length>MAX_PLAN_STORAGE_CHARS)throw new Error('本地记录已达到安全容量上限，尚未保存；请直接导出 JSON，原有记录未被覆盖');
  try{localStorage.setItem(PLAN_STORAGE_KEY,serialized);return next;}catch{throw new Error('浏览器存储不足或禁止写入，尚未保存；请直接导出 JSON 保留此次计划');}
}
