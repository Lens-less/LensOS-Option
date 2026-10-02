import { groupKey, type QuoteRow, type QuoteSource } from './csv';
import { entryCashAtTouch, payoffProfile, type PayoffProfile, type QuotedLeg } from './payoff';
import { isoInstant } from './time';

export type Direction='bullish'|'bearish';
export interface Criteria {
  asset:'BTC'|'ETH';currency:'USD'|'USDC'|'USDT';expiry:string;multiplier:number;direction:Direction;
  minCredit:number;maxLoss:number;maxSpreadPct:number;maxAgeMinutes:number;maxGapSeconds:number;
  contracts:number;entryFee:number;expiryFee:number;closeFee:number;asOf:string;
}
export interface Candidate {
  id:string;direction:Direction;asset:string;currency:string;expiry:string;multiplier:number;contracts:number;
  long:QuoteRow;short:QuoteRow;legs:QuotedLeg[];grossCredit:number;entryFees:number;netCredit:number;
  expiryFees:number;profile:PayoffProfile;quoteGapSeconds:number;oldestQuote:string;newestQuote:string;
  width:number;capacityKnown:boolean;
}
export interface Discovery {
  candidates:Candidate[];groupRows:number;validRows:number;formed:number;processed:number;
  excluded:Record<string,number>;limited:boolean;
}
export const EXCLUSION_LABELS:Record<string,string>={
  ZERO_BID:'缺少正双边报价',WIDE_SPREAD:'单腿买卖价差超过条件',STALE:'相对研究时点报价过旧',FUTURE:'报价晚于研究时点',
  EXPIRED:'研究时点已到期',QUOTE_GAP:'两腿报价不同步',CAPACITY:'已知报价数量不足',NO_CREDIT:'净入场现金非正',
  NO_EXPIRY_UPSIDE:'配置到期费后没有正到期结果',ARBITRAGE:'报价形成异常无风险信用，请复核',
  CREDIT_FLOOR:'低于最低净入场现金',LOSS_LIMIT:'超过到期损失限额',NON_FINITE:'金额不能可靠计算',
};

export function initialCriteria(source:QuoteSource):Criteria {
  const first=source.rows[0];
  return {asset:first?.asset??'BTC',currency:first?.currency??'USDC',expiry:'all',multiplier:first?.multiplier??1,direction:'bullish',
    minCredit:0,maxLoss:1000,maxSpreadPct:35,maxAgeMinutes:15,maxGapSeconds:120,contracts:1,entryFee:0,expiryFee:0,closeFee:0,
    asOf:source.lastQuote??new Date().toISOString()};
}
export function validateCriteria(criteria:Criteria):void {
  if(!['bullish','bearish'].includes(criteria.direction)||!['BTC','ETH'].includes(criteria.asset)||!['USD','USDC','USDT'].includes(criteria.currency))throw new Error('请选择支持的研究方向、标的和币种');
  if(!Number.isInteger(criteria.contracts)||criteria.contracts<1||criteria.contracts>10000)throw new Error('结构份数应为 1–10000 的整数');
  if(!isoInstant(criteria.asOf)||(criteria.expiry!=='all'&&!isoInstant(criteria.expiry)))throw new Error('研究时点与到期须为有效的明确时区时刻');
  if(!Number.isFinite(criteria.multiplier)||criteria.multiplier<=0)throw new Error('合约乘数必须为正数');
  for(const name of ['minCredit','maxLoss','maxSpreadPct','maxAgeMinutes','maxGapSeconds','entryFee','expiryFee','closeFee'] as const) {
    if(!Number.isFinite(criteria[name])||criteria[name]<0||criteria[name]>1e12)throw new Error('费用与筛选数值须为有效非负数');
  }
  if(criteria.maxLoss<=0||criteria.maxAgeMinutes<=0||criteria.maxGapSeconds<=0||criteria.maxSpreadPct>200)throw new Error('损失限额、报价时长与同步窗口须大于零；价差上限不能超过 200%');
}

export function qualityFailure(row:QuoteRow,criteria:Criteria):string|null {
  const at=Date.parse(criteria.asOf);const quote=Date.parse(row.quotedAt);
  if(Date.parse(row.expiry)<=at)return 'EXPIRED';
  if(quote>at)return 'FUTURE';
  if(at-quote>criteria.maxAgeMinutes*60000)return 'STALE';
  if(row.bid<=0)return 'ZERO_BID';
  if((row.ask-row.bid)/((row.ask+row.bid)/2)*100>criteria.maxSpreadPct)return 'WIDE_SPREAD';
  return null;
}

export function makeCandidate(long:QuoteRow,short:QuoteRow,criteria:Criteria):Candidate {
  validateCriteria(criteria);
  if(long.asset!==criteria.asset||long.currency!==criteria.currency||long.multiplier!==criteria.multiplier
    ||(criteria.expiry!=='all'&&long.expiry!==criteria.expiry))throw new Error('候选与研究条件的标的、币种、单位或到期不一致');
  if(groupKey(long)!==groupKey(short)||long.optionType!==short.optionType||long.instrument===short.instrument)throw new Error('候选必须是同定义、同到期的两条不同合约');
  const bullish=criteria.direction==='bullish';
  if((bullish&&(long.optionType!=='put'||long.strike>=short.strike))||(!bullish&&(long.optionType!=='call'||long.strike<=short.strike)))throw new Error('合约腿不构成指定方向的完整信用价差');
  const legs:QuotedLeg[]=[{...long,quantity:criteria.contracts},{...short,quantity:-criteria.contracts}];
  const cash=entryCashAtTouch(legs,criteria.entryFee);
  const expiryFees=criteria.expiryFee*2*criteria.contracts;
  const profile=payoffProfile(legs,cash.net,expiryFees);
  const times=[long.quotedAt,short.quotedAt].sort();
  return {id:JSON.stringify([criteria.direction,long.instrument,short.instrument]),direction:criteria.direction,asset:long.asset,currency:long.currency,
    expiry:long.expiry,multiplier:long.multiplier,contracts:criteria.contracts,long,short,legs,grossCredit:cash.gross,entryFees:cash.fees,
    netCredit:cash.net,expiryFees,profile,quoteGapSeconds:Math.abs(Date.parse(long.quotedAt)-Date.parse(short.quotedAt))/1000,
    oldestQuote:times[0],newestQuote:times[1],width:Math.abs(long.strike-short.strike),capacityKnown:long.askSize!==null&&short.bidSize!==null};
}

export function candidateFailure(candidate:Candidate,criteria:Criteria):string|null {
  for(const leg of [candidate.long,candidate.short]){const reason=qualityFailure(leg,criteria);if(reason)return reason;}
  if(candidate.quoteGapSeconds>criteria.maxGapSeconds)return 'QUOTE_GAP';
  if((candidate.long.askSize!==null&&candidate.long.askSize<criteria.contracts)||(candidate.short.bidSize!==null&&candidate.short.bidSize<criteria.contracts))return 'CAPACITY';
  if(candidate.netCredit<=0)return 'NO_CREDIT';
  if(candidate.grossCredit>=candidate.width*candidate.multiplier*candidate.contracts)return 'ARBITRAGE';
  if(candidate.profile.bestPnl===null||candidate.profile.bestPnl<=0)return 'NO_EXPIRY_UPSIDE';
  if(candidate.netCredit<criteria.minCredit)return 'CREDIT_FLOOR';
  if(candidate.profile.maxLoss===null||candidate.profile.maxLoss>criteria.maxLoss)return 'LOSS_LIMIT';
  return null;
}

const MAX_PAIRS=100000;
export function discover(source:QuoteSource,criteria:Criteria):Discovery {
  validateCriteria(criteria);
  const type=criteria.direction==='bullish'?'put':'call';
  const groupRows=source.rows.filter(row=>row.asset===criteria.asset&&row.currency===criteria.currency&&row.multiplier===criteria.multiplier
    &&(criteria.expiry==='all'||row.expiry===criteria.expiry)&&row.optionType===type);
  const groups=new Map<string,QuoteRow[]>();
  for(const row of groupRows){const key=groupKey(row);groups.set(key,[...(groups.get(key)??[]),row]);}
  const result:Discovery={candidates:[],groupRows:groupRows.length,validRows:groupRows.filter(row=>!qualityFailure(row,criteria)).length,
    formed:0,processed:0,excluded:{},limited:false};
  for(const rows of groups.values())result.formed+=rows.length*(rows.length-1)/2;
  outer:for(const rows of groups.values()) {
    rows.sort((a,b)=>a.strike-b.strike||a.instrument.localeCompare(b.instrument));
    for(let i=0;i<rows.length;i++)for(let j=i+1;j<rows.length;j++) {
      if(rows[i].strike===rows[j].strike){result.formed--;continue;}
      if(result.processed>=MAX_PAIRS){result.limited=true;break outer;}
      result.processed++;
      const long=criteria.direction==='bullish'?rows[i]:rows[j];const short=criteria.direction==='bullish'?rows[j]:rows[i];
      try {
        const candidate=makeCandidate(long,short,criteria);const reason=candidateFailure(candidate,criteria);
        if(reason)result.excluded[reason]=(result.excluded[reason]??0)+1;else result.candidates.push(candidate);
      }catch{result.excluded.NON_FINITE=(result.excluded.NON_FINITE??0)+1;}
    }
  }
  result.candidates.sort((a,b)=>a.expiry.localeCompare(b.expiry)||a.short.strike-b.short.strike||a.long.strike-b.long.strike);
  return result;
}
