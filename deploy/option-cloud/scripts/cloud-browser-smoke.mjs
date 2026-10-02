// One bounded production-build browser journey. Uses the repository's existing
// isolated Chromium/CDP approach, Node built-ins, and synthetic local CSV only.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { sampleCsv } from '../src/quoteWorkbench/samples.ts';

const output=path.resolve('browser-artifacts');await mkdir(output,{recursive:true});
const temporary=await mkdtemp(path.join(tmpdir(),'option-cloud-acceptance-'));
const report={commit:process.env.GITHUB_SHA??null,checks:[],errors:[],externalRequests:[],screenshots:[]};
let browser,socket,server,page,evaluate;const pending=new Map();const events=new Map();let counter=0;
async function until(check,label,timeout=20000){const deadline=Date.now()+timeout;while(Date.now()<deadline){const answer=await check();if(answer)return answer;await delay(100);}throw new Error(`Timed out: ${label}`);}
try{
 const dist=path.resolve('dist');assert(existsSync(path.join(dist,'index.html')),'production build missing');
 server=createServer(async(req,res)=>{try{let name=decodeURIComponent(new URL(req.url,'http://localhost').pathname);if(name==='/')name='/index.html';const file=path.resolve(dist,'.'+name);if(!file.startsWith(dist+path.sep)){res.writeHead(403);res.end();return;}const bytes=await readFile(file);const type=file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream';res.writeHead(200,{'content-type':type});res.end(bytes);}catch{res.writeHead(404);res.end('not found');}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${server.address().port}`;
 const executable=['/usr/bin/google-chrome','/usr/bin/google-chrome-stable','/usr/bin/chromium','/usr/bin/chromium-browser'].find(existsSync);assert(executable,'runner must provide Chrome/Chromium');
 let stderr='';browser=spawn(executable,['--headless=new','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',`--user-data-dir=${path.join(temporary,'profile')}`,'--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:['ignore','ignore','pipe']});
 browser.stderr.on('data',chunk=>stderr=(stderr+chunk).slice(-16000));
 const endpoint=await until(()=>{if(browser.exitCode!==null)throw new Error(stderr);return stderr.match(/DevTools listening on (ws:\/\/127\.0\.0\.1:\d+\/\S+)/)?.[1];},'Chromium startup');
 socket=new WebSocket(endpoint);await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
 const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const id=++counter;const timer=setTimeout(()=>{pending.delete(id);reject(new Error(`CDP timeout ${method}`));},20000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});
 socket.addEventListener('message',({data})=>{const message=JSON.parse(data);if(message.id){const item=pending.get(message.id);if(!item)return;pending.delete(message.id);clearTimeout(item.timer);if(message.error)item.reject(new Error(JSON.stringify(message.error)));else item.resolve(message.result);}else for(const handler of events.get(message.method)??[])Promise.resolve(handler(message.params)).catch(error=>report.errors.push(error.message));});
 const on=(name,handler)=>events.set(name,[...(events.get(name)??[]),handler]);
 const {targetId}=await send('Target.createTarget',{url:'about:blank'});const {sessionId}=await send('Target.attachToTarget',{targetId,flatten:true});
 page=(method,params={})=>send(method,params,sessionId);
 evaluate=async(expression)=>{const r=await page('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});assert(!r.exceptionDetails,JSON.stringify(r.exceptionDetails));return r.result.value;};
 on('Runtime.exceptionThrown',({exceptionDetails})=>report.errors.push(exceptionDetails.exception?.description??exceptionDetails.text));
 on('Runtime.consoleAPICalled',({type,args})=>{if(type==='error')report.errors.push(args.map(arg=>arg.value??arg.description).join(' '));});
 on('Fetch.requestPaused',async({requestId,request})=>{const url=new URL(request.url);const allowed=url.origin===origin||['blob:','data:','about:'].includes(url.protocol);if(!allowed||!['GET','HEAD'].includes(request.method)||request.hasPostData||request.postData){report.externalRequests.push({url:request.url,method:request.method,hasBody:!!request.postData||!!request.hasPostData});await page('Fetch.failRequest',{requestId,errorReason:'BlockedByClient'});}else await page('Fetch.continueRequest',{requestId});});
 await page('Runtime.enable');await page('Page.enable');await page('DOM.enable');await page('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
 await send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:output,eventsEnabled:true});
 await page('Emulation.setDeviceMetricsOverride',{width:1365,height:900,deviceScaleFactor:1,mobile:false});
 await page('Page.navigate',{url:origin});await until(()=>evaluate(`document.querySelector('.q-dropzone')!==null`),'production workbench entry');
 assert.equal(await evaluate(`document.querySelectorAll('.q-candidate-table input').length`),0,'must not replace input with preloaded demo');
 const click=async(text)=>{await until(()=>evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent.trim().includes(${JSON.stringify(text)})&&!b.disabled)`),`enabled button ${text}`);await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim().includes(${JSON.stringify(text)})&&!b.disabled).click()`);};
 const fill=async(selector,value)=>evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)throw Error('missing field');const p=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:e.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(p,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
 const upload=async(file)=>{const {root}=await page('DOM.getDocument');const {nodeId}=await page('DOM.querySelector',{nodeId:root.nodeId,selector:'input[aria-label="选择本地报价 CSV"]'});assert(nodeId,'file input');await page('DOM.setFileInputFiles',{nodeId,files:[file]});await until(()=>evaluate(`document.querySelector('.q-import-summary')?.textContent.includes('40 原始行')`),'local CSV preview');await evaluate(`document.querySelector('.q-confirm input').click()`);};
 const a=path.join(temporary,'SYNTHETIC-A.csv'),b=path.join(temporary,'SYNTHETIC-B.csv');await writeFile(a,sampleCsv('a'));await writeFile(b,sampleCsv('b'));
 await upload(a);await click('确认定义，进入筛选');await until(()=>evaluate(`!!document.querySelector('.q-filter-panel')`),'real condition controls');
 await evaluate(`document.querySelector('.q-filter-panel .q-confirm input').click()`);await click('枚举并筛选完整价差');await until(()=>evaluate(`document.querySelectorAll('.q-candidate-table input[type=checkbox]').length>=2`),'actual candidates');
 await evaluate(`Array.from(document.querySelectorAll('.q-candidate-table input[type=checkbox]')).slice(0,2).forEach(e=>e.click())`);await click('比较已选结构');
 await until(()=>evaluate(`document.querySelectorAll('.q-payoff svg').length>0`),'calculated expiry comparison');
 await evaluate(`document.fonts.ready`);
 const screenshot=async(name)=>{const metrics=await page('Page.getLayoutMetrics');const width=await evaluate('window.innerWidth');const height=Math.min(16000,Math.ceil(metrics.cssContentSize.height));const image=await page('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width,height,scale:1}});await writeFile(path.join(output,name),Buffer.from(image.data,'base64'));report.screenshots.push(name);};
 await screenshot('01-comparison-desktop.png');
 await evaluate(`document.querySelector('input[name="chosen-plan"]').click()`);await fill('.q-note-label textarea','Synthetic acceptance: preserve exact legs, costs and quote evidence.');await click('冻结为研究计划');
 await until(()=>evaluate(`!!document.querySelector('.q-plan-detail')`),'frozen plan');
 const original=await evaluate(`JSON.parse(localStorage.getItem('lensos-option.research-plans.v2')).plans[0]`);assert.equal(original.events.length,0);
 await click('导出计划 JSON');const downloaded=await until(async()=>{const files=await readdir(output);return files.find(name=>name.startsWith('option-plan-')&&name.endsWith('.json'));},'downloaded research plan');
 const exported=JSON.parse(await readFile(path.join(output,downloaded),'utf8'));assert.equal(exported.id,original.id);assert.equal(exported.long.instrument,original.long.instrument);assert.equal(exported.source.synthetic,true);
 await click('选择下一份报价 CSV');await upload(b);await click('按原合约复核');await until(()=>evaluate(`document.querySelector('.q-review-ready')?.textContent.includes('精确合约匹配')`),'exact second-file match');
 await fill('.q-review-form textarea','Synthetic acceptance: later exact quotes, no account or executed P&L.');await click('追加一条记录');
 await until(()=>evaluate(`JSON.parse(localStorage.getItem('lensos-option.research-plans.v2')).plans[0].events.length===1`),'appended research revision');
 const reviewed=await evaluate(`JSON.parse(localStorage.getItem('lensos-option.research-plans.v2')).plans[0]`);assert.deepEqual(reviewed.long,original.long);assert.deepEqual(reviewed.short,original.short);assert.equal(reviewed.rationale,original.rationale);assert.equal(reviewed.events[0].review.status,'matched');assert(reviewed.events[0].review.long.quotedAt>original.long.quotedAt);
 report.checks.push('production entry contains no preloaded fake opportunity','real local CSV A import and normalization','actual condition filtering and expiry comparison','freeze exact legs and JSON download','real local CSV B exact-leg review','original evidence unchanged after append');
 await page('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await until(()=>evaluate(`window.innerWidth===390`),'390px mobile viewport');const overflow=await evaluate(`({viewport:window.innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth})`);assert(overflow.document<=391&&overflow.body<=391,`mobile page overflow ${JSON.stringify(overflow)}`);
 await screenshot('02-review-mobile.png');report.checks.push('390px layout has no document-level horizontal overflow');
 assert.deepEqual(report.externalRequests,[],'no quote/file content may leave the browser');assert.deepEqual(report.errors,[],'browser runtime/console errors');report.checks.push('no external or body-bearing browser requests','no browser runtime errors');
 report.status='passed';console.log(JSON.stringify(report,null,2));
}catch(error){report.status='failed';report.errors.push(error.stack??String(error));if(page){try{const shot=await page('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await writeFile(path.join(output,'failure.png'),Buffer.from(shot.data,'base64'));}catch{}}process.exitCode=1;console.error(error);
}finally{
 await writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
 for(const item of pending.values()){clearTimeout(item.timer);item.reject(new Error('browser smoke cleanup'));}pending.clear();
 if(socket)socket.close();
 if(browser&&browser.exitCode===null&&browser.signalCode===null){
  browser.kill('SIGTERM');
  await until(()=>browser.exitCode!==null||browser.signalCode!==null,'Chromium shutdown',5000).catch(async()=>{
   browser.kill('SIGKILL');await until(()=>browser.exitCode!==null||browser.signalCode!==null,'forced Chromium shutdown',5000);
  });
 }
 if(server)await new Promise(resolve=>server.close(resolve));
 // Renderer/profile writers can finish just after the browser parent exits.
 await rm(temporary,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}
