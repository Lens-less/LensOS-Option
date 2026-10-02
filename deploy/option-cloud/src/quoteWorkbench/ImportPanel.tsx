import { useEffect, useMemo, useRef, useState } from 'react';
import { ALL_FIELDS, EMPTY_DEFAULTS, FIELD_LABELS, MAX_FILE_BYTES, REQUIRED_FIELDS, normalizeCsv, parseCsv, sourceFromCsv, suggestMapping,
  type ColumnMap, type ImportDefaults, type QuoteSource, type RawTable } from './csv';
import { CSV_HEADER, downloadText, sampleCsv } from './samples';

interface Pending {text:string;name:string;table:RawTable;synthetic:boolean}
export function ImportPanel({onSource,onCancel,review=false}:{onSource:(source:QuoteSource)=>void;onCancel?:()=>void;review?:boolean}):React.JSX.Element {
  const fileRef=useRef<HTMLInputElement>(null);const [pending,setPending]=useState<Pending|null>(null);
  const [mapping,setMapping]=useState<ColumnMap>(()=>suggestMapping([]));const [defaults,setDefaults]=useState<ImportDefaults>({...EMPTY_DEFAULTS});
  const [confirmed,setConfirmed]=useState(false);const [error,setError]=useState<string|null>(null);const [busy,setBusy]=useState(false);
  const sequence=useRef(0);useEffect(()=>()=>{++sequence.current;},[]);
  const prepare=(text:string,name:string,synthetic=false)=>{
    try{const table=parseCsv(text);setPending({text,name,table,synthetic:synthetic||/SYNTHETIC-(BTC|ETH)-/.test(text)});setMapping(suggestMapping(table.headers));setDefaults({...EMPTY_DEFAULTS});setConfirmed(false);setError(null);}
    catch(failure){setError(failure instanceof Error?failure.message:'CSV 无法读取');setPending(null);}
  };
  const read=async(file:File)=>{if(busy)return;if(file.size>MAX_FILE_BYTES){setError('文件超过 5 MB，请先缩小到需要的报价范围');return;}const request=++sequence.current;setBusy(true);try{const text=await file.text();if(request===sequence.current)prepare(text,file.name);}catch{if(request===sequence.current)setError('无法读取该本地文件');}finally{if(request===sequence.current)setBusy(false);}};
  const preview=useMemo(()=>{if(!pending)return null;try{return {...normalizeCsv(pending.table,mapping,defaults),error:null};}catch(failure){return {rows:[],issues:[],error:failure instanceof Error?failure.message:'请核对字段'};}},[pending,mapping,defaults]);
  const missing=REQUIRED_FIELDS.filter(field=>!mapping[field]);
  const confirm=async()=>{if(!pending||!confirmed||busy)return;const request=++sequence.current;setBusy(true);setError(null);try{const source=await sourceFromCsv(pending.text,pending.name,pending.table,mapping,defaults,pending.synthetic);if(request===sequence.current)onSource(source);}catch(failure){if(request===sequence.current)setError(failure instanceof Error?failure.message:'处理失败');}finally{if(request===sequence.current)setBusy(false);}};
  return <section className="q-import" aria-labelledby="import-title">
    <div className="q-section-heading"><div><span className="q-eyebrow">{review?'精确合约复核':'01 / 报价来源'}</span><h2 id="import-title">{review?'选择下一份报价链':'先放入你要研究的报价'}</h2>
      <p>CSV 只在此浏览器读取。不会上传，不连接账户，也不会替你下单。</p></div>{onCancel?<button className="q-button q-quiet" onClick={onCancel}>取消</button>:null}</div>
    <fieldset disabled={busy}><input ref={fileRef} type="file" accept=".csv,text/csv" className="q-file-input" aria-label="选择本地报价 CSV" onChange={event=>{const file=event.target.files?.[0];if(file)void read(file);event.target.value='';}} />
    <div className="q-dropzone" onDragOver={event=>event.preventDefault()} onDrop={event=>{event.preventDefault();const file=event.dataTransfer.files[0];if(file)void read(file);}}>
      <span className="q-file-mark" aria-hidden="true">↥</span><div><strong>{pending?.name??'拖入报价链 CSV，或选择本地文件'}</strong><p>逗号分隔 · 最多 5 MB / 5000 行 · 可含多个到期日</p></div>
      <button className="q-button q-primary" onClick={()=>fileRef.current?.click()}>{pending?'更换本地文件':'选择本地 CSV'}</button>
    </div>
    <div className="q-import-tools"><button onClick={()=>downloadText('option-chain-template.csv',CSV_HEADER+'\n','text/csv;charset=utf-8')}>下载空白标准模板 ↗</button>
      <details><summary>还没有文件？先用合成样例试跑</summary><div className="q-sample-options">
        <button className="q-button" onClick={()=>prepare(sampleCsv('a'),'合成示例-A.csv',true)}>载入示例 A</button>
        <button className="q-button" onClick={()=>prepare(sampleCsv('b'),'合成示例-B.csv',true)}>载入示例 B · 后续报价</button>
        <button className="q-button" onClick={()=>prepare(sampleCsv('bad'),'合成错误示例.csv',true)}>检查错误样例</button>
        <button className="q-button q-quiet" onClick={()=>downloadText('合成示例-A.csv',sampleCsv('a'),'text/csv;charset=utf-8')}>下载 A</button>
        <button className="q-button q-quiet" onClick={()=>downloadText('合成示例-B.csv',sampleCsv('b'),'text/csv;charset=utf-8')}>下载 B</button>
        <p>均为 2026-10-01 的虚构报价，演示完整文件流程，不是历史市场表现。</p></div></details></div>
    {error?<div className="q-alert" role="alert">{error}</div>:null}
    {!pending?<div className="q-import-guidance"><p><strong>需要的是完整报价链，不是持仓或成交清单。</strong>从你有权使用的数据源取得 Bid / Ask、合约定义和时间，再映射为模板字段；本版没有一键券商导出。</p>
      <p>支持 BTC / ETH、USD / USDC / USDT 计价的欧式线性现金期权。美式、实物交割、币本位反向合约不在此计算范围。</p></div>:<>
      <div className="q-import-summary"><span>{pending.table.rows.length} 原始行</span><span>{preview?.rows.length??0} 可识别行</span><span>{preview?.issues.length??0} 行问题</span>
        <strong className={pending.synthetic?'q-amber':'q-muted'}>{pending.synthetic?'合成示例，非市场数据':'用户文件，来源未独立核验'}</strong></div>
      <details className="q-mapping" open={missing.length>0||!!preview?.error}><summary>核对字段映射 <span>{REQUIRED_FIELDS.length-missing.length} / {REQUIRED_FIELDS.length} 个必需列已匹配</span></summary>
        <div className="q-field-grid">{ALL_FIELDS.map(field=><label key={field}>{FIELD_LABELS[field]}{REQUIRED_FIELDS.includes(field)?' *':'（可选）'}<select aria-label={`映射${FIELD_LABELS[field]}`} value={mapping[field]} onChange={event=>{setMapping({...mapping,[field]:event.target.value});setConfirmed(false);}}>
          <option value="">未映射</option>{pending.table.headers.map(header=><option key={header} value={header}>{header}</option>)}</select></label>)}</div>
        <div className="q-definition-defaults"><h3>文件未提供时，明确填写统一定义</h3><p>只填缺失字段；有列的行不会被统一值悄悄覆盖。乘数不是推荐数量。</p><div className="q-field-grid">
          <label>统一结算币种<select value={defaults.currency} onChange={e=>{setDefaults({...defaults,currency:e.target.value});setConfirmed(false);}}><option value="">不假设</option>{['USD','USDC','USDT'].map(v=><option key={v}>{v}</option>)}</select></label>
          <label>统一合约乘数<input type="number" min="0.00000001" step="any" value={defaults.multiplier} onChange={e=>{setDefaults({...defaults,multiplier:e.target.value});setConfirmed(false);}} placeholder="例如 1；必须核对" /></label>
          <label>统一报价单位<select value={defaults.quoteUnit} onChange={e=>{setDefaults({...defaults,quoteUnit:e.target.value});setConfirmed(false);}}><option value="">不假设</option><option value="per_underlying">每基础资产单位</option><option value="per_contract">每张合约</option></select></label>
          <label>统一行权方式<select value={defaults.exercise} onChange={e=>{setDefaults({...defaults,exercise:e.target.value});setConfirmed(false);}}><option value="">不假设</option><option value="european">欧式</option></select></label>
          <label>统一结算方式<select value={defaults.settlement} onChange={e=>{setDefaults({...defaults,settlement:e.target.value});setConfirmed(false);}}><option value="">不假设</option><option value="cash_linear">线性现金</option></select></label>
        </div></div>
      </details>
      {preview?.error?<div className="q-alert" role="alert">{preview.error}</div>:null}
      {preview?.rows.length?<div className="q-table-scroll"><table className="q-table"><caption>前 5 行归一化预览 · 报价已转为每基础资产单位</caption><thead><tr><th>原行</th><th>合约 / 到期 UTC</th><th>乘数 / 币种</th><th>Bid / Ask</th><th>原报价单位</th></tr></thead><tbody>{preview.rows.slice(0,5).map(row=><tr key={row.row}><td>{row.row}</td><td>{row.instrument}<small>{row.expiry}</small></td><td>{row.multiplier} / {row.currency}</td><td>{row.bid} / {row.ask}</td><td>{row.quoteUnit==='per_contract'?'每张合约':'每基础资产单位'}</td></tr>)}</tbody></table></div>:null}
      {preview?.issues.length?<details className="q-row-errors" open={!preview.rows.length}><summary>{preview.issues.length} 行问题，查看定位与原因</summary><ul>{preview.issues.slice(0,100).map((issue,i)=><li key={`${issue.row}:${i}`}><strong>第 {issue.row} 行 · {issue.instrument||'无合约标识'}</strong><span>{issue.detail}</span></li>)}</ul>{preview.issues.length>100?<p>先显示 100 项；修改文件后重新载入。</p>:null}</details>:null}
      <label className="q-confirm"><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)} />我已核对报价单位、乘数及合约定义；以文件中的原始时点研究，不将它当作实时或已成交报价</label>
      <div className="q-import-submit"><p>{preview?.issues.length?'有问题的行会明确排除，其他行仍可继续。':'缺少报价数量时只提示容量未知，不假定足够成交。'}</p>
        <button className="q-button q-primary" disabled={!confirmed||busy||!!preview?.error||!preview?.rows.length} onClick={()=>void confirm()}>{busy?'正在本地处理…':review?'按原合约复核':'确认定义，进入筛选 →'}</button></div>
    </>}</fieldset>
  </section>;
}
