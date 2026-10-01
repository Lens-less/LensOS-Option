// Real DecisionDesk journey in browser-smoke's isolated profile and installed engine.
// Demo requests use the actual stdlib service; no fixture responses are intercepted.
import assert from "node:assert/strict";

const OBSERVATIONS_KEY = "lensos-option.observations.v1";

export async function verifyDecisionDesk({ page, evaluate, until, click, keyboardActivate,
  noOverflow, screenshot, origin, report }) {
  const visible = (selector) => evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    return Boolean(element && element.checkVisibility({checkOpacity:true, checkVisibilityCSS:true}));
  })()`);
  const enabled = (label) => evaluate(`[...document.querySelectorAll('button')].some((element) =>
    element.textContent.trim() === ${JSON.stringify(label)} && element.checkVisibility() && !element.disabled)`);
  const clickSelector = async (selector) => {
    const point = await evaluate(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element || element.disabled || !element.checkVisibility()) throw new Error('Missing enabled Desk control: ' + ${JSON.stringify(selector)});
      element.scrollIntoView({block:'center', behavior:'instant'});
      const box = element.getBoundingClientRect();
      return {x:box.x + box.width/2, y:box.y + box.height/2};
    })()`);
    await page("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, ...point });
    await page("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, ...point });
  };
  const setRange = async (label, value) => {
    await evaluate(`(() => {
      const input = document.querySelector('input[type=range][aria-label=' + ${JSON.stringify(JSON.stringify(label))} + ']');
      if (!input || input.disabled) throw new Error('Missing scenario range: ' + ${JSON.stringify(label)});
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(String(value))});
      input.dispatchEvent(new Event('input', {bubbles:true}));
      input.dispatchEvent(new Event('change', {bubbles:true}));
    })()`);
    assert.equal(await evaluate(`document.querySelector('input[type=range][aria-label=' + ${JSON.stringify(JSON.stringify(label))} + ']').value`), String(value));
  };
  const storage = () => evaluate(`JSON.parse(localStorage.getItem(${JSON.stringify(OBSERVATIONS_KEY)}) || 'null')`);
  const navigate = async (view) => {
    const result = await page("Page.navigate", { url: `${origin}/index.html?${view}` });
    assert(!result.errorText, `DecisionDesk navigation failed: ${result.errorText}`);
  };
  const waitDiscover = async () => {
    await until(() => visible(".decision-desk .desk-opportunities"), "real demo discovers complete option structures");
    await until(() => enabled("重新载入样例"), "demo discovery finishes");
  };
  const selectThree = async () => {
    for (let count = 1; count <= 3; count += 1) {
      await clickSelector('.desk-opportunity .desk-add-action button[aria-pressed="false"]:not([disabled])');
      await until(() => evaluate(`document.querySelectorAll('.desk-opportunity[data-selected=true]').length === ${count}`), `select ${count} same-expiry structures`);
    }
    const expiries = await evaluate(`[...document.querySelectorAll('.desk-opportunity[data-selected=true] .desk-opportunity-heading p')].map((element) => element.textContent.match(/[0-9]{4}-[0-9]{2}-[0-9]{2}/)?.[0])`);
    assert.equal(expiries.length, 3);
    assert(expiries.every((date) => date && date === expiries[0]), "Comparison must use three structures with the same expiry");
  };
  const openCompare = async () => {
    await clickSelector(".desk-compare-tray button:not([disabled])");
    await until(() => visible(".desk-expiry-chart svg"), "real backend returns comparison payoff curves");
    await until(() => enabled("更新情景比较"), "comparison calculation finishes");
    assert.equal(await evaluate("document.querySelectorAll('.desk-expiry-chart path').length"), 3);
    assert.equal(await evaluate("document.querySelectorAll('.desk-stress-grid > div').length"), 3);
  };

  await page("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await navigate("view=desk&mode=demo");
  await waitDiscover();
  assert(await evaluate("document.querySelector('.decision-desk')?.dataset.mode === 'demo'"), "DecisionDesk must begin in explicit offline demo mode");
  assert(await evaluate("document.body.innerText.includes('不代表当前行情') && document.body.innerText.includes('USDC 线性期权')"), "Demo and contract-family limits must remain visible");
  assert(!await evaluate("Boolean(document.querySelector('#surface-main, .strategy-brief-header, [data-freshness]'))"), "Legacy evidence dashboard must not remain the main DecisionDesk surface");
  assert(await evaluate("document.querySelectorAll('.desk-opportunity').length >= 3"), "Demo must supply complete discoverable structures");
  await noOverflow("DecisionDesk desktop discovery has no page overflow");
  await screenshot("desk-desktop-discover");
  await selectThree();
  await openCompare();

  const before = await evaluate(`({
    payoff: [...document.querySelectorAll('.desk-expiry-chart path')].map((element) => element.getAttribute('d')),
    stress: [...document.querySelectorAll('.desk-stress-grid strong')].map((element) => element.textContent)
  })`);
  await setRange("标的价格变化百分比", -8);
  await setRange("经过时间天数", 2);
  await setRange("IV平移百分点", 5);
  await until(async () => await visible(".desk-chart-placeholder") && !await visible(".desk-expiry-chart svg"), "changed scenario withdraws the previous comparison");
  await clickSelector(".desk-decision-options input[type=radio]");
  assert(!await enabled("保存到本地观察"), "Changing assumptions must block saving the old comparison");
  assert(!await enabled("复制研究复核"), "Changing assumptions must block copying the old comparison");
  await click("计算共同情景");
  await until(async () => await enabled("保存到本地观察") && await visible(".desk-expiry-chart svg"), "real updated scenario becomes available");
  const after = await evaluate(`({
    payoff: [...document.querySelectorAll('.desk-expiry-chart path')].map((element) => element.getAttribute('d')),
    stress: [...document.querySelectorAll('.desk-stress-grid strong')].map((element) => element.textContent)
  })`);
  assert.deepEqual(after.payoff, before.payoff, "Elapsed time and IV changes must not alter the fixed conditional expiry payoff");
  assert.notDeepEqual(after.stress, before.stress, "Price/time/IV changes must recalculate the pre-expiry stress model");

  await clickSelector(".desk-note-label textarea");
  await page("Input.insertText", { text: "优先保留完整保护腿；固定价格 -8%、推进 2 天、IV +5 点后再复核。" });
  await keyboardActivate("复制研究复核");
  await until(async () => await enabled("已复制研究复核") || await visible(".desk-copy-fallback textarea"), "research review copy or visible manual fallback");
  const copy = await evaluate(`(async () => {
    const fallback = document.querySelector('.desk-copy-fallback textarea');
    if (fallback) return {channel:'visible manual fallback', text:fallback.value};
    try { return {channel:'native clipboard', text:await navigator.clipboard.readText()}; }
    catch { return {channel:'native clipboard write acknowledged; read unavailable', text:null}; }
  })()`);
  if (copy.text !== null) {
    for (const token of ["execution_allowed=false", "SYNTHETIC OFFLINE EXAMPLE", "SNAPSHOT ID:", "ANALYSIS ID:", "BID", "ASK", "CONTRACT SIZE", "RECHECK AT:"]) {
      assert(copy.text.includes(token), `Copied research must include ${token}`);
    }
  }
  await noOverflow("DecisionDesk desktop comparison has no page overflow");
  await screenshot("desk-desktop-compare");
  await screenshot("desk-desktop-compare-full", { fullPage: true });
  await keyboardActivate("保存到本地观察");
  await until(() => visible(".desk-observe-detail"), "comparison saves an actual browser-private observation");
  let saved = await storage();
  assert.equal(saved?.version, 1);
  assert.equal(saved.records.length, 1, "Isolated profile must save exactly one observation");
  const original = saved.records[0];
  assert.equal(original.desk.source.mode, "demo");
  assert.equal(original.desk.qualification.execution_allowed, false);
  assert.equal(original.comparison.members.length, 3);
  assert.deepEqual(original.comparison.scenario, { price_change_pct: -8, time_days: 2, iv_shift_points: 5 });
  assert(original.note.includes("完整保护腿"), "Decision note must survive an actual textarea edit");
  const originalCandidate = original.desk.candidates.find((candidate) => candidate.candidate_id === original.candidate_id);
  assert(originalCandidate && [2, 4].includes(originalCandidate.legs.length), "Saved observation must retain its complete exact legs");

  await page("Page.reload", { ignoreCache: true });
  await waitDiscover();
  await clickSelector(".desk-masthead nav button:nth-child(3)");
  await until(() => visible(".desk-observe-detail"), "reload restores the saved browser observation");
  assert.deepEqual((await storage()).records[0], original, "Reload must retain the immutable original research and note");
  await click("复核同一组合");
  await until(() => visible(".desk-quote-table"), "real engine reviews exactly the saved contracts");
  saved = await storage();
  assert.deepEqual(saved.records[0], original, "Review must append evidence without rewriting original inputs");
  const review = saved.reviews.find((event) => event.kind === "review")?.review;
  assert(review, "A successful real review must persist a separate event");
  assert.equal(review.original_snapshot_id, original.desk.snapshot_id);
  assert.equal(review.original_candidate_id, original.candidate_id);
  assert.notEqual(review.reviewed_candidate_id, original.candidate_id, "Fresh snapshot identity must produce a new truthful candidate identity");
  const currentCandidate = review.desk?.candidates.find((candidate) => candidate.candidate_id === review.reviewed_candidate_id);
  assert(currentCandidate, "Review must link to the candidate in the fresh snapshot");
  const identity = (leg) => [leg.instrument_name, leg.side, leg.ratio, leg.contract_size, leg.strike, leg.option_type];
  assert.deepEqual(currentCandidate.legs.map(identity), originalCandidate.legs.map(identity), "Review cannot substitute expiry, protection, or contracts");
  assert.equal(currentCandidate.expiration_timestamp, originalCandidate.expiration_timestamp);
  assert.equal(review.desk.source.mode, "demo", "Review of synthetic research must stay honestly labeled as synthetic");
  await noOverflow("DecisionDesk desktop observation has no page overflow");
  await screenshot("desk-desktop-observe");

  await page("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await clickSelector(".desk-masthead nav button:nth-child(1)");
  await until(() => visible(".desk-opportunities"), "mobile discovery workspace");
  await click("重新载入样例");
  await waitDiscover();
  await selectThree();
  await noOverflow("DecisionDesk 390px discovery has no page overflow");
  await screenshot("desk-mobile-discover");
  await openCompare();
  await noOverflow("DecisionDesk 390px comparison has no page overflow");
  await screenshot("desk-mobile-compare");
  await screenshot("desk-mobile-compare-full", { fullPage: true });
  await clickSelector(".desk-masthead nav button:nth-child(3)");
  await until(() => visible(".desk-observe-detail"), "mobile observation workspace");
  await noOverflow("DecisionDesk 390px observation has no page overflow");
  await screenshot("desk-mobile-observe");
  assert(await evaluate(`[...document.querySelectorAll('.decision-desk button')].every((button) =>
    !/^(买入|卖出|提交订单|确认下单|执行交易|开始交易)$/.test(button.textContent.trim()))`), "Research journey cannot introduce trading controls");
  report.decisionDesk = {
    realBackend: true, source: "SYNTHETIC_DEMO", asset: original.desk.asset, structuresCompared: 3,
    copiedVia: copy.channel, scenario: original.comparison.scenario,
    originalCandidateId: original.candidate_id, reviewedCandidateId: review.reviewed_candidate_id,
    browserStorageOnly: true, originalPreservedAfterReloadAndReview: true,
  };
  report.checks.push(
    "real DecisionDesk discovers three complete same-expiry structures and compares shared payoff/stress assumptions",
    "real scenario controls invalidate stale save/copy until recalculation; keyboard copies research with boundary metadata",
    "browser-private observation restores after reload and reviews exact saved legs with truthful new identity",
    "desktop and 390px DecisionDesk discovery, comparison, and observation remain research-only with explicit synthetic source",
  );

  // The caller continues its legacy freshness acceptance on the same page.
  await navigate("view=legacy");
  await until(() => visible('[data-freshness="current"]'), "restore legacy research page before controlled expiry");
}
