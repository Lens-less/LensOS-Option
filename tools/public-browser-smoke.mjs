// Accept the actual public build with a static publication produced by the installed wheel.
// The fixed fixture and historical browser clock are recorded explicitly in the report.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { promisify } from "node:util";

export function historicalAcceptanceClock(published) {
  const startsAt = Math.max(Date.parse(published.publish_edition.published_at), Date.parse(published.strategy_brief.market.as_of));
  const endsAt = Math.min(Date.parse(published.publish_edition.stale_after), Date.parse(published.strategy_brief.market.expires_at));
  assert(Number.isFinite(startsAt) && Number.isFinite(endsAt) && endsAt > startsAt,
    "Public fixture needs a historical interval after publication and before brief expiry");
  return startsAt + Math.floor((endsAt - startsAt) / 2);
}

export async function verifyPublic({ send, until, python, publicBuildDir, temporary,
  outputDir, report, setPublicOrigin, setPublicFailure }) {
  const site = path.join(temporary, "public-site");
  const prepared = await promisify(execFile)(python, [
    "-I", path.join(import.meta.dirname, "prepare_public_browser_case.py"),
    "--public-build-dir", publicBuildDir, "--output-dir", site,
  ], { cwd: temporary, windowsHide: true, encoding: "utf8", timeout: 120000 });
  const preparation = JSON.parse(prepared.stdout);
  const published = JSON.parse(await readFile(path.join(site, "research", "report"), "utf8"));
  const historicalClock = historicalAcceptanceClock(published);
  report.public = { preparation, historicalClock: new Date(historicalClock).toISOString(), liveMarketEvidence: false };

  const server = createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
      const file = path.resolve(site, `.${pathname === "/" ? "/index.html" : pathname}`);
      if (!file.startsWith(`${site}${path.sep}`)) {
        response.writeHead(403).end();
        return;
      }
      const content = await readFile(file);
      const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2" }[path.extname(file)]
        ?? (pathname.startsWith("/research/") || pathname.endsWith(".json") ? "application/json" : "text/plain");
      response.writeHead(200, { "Content-Type": mime, "Cache-Control": "no-store" }).end(content);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const origin = `http://127.0.0.1:${server.address().port}`;
  setPublicOrigin(origin);
  let targetId;
  let evaluate;
  let page;
  try {
    ({ targetId } = await send("Target.createTarget", { url: "about:blank" }));
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    page = (method, params = {}) => send(method, params, sessionId);
    evaluate = async (expression) => {
      const result = await page("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
      assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
      return result.result.value;
    };
    const has = (selector) => evaluate(`[...document.querySelectorAll(${JSON.stringify(selector)})].some((element) => element.checkVisibility({checkOpacity:true, checkVisibilityCSS:true}))`);
    const errorContains = (text) => evaluate(`document.querySelector('.error-card[role=alert]')?.innerText.includes(${JSON.stringify(text)})`);
    const resize = (width) => page("Emulation.setDeviceMetricsOverride", { width, height: width === 390 ? 844 : 1000, deviceScaleFactor: 1, mobile: width === 390 });
    const noOverflow = async (label) => {
      const size = await evaluate("({viewport:innerWidth, document:document.documentElement.scrollWidth})");
      assert(size.document <= size.viewport + 1, `${label}: horizontal overflow ${JSON.stringify(size)}`);
      report.checks.push(label);
    };
    const screenshot = async (name) => {
      if (!outputDir) return;
      await evaluate("window.scrollTo({top:0, left:0, behavior:'instant'})");
      const { data } = await page("Page.captureScreenshot", { format: "png" });
      await writeFile(path.join(outputDir, `${name}.png`), Buffer.from(data, "base64"));
    };
    const key = async (name, code) => {
      const params = { key: name, code: name, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code };
      await page("Input.dispatchKeyEvent", { type: "keyDown", ...params, ...(name === "Enter" ? { text: "\r", unmodifiedText: "\r" } : {}) });
      await page("Input.dispatchKeyEvent", { type: "keyUp", ...params });
    };
    const activate = async (label) => {
      for (let index = 0; index < 60; index += 1) {
        if (await evaluate(`document.activeElement?.textContent.trim() === ${JSON.stringify(label)} && !document.activeElement.disabled`)) {
          await key("Enter", 13);
          return;
        }
        await key("Tab", 9);
      }
      throw new Error(`Keyboard cannot reach public control: ${label}`);
    };
    const retry = () => activate("重新读取静态快照");
    const restored = async () => await has(".published-edition-bar") && await has(".strategy-brief-view") && !await has(".error-card[role=alert]");
    const openEvidence = async () => {
      await activate("查看依据");
      await until(() => has(".strategy-brief-details[open] #vrp"), "public keyboard opens restored evidence details");
    };
    const navigate = async (suffix = "") => {
      const result = await page("Page.navigate", { url: `${origin}/index.html${suffix}` });
      assert(!result.errorText, `Public navigation failed: ${result.errorText}`);
    };
    await page("Runtime.enable");
    await page("Page.enable");
    await page("Network.enable");
    await page("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
    await resize(1440);
    await navigate();
    await until(() => has(".published-stop-card"), "real current clock withholds expired public fixture");
    assert(!await has(".vrp-hero, .market-metrics, #surface"), "Expired public edition must withhold research values");
    report.checks.push("actual public build withholds historical fixture at the real current clock");
    await noOverflow("public expired edition desktop");
    await screenshot("public-expired");

    // Only this public fixture tab uses its recorded historical clock. The
    // installed-wheel journey and extension keep their existing clock checks.
    await page("Page.addScriptToEvaluateOnNewDocument", { source: `Date.now = () => ${historicalClock};` });
    setPublicFailure("network");
    await resize(390);
    await navigate();
    await until(() => errorContains("无法连接研究服务"), "public report network failure");
    assert.equal(await evaluate("Date.now()"), historicalClock, "Public fixture must use its recorded historical clock");
    assert(!await has(".published-edition-bar, #vrp, .market-metrics"), "Failed public fetch must withhold previous research values");
    await noOverflow("public network failure mobile");
    await retry();
    await until(restored, "public keyboard retry restores the actual static publication");
    report.checks.push("public network failure recovers through keyboard retry and actual static report");
    assert(await evaluate("document.body.innerText.includes('RESEARCH_ONLY · NO_TRADE')"), "Public fixture must retain its research-only boundary");
    assert(!await evaluate("document.querySelector('.strategy-brief-view').innerText.includes('有效期已过')"), "Historical acceptance clock must precede the real brief expiry");
    await openEvidence();
    report.checks.push("public restored brief exposes evidence through keyboard-controlled details");
    await noOverflow("public historical evidence mobile");
    await screenshot("public-mobile");
    await resize(1440);
    await noOverflow("public historical evidence desktop");
    await screenshot("public-desktop");
    await resize(390);
    setPublicFailure("invalid");
    await retry();
    await until(() => errorContains("报告校验失败"), "public malformed report failure");
    assert(!await has(".published-edition-bar, #vrp, .market-metrics"), "Malformed refresh must withdraw prior public evidence");
    await noOverflow("public invalid report mobile");
    await retry();
    await until(restored, "public retry restores report after malformed response");
    await openEvidence();
    report.checks.push("public malformed refresh withdraws prior evidence and keyboard retry restores the static report");
    for (const [view, region] of [["signal", "信号验证进度"], ["series", "序列验证进度"]]) {
      await navigate(`?view=${view}`);
      await until(() => has(`section[aria-label="${region}"]`), `public ${view} route`);
      await noOverflow(`public historical ${view} mobile`);
      await screenshot(`public-${view}-mobile`);
    }
  } catch (error) {
    report.public.diagnostic = evaluate ? await evaluate("({url:location.href, nowMs:Date.now(), evidenceDetailsOpen:document.querySelector('.strategy-brief-details')?.open, body:document.body.innerText.slice(0,4000)})").catch(() => null) : null;
    if (outputDir && page) {
      const failure = await page("Page.captureScreenshot", { format: "png" }).catch(() => null);
      if (failure) await writeFile(path.join(outputDir, "public-failure.png"), Buffer.from(failure.data, "base64"));
    }
    throw error;
  } finally {
    if (targetId) await send("Target.closeTarget", { targetId }).catch(() => {});
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}
