// Real unpacked-extension acceptance inside browser-smoke's disposable profile.
// https://chromedevtools.github.io/devtools-protocol/tot/Extensions/
// https://developer.chrome.com/docs/extensions/how-to/test/puppeteer
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

export async function verifyExtension({ send, until, origin, mainTargetId,
  extensionDir, outputDir, report, setExtensionId, stopDemo, startDemo }) {
  const manifest = JSON.parse(await readFile(path.join(extensionDir, "manifest.json"), "utf8"));
  assert.equal(manifest.manifest_version, 3, "Expected the built Manifest V3 companion");
  await stopDemo();
  const { id } = await send("Extensions.loadUnpacked", { path: extensionDir });
  setExtensionId(id);
  report.extension = { id, version: manifest.version, surface: "pending" };
  const worker = await until(async () => (await send("Target.getTargets")).targetInfos.find(
    (target) => target.type === "service_worker" && target.url.startsWith(`chrome-extension://${id}/`)), "real extension service worker");
  const workerSession = (await send("Target.attachToTarget", { targetId: worker.targetId, flatten: true })).sessionId;
  await send("Runtime.enable", {}, workerSession);
  await send("Network.enable", {}, workerSession);
  await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] }, workerSession);
  // Configure only this newly loaded extension so onboarding never contacts a user's port 8000.
  await send("Extensions.setStorageItems", { id, storageArea: "local", values: { engineConfig: { origin } } }, workerSession);
  const panelUrl = `chrome-extension://${id}/${manifest.side_panel.default_path}`;
  let panelTarget;
  try {
    const tabs = (await send("Target.getTargets", { filter: [{ type: "tab", exclude: false }] })).targetInfos;
    const tabTargetId = tabs.find((target) => target.type === "tab" && target.url.startsWith(origin))?.targetId ?? mainTargetId;
    await send("Extensions.triggerAction", { id, targetId: tabTargetId });
    panelTarget = await until(async () => (await send("Target.getTargets")).targetInfos.find(
      (target) => target.url === panelUrl), "native extension side panel target", 3000);
    report.extension.surface = "native side panel";
  } catch (error) {
    // A real extension page still exercises chrome.runtime and its installed service worker.
    // Explicitly retain this limitation instead of claiming native side-panel activation.
    report.extension.nativePanelLimitation = error.message;
    const { targetId } = await send("Target.createTarget", { url: "about:blank" });
    panelTarget = { targetId };
    report.extension.surface = "installed extension page";
  }
  const sessionId = (await send("Target.attachToTarget", { targetId: panelTarget.targetId, flatten: true })).sessionId;
  const panel = (method, params = {}) => send(method, params, sessionId);
  const evaluate = async (expression) => {
    const result = await panel("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const has = (selector) => evaluate(`[...document.querySelectorAll(${JSON.stringify(selector)})].some((element) => element.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}))`);
  const enabled = (label) => evaluate(`[...document.querySelectorAll('button')].some((button) => button.innerText.trim() === ${JSON.stringify(label)} && button.checkVisibility() && !button.disabled)`);
  const connected = () => evaluate(`(() => {
    const visible = (element) => element.checkVisibility({checkOpacity:true, checkVisibilityCSS:true});
    const refresh = [...document.querySelectorAll('.panel-header button')].find((button) => button.innerText.trim() === '刷新研究');
    const metadata = document.querySelector('.strategy-brief-meta');
    return Boolean(refresh && visible(refresh) && !refresh.disabled && metadata && visible(metadata)
      && ![...document.querySelectorAll('[role=alert]')].some(visible)
      && ![...document.querySelectorAll('p')].some((element) => visible(element) && element.innerText.includes('正在读取本地研究报告'))
      && ![...document.querySelectorAll('.panel-settings button')].some((button) => visible(button) && (button.disabled || button.innerText.includes('保存中'))));
  })()`);
  const click = async (label) => {
    await until(() => enabled(label), `enabled extension control: ${label}`);
    const point = await evaluate(`(() => {
      const element = [...document.querySelectorAll('button')].find((button) => button.innerText.trim() === ${JSON.stringify(label)} && button.checkVisibility());
      if (!element || element.disabled) throw new Error('Missing enabled extension control: ' + ${JSON.stringify(label)});
      element.scrollIntoView({block:'center', behavior:'instant'});
      const box = element.getBoundingClientRect(); return {x:box.x + box.width/2, y:box.y + box.height/2};
    })()`);
    await panel("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, ...point });
    await panel("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, ...point });
  };
  const visibleText = (text) => evaluate(`[...document.querySelectorAll('p, h2')].some((element) => element.checkVisibility() && element.innerText.includes(${JSON.stringify(text)}))`);
  await panel("Runtime.enable");
  await panel("Network.enable");
  await panel("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
  await panel("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  if (report.extension.surface === "installed extension page") await panel("Page.navigate", { url: panelUrl });
  try {
    await until(() => visibleText("本地引擎离线 · 首次设置"), "real extension first connection guide");
    assert(await has(".panel-settings input"), "First connection settings must be visible without opening evidence");
    assert(await evaluate("document.querySelector('.panel-settings input').value === " + JSON.stringify(origin)), "Settings must show this run's loopback origin");
    assert(!await has(".strategy-brief-strategy"), "First connection cannot fabricate strategy cards");
    report.checks.push("real extension first connection guide and settings are visible");
    await startDemo();
    await click("保存地址");
    // The generic brief shell also exists while loading. Wait for actual report
    // metadata and both load/save completion before stopping the engine.
    await until(connected, "real extension finishes saving and loads report metadata through its service worker");
    report.checks.push("real extension settings save connects to the installed engine");
    await stopDemo();
    await click("刷新研究");
    await until(async () => await visibleText("本地引擎离线 · 显示上次结果") && await enabled("刷新研究"), "real extension finishes the failed refresh and shows cached provenance");
    assert(await visibleText("当前排名和策略条件已收起"), "Cached extension result must be clearly withheld as current evidence");
    report.checks.push("real extension disconnection visibly withdraws current evidence");
    await startDemo();
    await click("重试");
    await until(connected, "real extension retry finishes and restores actual report metadata");
    const size = await evaluate("({viewport: innerWidth, document: document.documentElement.scrollWidth})");
    assert(size.document <= size.viewport + 1, "Installed extension has horizontal overflow at 390px");
    report.checks.push("real extension retry restores the installed engine connection");
    if (outputDir) {
      await evaluate("window.scrollTo({top:0, left:0, behavior:'instant'})");
      const { data } = await panel("Page.captureScreenshot", { format: "png" });
      await writeFile(path.join(outputDir, "extension.png"), Buffer.from(data, "base64"));
    }
  } catch (error) {
    report.extension.diagnostic = await evaluate("({url:location.href, body:(document.body?.innerText||'').slice(0,4000), reportMetadata:document.querySelector('.strategy-brief-meta')?.innerText, buttons:[...document.querySelectorAll('button')].map(button=>({label:button.innerText, disabled:button.disabled}))})").catch(() => null);
    if (outputDir) {
      const failure = await panel("Page.captureScreenshot", { format: "png" }).catch(() => null);
      if (failure) await writeFile(path.join(outputDir, "extension-failure.png"), Buffer.from(failure.data, "base64"));
    }
    throw error;
  }
  // Own-profile installation disappears with profile cleanup; no user extension is modified.
}
