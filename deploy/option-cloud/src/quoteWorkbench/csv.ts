import { isoInstant } from './time';
export const MAX_FILE_BYTES = 5 * 1024 * 1024;
export const MAX_ROWS = 5000;
export type Field = 'instrument' | 'asset' | 'expiry' | 'optionType' | 'strike' | 'bid' | 'ask' | 'quotedAt' | 'currency' | 'multiplier' | 'quoteUnit' | 'exercise' | 'settlement' | 'bidSize' | 'askSize' | 'tickSize';
export const FIELD_LABELS: Record<Field,string> = {
  instrument:'合约标识',asset:'标的',expiry:'到期时刻（含时区）',optionType:'期权类型 C / P',strike:'执行价',
  bid:'Bid 买价',ask:'Ask 卖价',quotedAt:'报价时刻（含时区）',currency:'结算币种',multiplier:'合约乘数',
  quoteUnit:'报价单位',exercise:'行权方式',settlement:'结算方式',bidSize:'Bid 数量（张）',askSize:'Ask 数量（张）',tickSize:'报价最小跳动',
};
export const REQUIRED_FIELDS: Field[] = ['instrument','asset','expiry','optionType','strike','bid','ask','quotedAt','currency','multiplier','quoteUnit','exercise','settlement'];
export const ALL_FIELDS = Object.keys(FIELD_LABELS) as Field[];
export type ColumnMap = Record<Field,string>;
export interface RawTable { headers:string[]; rows:{line:number;values:string[]}[] }
export interface ImportDefaults { currency:string; multiplier:string; quoteUnit:string; exercise:string; settlement:string }
export const EMPTY_DEFAULTS: ImportDefaults = {currency:'',multiplier:'',quoteUnit:'',exercise:'',settlement:''};
export interface QuoteRow {
  row:number; instrument:string; asset:'BTC'|'ETH'; expiry:string; optionType:'call'|'put'; strike:number;
  bid:number; ask:number; quotedAt:string; currency:'USD'|'USDC'|'USDT'; multiplier:number;
  quoteUnit:'per_underlying'|'per_contract'; rawBid:number; rawAsk:number;
  exercise:'european'; settlement:'cash_linear'; bidSize:number|null; askSize:number|null; tickSize:number|null;
}
export interface RowIssue { row:number; instrument:string; code:string; detail:string }
export interface QuoteSource {
  schema:'quote-source.v1'; id:string; name:string; importedAt:string; synthetic:boolean;
  totalRows:number; rows:QuoteRow[]; issues:RowIssue[]; firstQuote:string|null; lastQuote:string|null;
}

/** Bounded RFC-style parser: quoted commas/newlines and doubled quotes, never eval. */
export function parseCsv(input:string):RawTable {
  if (new TextEncoder().encode(input).byteLength>MAX_FILE_BYTES) throw new Error('文件超过 5 MB，请按标的或到期缩小范围');
  const text=input.replace(/^\uFEFF/,'');
  const records:{line:number;values:string[]}[]=[]; let values:string[]=[]; let value=''; let quoted=false; let closed=false;
  let line=1; let recordLine=1;
  const finishCell=()=>{values.push(value.trim());value='';closed=false;};
  const finishRow=()=>{finishCell();if(values.some(cell=>cell!==''))records.push({line:recordLine,values});values=[];recordLine=line+1;};
  for(let i=0;i<text.length;i++) {
    const c=text[i];
    if(quoted) {
      if(c==='"') {if(text[i+1]==='"'){value+='"';i++;}else{quoted=false;closed=true;}}
      else{value+=c;if(c==='\n')line++;}
    } else if(c==='"') {
      if(value.trim()!==''||closed)throw new Error(`第 ${line} 行的引号格式不完整`);
      quoted=true;
    } else if(c===',')finishCell();
    else if(c==='\n'||c==='\r') {finishRow();if(c==='\r'&&text[i+1]==='\n')i++;line++;}
    else {if(closed&&c.trim())throw new Error(`第 ${line} 行引号后有多余内容`);value+=c;}
    if(records.length>MAX_ROWS+1)throw new Error('最多处理 5000 行报价，请先缩小文件范围');
  }
  if(quoted)throw new Error(`第 ${recordLine} 行的引号没有闭合`);
  if(value!==''||values.length)finishRow();
  const header=records.shift();if(!header||header.values.length<2)throw new Error('未识别到逗号分隔的 CSV 表头');
  if(new Set(header.values).size!==header.values.length||header.values.some(h=>!h))throw new Error('CSV 表头不能为空或重名');
  if(!records.length)throw new Error('文件只有表头，没有报价行');
  if(records.length>MAX_ROWS)throw new Error('最多处理 5000 行报价');
  return {headers:header.values,rows:records};
}

const ALIASES:Record<Field,string[]>={
  instrument:['instrument_id','instrument_name','instrument','symbol','合约','合约标识','合约名称'],
  asset:['underlying','asset','currency_underlying','标的','基础资产'],
  expiry:['expiry','expiration','expiration_timestamp','expiry_timestamp','到期时刻','到期时间'],
  optionType:['option_type','type','call_put','期权类型','类型'],strike:['strike','strike_price','执行价','行权价'],
  bid:['bid','bid_price','best_bid_price','买价'],ask:['ask','ask_price','best_ask_price','卖价'],
  quotedAt:['quote_timestamp','quoted_at','quote_time','timestamp','报价时间','报价时刻'],
  currency:['settlement_currency','quote_currency','price_currency','结算币种','币种'],
  multiplier:['contract_multiplier','contract_size','multiplier','合约乘数','合约单位'],
  quoteUnit:['quote_unit','price_unit','报价单位'],exercise:['exercise_style','exercise','行权方式'],
  settlement:['settlement_type','settlement','结算方式'],bidSize:['bid_size','best_bid_amount','买价数量'],
  askSize:['ask_size','best_ask_amount','卖价数量'],tickSize:['tick_size','tick','最小跳动'],
};
const normalizeHeader=(value:string)=>value.trim().toLowerCase().replace(/[\s-]+/g,'_');
export function suggestMapping(headers:string[]):ColumnMap {
  return Object.fromEntries(ALL_FIELDS.map(field=>[field,headers.find(header=>ALIASES[field].includes(normalizeHeader(header)))??''])) as ColumnMap;
}
const number=(text:string):number|null=>text!==''&&/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(text)&&Number.isFinite(Number(text))?Number(text):null;
const date=isoInstant;
export function normalizeCsv(table:RawTable,mapping:ColumnMap,defaults:ImportDefaults):{rows:QuoteRow[];issues:RowIssue[]} {
  const used=Object.values(mapping).filter(Boolean);
  if(new Set(used).size!==used.length)throw new Error('同一列不能对应多个字段，请检查映射');
  for(const field of REQUIRED_FIELDS)if(!mapping[field]&&!(field in defaults&&defaults[field as keyof ImportDefaults]))throw new Error(`请映射「${FIELD_LABELS[field]}」，或明确填写统一定义`);
  const rows:QuoteRow[]=[];const issues:RowIssue[]=[];
  for(const raw of table.rows) {
    const get=(field:Field)=>mapping[field]?raw.values[table.headers.indexOf(mapping[field])]?.trim()??'':field in defaults?defaults[field as keyof ImportDefaults]:'';
    const instrument=get('instrument');
    const issue=(code:string,detail:string)=>issues.push({row:raw.line,instrument,code,detail});
    if(raw.values.length!==table.headers.length){issue('COLUMN_COUNT',`列数 ${raw.values.length} 与表头 ${table.headers.length} 不一致`);continue;}
    const asset=get('asset').toUpperCase(); const currency=get('currency').toUpperCase();
    const expiry=date(get('expiry')); const quotedAt=date(get('quotedAt'));
    const type=get('optionType').toLowerCase(); const optionType=['c','call','看涨'].includes(type)?'call':['p','put','看跌'].includes(type)?'put':null;
    const strike=number(get('strike')); const bid=number(get('bid')); const ask=number(get('ask'));const multiplier=number(get('multiplier'));
    const unit=get('quoteUnit').toLowerCase();const quoteUnit=['per_underlying','underlying','每基础资产单位'].includes(unit)?'per_underlying':['per_contract','contract','每张合约'].includes(unit)?'per_contract':null;
    const exercise=get('exercise').toLowerCase();const settlement=get('settlement').toLowerCase();
    if(!instrument||instrument.length>200){issue('INSTRUMENT','合约标识缺失或过长');continue;}
    if(!['BTC','ETH'].includes(asset)){issue('ASSET','本版只支持 BTC / ETH');continue;}
    if(!['USD','USDC','USDT'].includes(currency)){issue('CURRENCY','本版只支持 USD / USDC / USDT 计价结算，不支持反向币本位');continue;}
    if(!expiry||!quotedAt){issue('TIME','到期与报价须为带时区的 ISO 时刻，例如 2026-10-02T08:00:00Z；不猜日期或秒/毫秒');continue;}
    if(Date.parse(quotedAt)>=Date.parse(expiry)){issue('EXPIRED_AT_QUOTE','报价时刻已到或超过合约到期');continue;}
    if(!optionType||strike===null||strike<=0||strike>1e9){issue('CONTRACT','期权类型或执行价无效');continue;}
    if(multiplier===null||multiplier<=0||multiplier>1e6||!quoteUnit){issue('UNIT','必须明确正合约乘数及 per_underlying / per_contract 报价单位');continue;}
    if(!['european','欧式'].includes(exercise)||!['cash_linear','linear_cash','线性现金'].includes(settlement)) {issue('DEFINITION','仅支持 european + cash_linear；美式、实物和反向定义不可套用');continue;}
    if(bid===null||ask===null||bid<0||ask<=0||bid>ask||ask>1e12){issue('QUOTE','Bid / Ask 须为有效非负数、Ask > 0 且 Bid ≤ Ask');continue;}
    const size=(field:'bidSize'|'askSize'|'tickSize')=>get(field)===''?null:number(get(field));
    const bidSize=size('bidSize'),askSize=size('askSize'),tickSize=size('tickSize');
    if(['bidSize','askSize','tickSize'].some(field=>get(field as Field)!==''&&(size(field as 'bidSize'|'askSize'|'tickSize')===null||(size(field as 'bidSize'|'askSize'|'tickSize')??0)<0))||tickSize===0) {issue('SIZE','数量不能为负；最小跳动必须为正数，未知请留空');continue;}
    if(tickSize!==null&&[bid,ask].some(price=>price/tickSize>Number.MAX_SAFE_INTEGER||Math.abs(price/tickSize-Math.round(price/tickSize))>1e-6)) {
      issue('TICK','原始报价不符合提供的最小跳动，或精度超出可靠范围；请核对报价与单位，不自动改价');continue;
    }
    rows.push({row:raw.line,instrument,asset:asset as QuoteRow['asset'],currency:currency as QuoteRow['currency'],expiry,quotedAt,optionType,strike,multiplier,
      quoteUnit,bid:quoteUnit==='per_contract'?bid/multiplier:bid,ask:quoteUnit==='per_contract'?ask/multiplier:ask,rawBid:bid,rawAsk:ask,
      exercise:'european',settlement:'cash_linear',bidSize,askSize,tickSize});
  }
  const counts=new Map<string,number>();for(const row of rows)counts.set(row.instrument,(counts.get(row.instrument)??0)+1);
  const duplicates=new Set([...counts].filter(([,count])=>count>1).map(([name])=>name));
  for(const row of rows)if(duplicates.has(row.instrument))issues.push({row:row.row,instrument:row.instrument,code:'DUPLICATE_ID',detail:'合约标识重复，本次全部排除；请保留所需的唯一一行，不能静默覆盖'});
  return {rows:rows.filter(row=>!duplicates.has(row.instrument)),issues};
}

export async function sourceFromCsv(text:string,name:string,table:RawTable,mapping:ColumnMap,defaults:ImportDefaults,synthetic=false):Promise<QuoteSource> {
  const normalized=normalizeCsv(table,mapping,defaults);
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));
  const id=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
  const times=normalized.rows.map(row=>Date.parse(row.quotedAt));
  return {schema:'quote-source.v1',id,name,importedAt:new Date().toISOString(),synthetic,totalRows:table.rows.length,...normalized,
    firstQuote:times.length?new Date(Math.min(...times)).toISOString():null,lastQuote:times.length?new Date(Math.max(...times)).toISOString():null};
}

export const groupKey=(row:QuoteRow):string=>[row.asset,row.currency,row.expiry,row.multiplier].join('|');
export function quoteGroups(source:QuoteSource):{key:string;asset:string;currency:string;expiry:string;multiplier:number;count:number}[] {
  const groups=new Map<string,{key:string;asset:string;currency:string;expiry:string;multiplier:number;count:number}>();
  for(const row of source.rows){const key=groupKey(row);const group=groups.get(key);if(group)group.count++;else groups.set(key,{key,asset:row.asset,currency:row.currency,expiry:row.expiry,multiplier:row.multiplier,count:1});}
  return [...groups.values()].sort((a,b)=>a.asset.localeCompare(b.asset)||a.currency.localeCompare(b.currency)||a.expiry.localeCompare(b.expiry)||a.multiplier-b.multiplier);
}
