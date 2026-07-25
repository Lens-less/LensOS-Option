import { detectDeribitContext } from "./context";

declare const chrome: Chrome;

const DOM_TEXT_SELECTORS = [
  "[data-instrument-name]",
  "[data-testid*='instrument']",
  "[data-test*='instrument']",
  "h1",
  "[role='heading']",
];

function collectDeribitHints(): string {
  const fragments: string[] = [];

  for (const selector of DOM_TEXT_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (const node of nodes) {
      const value = node.textContent?.trim();
      if (value) {
        fragments.push(value);
      }
      if (fragments.length >= 6) {
        return fragments.join(" | ");
      }
    }
  }

  return fragments.join(" | ");
}

let lastPublishedSignature: string | null = null;
let pendingSignature: string | null = null;

function publishContext(): void {
  const context = detectDeribitContext({
    href: window.location.href,
    documentTitle: document.title,
    bodyText: collectDeribitHints(),
  });

  const signature = JSON.stringify({
    href: context.href,
    route: context.route,
    source: context.source,
    instrument: context.instrument,
    underlying: context.underlying,
  });
  if (
    signature === lastPublishedSignature ||
    signature === pendingSignature
  ) {
    return;
  }

  pendingSignature = signature;
  void chrome.runtime
    .sendMessage({
      type: "DERIBIT_CONTEXT_UPDATE",
      context,
    })
    .then(() => {
      lastPublishedSignature = signature;
    })
    .catch(() => undefined)
    .finally(() => {
      if (pendingSignature === signature) {
        pendingSignature = null;
      }
    });
}

let debounceHandle: number | null = null;

function scheduleContextRefresh(): void {
  if (debounceHandle !== null) {
    window.clearTimeout(debounceHandle);
  }
  debounceHandle = window.setTimeout(() => {
    debounceHandle = null;
    publishContext();
  }, 250);
}

window.addEventListener("hashchange", scheduleContextRefresh);
window.addEventListener("popstate", scheduleContextRefresh);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    scheduleContextRefresh();
  }
});

const observer = new MutationObserver(() => {
  scheduleContextRefresh();
});

observer.observe(document.documentElement, {
  subtree: true,
  childList: true,
  characterData: true,
});

let lastObservedHref = window.location.href;
window.setInterval(() => {
  if (window.location.href === lastObservedHref) {
    return;
  }
  lastObservedHref = window.location.href;
  scheduleContextRefresh();
}, 1_000);

scheduleContextRefresh();
