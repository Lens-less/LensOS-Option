import { webcrypto } from 'node:crypto';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QuoteWorkbenchApp } from './QuoteWorkbenchApp';
import { ImportPanel } from './ImportPanel';
import { PLAN_STORAGE_KEY } from './plans';

beforeEach(()=>{localStorage.clear();vi.stubGlobal('crypto',webcrypto);vi.spyOn(window,'scrollTo').mockImplementation(()=>{});vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});URL.createObjectURL=vi.fn(()=> 'blob:local');URL.revokeObjectURL=vi.fn();});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});
async function chooseSample(version:'A'|'B'='A') {
 fireEvent.click(screen.getByText('还没有文件？先用合成样例试跑'));
 fireEvent.click(screen.getByRole('button',{name:version==='A'?'载入示例 A':'载入示例 B · 后续报价'}));
 fireEvent.click(screen.getByRole('checkbox',{name:/我已核对报价单位/}));
 fireEvent.click(screen.getByRole('button',{name:/确认定义，进入筛选|按原合约复核/}));
}
async function discoverSample(){await chooseSample();await screen.findByRole('heading',{name:'先定方向，再比较同方向结构'});fireEvent.click(screen.getByRole('checkbox',{name:/我确认费用、份数与限额/}));fireEvent.click(screen.getByRole('button',{name:'枚举并筛选完整价差 →'}));await waitFor(()=>expect(screen.getAllByRole('checkbox',{name:/^比较 /}).length).toBeGreaterThan(2));}

describe('quote → actual conditions → compare → frozen plan → exact later CSV',()=>{
 it('completes the full working flow, exports and appends review without fetch',async()=>{
  const network=vi.spyOn(globalThis,'fetch').mockRejectedValue(new Error('forbidden'));
  const view=render(<QuoteWorkbenchApp />);
  expect(screen.queryByRole('checkbox',{name:/^比较 /})).toBeNull();
  await discoverSample();
  const choices=screen.getAllByRole('checkbox',{name:/^比较 /});fireEvent.click(choices[0]);fireEvent.click(choices[1]);
  fireEvent.click(screen.getByRole('button',{name:'比较已选结构 →'}));
  await screen.findByRole('heading',{name:'相同假设，看看你更在意什么'});
  fireEvent.click(screen.getByRole('radio',{name:/候选 1/}));
  fireEvent.change(screen.getByRole('textbox',{name:'选择理由或尚待验证的问题'}),{target:{value:'保留完整保护腿，先核对后续报价和费用。'}});
  fireEvent.click(screen.getByRole('button',{name:'冻结为研究计划'}));
  await screen.findByText('原始判断永久保留');
  const original=JSON.parse(localStorage.getItem(PLAN_STORAGE_KEY)!).plans[0];expect(original.events).toHaveLength(0);
  fireEvent.click(screen.getByRole('button',{name:'导出计划 JSON ↗'}));expect(URL.createObjectURL).toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'选择下一份报价 CSV'}));await chooseSample('B');
  await screen.findByText('精确合约匹配，等待你记录判断');
  fireEvent.change(screen.getByRole('textbox',{name:'记录理由'}),{target:{value:'报价变化已记录，暂时继续研究。'}});
  fireEvent.click(screen.getByRole('button',{name:'追加一条记录，不覆盖原版'}));
  await screen.findByText('研究版本历史 · 1 次');
  const latest=JSON.parse(localStorage.getItem(PLAN_STORAGE_KEY)!).plans[0];expect(latest.long).toEqual(original.long);expect(latest.rationale).toBe(original.rationale);expect(latest.events).toHaveLength(1);
  view.unmount();render(<QuoteWorkbenchApp />);fireEvent.click(screen.getByRole('button',{name:/03.*研究计划/}));await screen.findByText('研究版本历史 · 1 次');
  expect(network).not.toHaveBeenCalled();
 });
 it('actually filters to zero and disables stale-result comparison after changing risk limit',async()=>{
  render(<QuoteWorkbenchApp />);await discoverSample();
  fireEvent.change(screen.getByRole('spinbutton',{name:/理论到期损失限额/}),{target:{value:'1'}});
  expect(screen.getByRole('button',{name:'比较已选结构 →'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'按新条件重新筛选'}));
  await screen.findByRole('heading',{name:'没有结构满足这组条件'});
  expect(screen.queryByRole('checkbox',{name:/^比较 /})).toBeNull();
 });
 it('shows separate date charts when comparing different expiries',async()=>{
  render(<QuoteWorkbenchApp />);await discoverSample();
  fireEvent.click(screen.getAllByRole('checkbox',{name:/^比较 .*2026-10-22/})[0]);
  fireEvent.click(screen.getAllByRole('checkbox',{name:/^比较 .*2026-11-19/})[0]);
  fireEvent.click(screen.getByRole('button',{name:'比较已选结构 →'}));
  await screen.findByText(/期限不同，分开作图/);expect(screen.getAllByRole('img')).toHaveLength(2);
 });
 it('offers export rather than claiming local save succeeded after quota failure',async()=>{
  render(<QuoteWorkbenchApp />);await discoverSample();const options=screen.getAllByRole('checkbox',{name:/^比较 /});fireEvent.click(options[0]);fireEvent.click(options[1]);fireEvent.click(screen.getByRole('button',{name:'比较已选结构 →'}));
  fireEvent.click(screen.getByRole('radio',{name:/候选 1/}));fireEvent.change(screen.getByRole('textbox',{name:'选择理由或尚待验证的问题'}),{target:{value:'保留这次比较'}});
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new Error('quota');});fireEvent.click(screen.getByRole('button',{name:'冻结为研究计划'}));
  expect(screen.getByRole('alert')).toHaveTextContent('尚未保存');expect(screen.getByRole('button',{name:'直接导出未保存的计划'})).toBeEnabled();expect(localStorage.getItem(PLAN_STORAGE_KEY)).toBeNull();
 });
});

describe('interrupted import is not a late navigation command',()=>{
 it('ignores a hash completion after Cancel unmounts the importer',async()=>{
  let resolve!:(value:ArrayBuffer)=>void;
  vi.spyOn(crypto.subtle,'digest').mockImplementation(()=>new Promise(done=>{resolve=done;}) as Promise<ArrayBuffer>);
  const onSource=vi.fn();let view:ReturnType<typeof render>;
  view=render(<ImportPanel onSource={onSource} onCancel={()=>view.unmount()} />);
  await chooseSample();expect(screen.getByRole('button',{name:'正在本地处理…'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'取消'}));
  await act(async()=>{resolve(new Uint8Array(32).buffer);await Promise.resolve();});expect(onSource).not.toHaveBeenCalled();
 });
 it('does not restore a cancelled file read',async()=>{
  let resolve!:(text:string)=>void;const onSource=vi.fn();let view:ReturnType<typeof render>;
  view=render(<ImportPanel onSource={onSource} onCancel={()=>view.unmount()} />);
  const file={size:100,name:'later.csv',text:()=>new Promise<string>(done=>{resolve=done;})};
  fireEvent.change(screen.getByLabelText('选择本地报价 CSV'),{target:{files:[file]}});fireEvent.click(screen.getByRole('button',{name:'取消'}));
  await act(async()=>{resolve('a,b\nx,y');await Promise.resolve();});expect(onSource).not.toHaveBeenCalled();
 });
});
