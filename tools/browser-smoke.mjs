#!/usr/bin/env node
// A bounded release journey, using only Node's standard library and a new browser profile.
// Protocol references: https://developer.chrome.com/blog/remote-debugging-port
// https://chromedevtools.github.io/devtools-protocol/tot/{Fetch,Emulation,Runtime,Input}/
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { parseArgs } from "node:util";
import { verifyExtension } from "./extension-browser-smoke.mjs";
import { verifyPublic } from "./public-browser-smoke.mjs";

const { values } = parseArgs({ options: {
  python: { type: "string" },
  "output-dir": { type: "string" },
  "extension-dir": { type: "string" },
  "public-build-dir": { type: "string" },
  help: { type: "boolean", short: "h" },
} });
if (values.help) {
  console.log("Usage: node tools/browser-smoke.mjs --python <installed-wheel venv Python> [--output-dir <artifacts>] [--extension-dir <built unpacked extension>] [--public-build-dir <built public site>]\nRequires Node >=22 and Chrome/Chromium (or BROWSER_PATH). Starts an isolated, hidden browser and loopback demo. Optional public checks use a real installed-wheel fixture publication; extension checks load the real build. No browser download or user profile access.");
  process.exit(0);
}
assert(Number(process.versions.node.split(".")[0]) >= 22, "Node >=22 is required");
assert(values.python && path.isAbsolute(values.python), "--python must be the absolute Python path of the installed-wheel virtual environment");
const browserPaths = process.platform === "win32"
  ? ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe"]
  : process.platform === "darwin"
    ? ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    : ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser"];
const browserPath = process.env.BROWSER_PATH || browserPaths.find(existsSync);
assert(browserPath && existsSync(browserPath), "Chrome/Chromium not found; set BROWSER_PATH to its executable (no browser will be downloaded)");
const temporary = await mkdtemp(path.join(tmpdir(), "option-browser-check-"));
const profile = path.join(temporary, "profile");
const outputDir = values["output-dir"] ? path.resolve(values["output-dir"]) : null;
if (outputDir) await mkdir(outputDir, { recursive: true });
const report = { checks: [], errors: [], externalRequests: [] };
let browser;
let server;
let socket;
let send;
let page;
let evaluate;
let stderr = "";
let serverLog = "";
let demoOrigin;
let publicOrigin;
let publicFailure = null;
let extensionId;
const responses = [];
const failedLoads = [];
const requestPaths = new Map();

async function until(check, label, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await check();
    if (result) return result;
    await delay(100);
  }
  throw new Error(`Timed out: ${label}`);
}

async function freePort() {
  const reservation = createServer();
  await new Promise((resolve, reject) => {
    reservation.once("error", reject);
    reservation.listen(0, "127.0.0.1", resolve);
  });
  const { port } = reservation.address();
  await new Promise((resolve) => reservation.close(resolve));
  return port;
}

async function stop(child) {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  await until(() => child.exitCode !== null || child.signalCode !== null, "child shutdown", 5000)
    .catch(async () => {
      child.kill("SIGKILL");
      await until(() => child.exitCode !== null || child.signalCode !== null, "forced child shutdown", 5000);
    });
}

try {
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  demoOrigin = origin;
  // -I and a temporary cwd prevent accidentally testing checkout imports.
  const startDemo = async () => {
    server = spawn(values.python, ["-I", "-u", "-m", "crypto_options_report.demo", "--port", String(port), "--no-open-browser"], {
      cwd: temporary, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
    });
    server.on("error", (error) => { serverLog += error.message; });
    server.stdout.on("data", (chunk) => { serverLog = (serverLog + chunk).slice(-8000); });
    server.stderr.on("data", (chunk) => { serverLog = (serverLog + chunk).slice(-8000); });
    await until(async () => {
      if (server.exitCode !== null) throw new Error(`Installed demo exited: ${serverLog}`);
      try { return (await fetch(`${origin}/livez`, { signal: AbortSignal.timeout(1000) })).ok; }
      catch { return false; }
    }, "installed wheel demo startup");
  };
  await startDemo();
  browser = spawn(browserPath, [
    "--headless", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
    `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check",
    "--disable-background-networking", "--disable-component-update", "--disable-sync",
    "--disable-default-apps", values["extension-dir"] ? "--enable-unsafe-extension-debugging" : "--disable-extensions", "--no-proxy-server",
    // Chrome applies MAP rules to IP literals too; the generated demo origin uses 127.0.0.1.
    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1", "about:blank",
  ], { cwd: temporary, windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
  browser.on("error", (error) => { stderr += error.message; });
  browser.stderr.on("data", (chunk) => { stderr = (stderr + chunk).slice(-16000); });
  const endpoint = await until(() => {
    if (browser.exitCode !== null) throw new Error(`Isolated browser exited: ${stderr}`);
    return stderr.match(/DevTools listening on (ws:\/\/127\.0\.0\.1:\d+\/\S+)/)?.[1];
  }, "isolated browser DevTools endpoint");
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("Timed out connecting to isolated browser")), 10000);
    socket.addEventListener("open", () => { clearTimeout(timeout); resolve(); }, { once: true });
    socket.addEventListener("error", (error) => { clearTimeout(timeout); reject(error); }, { once: true });
  });
  let sequence = 0;
  const pending = new Map();
  const handlers = new Map();
  send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, { resolve, reject, timer, method });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const waiting = pending.get(message.id);
      if (!waiting) return;
      clearTimeout(waiting.timer);
      pending.delete(message.id);
      if (message.error) waiting.reject(new Error(`${waiting.method}: ${JSON.stringify(message.error)}`));
      else waiting.resolve(message.result);
    } else {
      for (const handler of handlers.get(message.method) ?? []) {
        Promise.resolve(handler(message.params, message.sessionId)).catch((error) => report.errors.push(error.message));
      }
    }
  });
  socket.addEventListener("close", () => {
    for (const { reject, timer } of pending.values()) {
      clearTimeout(timer);
      reject(new Error("Browser connection closed"));
    }
    pending.clear();
  });
  const on = (method, handler) => handlers.set(method, [...(handlers.get(method) ?? []), handler]);
  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  page = (method, params = {}) => send(method, params, sessionId);
  evaluate = async (expression) => {
    const result = await page("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const isLocal = (url) => {
    const parsed = new URL(url);
    return ["data:", "blob:", "about:"].includes(parsed.protocol) || parsed.origin === origin || parsed.origin === publicOrigin || (parsed.protocol === "chrome-extension:" && parsed.hostname === extensionId);
  };
  let failNextReport = false;
  let blockResearchReport = true;
  let simulatedReportFailures = 0;
  let blockedResearchReports = 0;
  let researchRequests = 0;
  on("Runtime.exceptionThrown", ({ exceptionDetails }) => report.errors.push(exceptionDetails.exception?.description || exceptionDetails.text));
  on("Runtime.consoleAPICalled", ({ type, args }) => {
    if (type === "error") report.errors.push(args.map((arg) => arg.description || arg.value).join(" "));
  });
  on("Network.webSocketCreated", ({ url }) => {
    if (!isLocal(url)) report.externalRequests.push(url);
  });
  on("Network.requestWillBeSent", ({ requestId, request }) => {
    if (new URL(request.url).origin === origin) requestPaths.set(requestId, new URL(request.url).pathname);
  });
  on("Network.responseReceived", ({ response }) => {
    if (new URL(response.url).origin === origin && responses.length < 50) {
      responses.push({ path: new URL(response.url).pathname, status: response.status, mimeType: response.mimeType });
    }
  });
  on("Network.loadingFailed", ({ requestId, errorText, canceled }) => {
    if (requestPaths.has(requestId) && failedLoads.length < 20) failedLoads.push({ path: requestPaths.get(requestId), errorText, canceled });
  });
  on("Fetch.requestPaused", async ({ requestId, request }, sourceSessionId) => {
    const respond = (method, params) => send(method, params, sourceSessionId);
    const requested = new URL(request.url);
    if (requested.origin === origin && /^\/research\/(report|signal|series)$/.test(requested.pathname)) researchRequests += 1;
    if (!isLocal(request.url)) {
      report.externalRequests.push(request.url);
      await respond("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" });
    } else if (publicFailure && requested.origin === publicOrigin && requested.pathname === "/research/report") {
      const failure = publicFailure;
      publicFailure = null;
      report.publicInjectedFaults ??= [];
      report.publicInjectedFaults.push(failure);
      if (failure === "network") await respond("Fetch.failRequest", { requestId, errorReason: "ConnectionFailed" });
      else await respond("Fetch.fulfillRequest", { requestId, responseCode: 200, responseHeaders: [{ name: "Content-Type", value: "application/json" }], body: Buffer.from("{malformed").toString("base64") });
    } else if (blockResearchReport && request.method === "GET" && request.url === `${origin}/research/report`) {
      blockedResearchReports += 1;
      await respond("Fetch.failRequest", { requestId, errorReason: "ConnectionFailed" });
    } else if (failNextReport && request.method === "GET" && request.url === `${origin}/research/report`) {
      failNextReport = false;
      simulatedReportFailures += 1;
      await respond("Fetch.failRequest", { requestId, errorReason: "ConnectionFailed" });
    } else {
      await respond("Fetch.continueRequest", { requestId });
    }
  });
  await page("Runtime.enable");
  await page("Page.enable");
  await page("Network.enable");
  await page("Network.setBypassServiceWorker", { bypass: true });
  await page("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
  const has = (selector) => evaluate(`[...document.querySelectorAll(${JSON.stringify(selector)})].some((element) => element.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}))`);
  const click = async (label) => {
    const point = await evaluate(`(() => {
      const element = [...document.querySelectorAll('button, a')].find((item) => item.textContent.trim() === ${JSON.stringify(label)} && item.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}));
      if (!element || element.disabled) throw new Error('Missing enabled control: ' + ${JSON.stringify(label)});
      element.scrollIntoView({block: 'center', behavior: 'instant'});
      const box = element.getBoundingClientRect();
      return {x: box.x + box.width / 2, y: box.y + box.height / 2};
    })()`);
    await page("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, ...point });
    await page("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, ...point });
  };
  const key = async (name, code) => {
    const params = { key: name, code: name, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code };
    await page("Input.dispatchKeyEvent", { type: "keyDown", ...params, ...(name === "Enter" ? { text: "\r", unmodifiedText: "\r" } : {}) });
    await page("Input.dispatchKeyEvent", { type: "keyUp", ...params });
  };
  const tabTo = async (expression, label) => {
    for (let index = 0; index < 50; index += 1) {
      if (await evaluate(expression)) return;
      await key("Tab", 9);
    }
    throw new Error(`Keyboard Tab could not reach ${label}`);
  };
  const keyboardActivate = async (label) => {
    await tabTo(`document.activeElement?.textContent.trim() === ${JSON.stringify(label)}`, label);
    assert(await evaluate("document.activeElement.checkVisibility() && !document.activeElement.disabled"), `Keyboard target ${label} is unavailable`);
    await key("Enter", 13);
  };
  const openNavigation = async () => {
    if (await has('[data-testid="mobile-navigation-toggle"][aria-expanded="false"]')) {
      const label = await evaluate("document.querySelector('[data-testid=mobile-navigation-toggle]').textContent.trim()");
      await click(label);
      await until(() => has('[data-testid="mobile-navigation-toggle"][aria-expanded="true"]'), "expanded mobile navigation");
    }
  };
  const inFirstViewport = async (selector, label) => {
    await evaluate("window.scrollTo({top:0, left:0, behavior:'instant'})");
    const boxes = await evaluate(`[...document.querySelectorAll(${JSON.stringify(selector)})].map((element) => {
      const box = element.getBoundingClientRect(); return {text:element.innerText, visible:element.checkVisibility(), top:box.top, bottom:box.bottom, height:innerHeight};
    })`);
    assert(boxes.length > 0 && boxes.every((box) => box.visible && box.top >= 0 && box.bottom <= box.height), `${label} must be readable in the first 390px viewport: ${JSON.stringify(boxes)}`);
    report.checks.push(label);
  };
  const noOverflow = async (name) => {
    const width = await evaluate("({viewport: innerWidth, document: document.documentElement.scrollWidth})");
    assert(width.document <= width.viewport + 1, `${name}: horizontal overflow ${JSON.stringify(width)}`);
    report.checks.push(name);
  };
  const screenshot = async (name) => {
    if (!outputDir) return;
    await evaluate("window.scrollTo({top: 0, left: 0, behavior: 'instant'})");
    const { data } = await page("Page.captureScreenshot", { format: "png" });
    await writeFile(path.join(outputDir, `${name}.png`), Buffer.from(data, "base64"));
  };
  await page("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  const navigation = await page("Page.navigate", { url: `${origin}/index.html` });
  assert(!navigation.errorText, `Research navigation failed: ${navigation.errorText}`);
  await until(() => evaluate("document.querySelector('[role=alert]')?.innerText.includes('研究数据不可用')"), "initial research connection failure");
  assert.equal(blockedResearchReports, 1, "Initial research request must encounter the controlled outage");
  await noOverflow("desktop research outage");
  const requestsBeforeLearning = researchRequests;
  await keyboardActivate("进入离线学习导览");
  await until(() => has('[data-testid="demo-tour"]'), "offline learning tour");
  assert(await evaluate("document.body.innerText.includes('离线学习导览')"), "Demo introduction must be visible");
  await noOverflow("desktop introduction");
  await screenshot("desktop");
  await keyboardActivate("查看风险与收益");
  await until(() => has('[data-testid="demo-risk-step"]'), "risk and payoff step");
  await tabTo("document.activeElement?.id === 'demo-expiry-price'", "teaching payoff slider");
  const priorPrice = await evaluate("Number(document.activeElement.value)");
  await key("ArrowRight", 39);
  assert.equal(await evaluate("Number(document.activeElement.value)"), priorPrice + 1, "ArrowRight must adjust the real teaching slider");
  await screenshot("desktop-risk");
  await keyboardActivate("查看证据与限制");
  await until(() => has('[data-testid="demo-evidence-step"]'), "evidence and limits step");
  report.checks.push("three-step offline learning journey");
  await page("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await noOverflow("mobile evidence step");
  await screenshot("mobile");
  await keyboardActivate("完成导览");
  await until(async () => await has("#demo-step-title") && await evaluate("document.querySelector('#demo-step-title').innerText === '你已完成导览'"), "visible completed tour heading");
  report.checks.push("explicit tour completion");
  report.checks.push("keyboard Tab and Enter complete the tour; arrow key adjusts payoff input");
  assert.equal(researchRequests, requestsBeforeLearning, "Independent learning must not request report, signal or series APIs");
  report.checks.push("research outage still allows a complete keyboard learning journey without research API requests");
  await click("查看真实快照");
  await until(() => evaluate("document.querySelector('[role=alert]')?.innerText.includes('研究数据不可用')"), "returning from learning preserves the real research outage");
  assert.equal(blockedResearchReports, 2, "Returning from learning must check the real research service again");
  await noOverflow("mobile research outage after learning");
  blockResearchReport = false;
  await keyboardActivate("重新读取");
  await until(async () => !await has('[data-testid="demo-tour"]') && await has('[data-freshness]'), "real snapshot view");
  report.checks.push("return from learning retries the real installed-wheel research service after recovery");
  await noOverflow("mobile real snapshot");
  await inFirstViewport(".strategy-brief-header h2, .strategy-brief-header > [role=status]", "mobile conclusion and action fit the first viewport");
  await screenshot("mobile-brief");
  await page("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await noOverflow("desktop real snapshot");
  await screenshot("desktop-brief");
  await page("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  assert(await has('[data-freshness="current"]'), "Snapshot must begin current before the controlled refresh failure");
  failNextReport = true;
  await openNavigation();
  await click("刷新");
  await until(() => evaluate(`[...document.querySelectorAll('[role="alert"]')].some((element) =>
    element.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) && element.innerText.includes('无法连接研究服务'))`), "visible connection failure after refresh");
  assert.equal(simulatedReportFailures, 1, "Exactly one loopback report request must be interrupted");
  assert(await evaluate("!document.querySelector('[data-freshness]') && !document.querySelector('#surface-main')"), "A failed refresh must withdraw the previous snapshot");
  report.checks.push("failed refresh withdraws the previous snapshot");
  await click("重新读取");
  await until(() => has('[data-freshness="current"]'), "retry restores a current snapshot");
  assert(!await evaluate("document.body.innerText.includes('无法连接研究服务')"), "Connection failure must clear after a successful retry");
  assert.equal(simulatedReportFailures, 1, "Retry must use the restored loopback connection");
  report.checks.push("retry restores a current snapshot after one loopback connection failure");
  for (const [label, region] of [["④ 排序验证", "信号验证进度"], ["② 波动时序", "序列验证进度"]]) {
    await openNavigation();
    await click(label);
    await until(() => has(`section[aria-label="${region}"]`), region);
    await noOverflow(`mobile ${region}`);
    await inFirstViewport(`section[aria-label="${region}"] h2, section[aria-label="${region}"] .research-next-step`, `mobile ${region} conclusion and next step fit the first viewport`);
    await screenshot(region === "信号验证进度" ? "mobile-signal" : "mobile-series");
  }
  await openNavigation();
  await click("① 研究简报");
  await until(() => has('[data-freshness="current"]'), "return to current brief before expiry");
  await evaluate("document.querySelectorAll('details').forEach((detail) => { detail.open = true; })");
  const before = await evaluate("Date.now()");
  let virtualTimeEnded = false;
  on("Emulation.virtualTimeBudgetExpired", () => { virtualTimeEnded = true; });
  await page("Emulation.setVirtualTimePolicy", { policy: "advance", budget: 65000, maxVirtualTimeTaskStarvationCount: 1000 });
  await until(() => virtualTimeEnded, "65 seconds of page time");
  const after = await evaluate("Date.now()");
  assert(after - before >= 65000, "Page clock did not advance beyond the freshness limit");
  await until(() => has('[data-freshness="expired"]'), "expired snapshot state");
  const staleNotices = await evaluate(`[...document.querySelectorAll('[role="alert"], [role="status"]')]
    .filter((element) => element.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) && /已失效|已过期|过期|停摆/.test(element.innerText))
    .map((element) => element.innerText)`);
  assert(staleNotices.length >= 2, "Expired snapshot must explain the stop state in multiple visible evidence sections");
  const contradictions = await evaluate(`(() => {
    const findings = [];
    for (const term of document.querySelectorAll('dt')) {
      if (term.checkVisibility() && term.textContent.trim() === '候选资格' && term.nextElementSibling?.textContent.trim() === '可用') findings.push('expired candidate remains available');
    }
    for (const row of document.querySelectorAll('li, tr, [role="alert"], [role="status"]')) {
      if (!row.checkVisibility()) continue;
      const text = row.innerText || '';
      if (text.includes('当前新鲜度') && /通过/.test(text) && !/未通过|不通过|已失效|过期|快照时/.test(text)) findings.push('expired freshness still passes');
    }
    return findings;
  })()`);
  assert.deepEqual(contradictions, [], "Expired snapshot contradicts current eligibility");
  report.checks.push("snapshot expires after 65 seconds without current eligibility");
  if (values["public-build-dir"]) {
    await verifyPublic({ send, until, python: values.python,
      publicBuildDir: path.resolve(values["public-build-dir"]), temporary, outputDir, report,
      setPublicOrigin: (value) => { publicOrigin = value; },
      setPublicFailure: (value) => { publicFailure = value; } });
    assert.deepEqual(report.publicInjectedFaults, ["network", "invalid"], "Public acceptance must actually exercise both controlled failures");
  }
  if (values["extension-dir"]) {
    await verifyExtension({ send, until, origin, mainTargetId: targetId,
      extensionDir: path.resolve(values["extension-dir"]), outputDir, report,
      setExtensionId: (id) => { extensionId = id; },
      stopDemo: () => stop(server), startDemo });
  }
  assert.deepEqual(report.externalRequests, [], "Page attempted non-loopback network access");
  assert.deepEqual(report.errors, [], "Browser reported JavaScript errors");
  report.checks.push("loopback-only page requests", "no unhandled JavaScript or console errors");
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.failure = error.stack || String(error);
  report.diagnostics = { responses, failedLoads };
  if (evaluate) {
    report.diagnostics.page = await evaluate(`(() => {
      if (location.origin !== ${JSON.stringify(demoOrigin)}) return { origin: location.origin, localDemo: false };
      return { url: location.href, readyState: document.readyState, title: document.title,
        body: (document.body?.innerText || '').slice(0, 4000),
        testIds: [...document.querySelectorAll('[data-testid]')].map((element) => element.dataset.testid).slice(0, 20) };
    })()`).catch((failure) => ({ diagnosticError: failure.message }));
    if (outputDir && report.diagnostics.page.localDemo !== false) {
      try {
        const { data } = await page("Page.captureScreenshot", { format: "png" });
        await writeFile(path.join(outputDir, "failure.png"), Buffer.from(data, "base64"));
      } catch (failure) { report.diagnostics.screenshotError = failure.message; }
    }
  }
  process.exitCode = 1;
} finally {
  if (send && socket?.readyState === WebSocket.OPEN) await send("Browser.close").catch(() => {});
  socket?.close();
  await stop(browser);
  await stop(server);
  // Both paths are created by this run, never supplied by the user.
  assert(path.dirname(temporary) === path.resolve(tmpdir()) && path.basename(temporary).startsWith("option-browser-check-"));
  await rm(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  if (outputDir) await writeFile(path.join(outputDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report, null, 2));
}
