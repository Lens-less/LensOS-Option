import { detectDeribitContext } from "./context";

declare const chrome: Chrome;

// Selectors Deribit marks as instrument-identifying: a match here is treated
// as higher confidence than the generic heading/body scan below.
const STRUCTURAL_SELECTORS = [
  "[data-instrument-name]",
  "[data-testid*='instrument']",
  "[data-test*='instrument']",
];

// Generic headings only; a bounded, best-effort fallback when Deribit hasn't
// marked the instrument with a dedicated attribute.
const HEURISTIC_SELECTORS = ["h1", "[role='heading']"];

function collectFragments(selectors: string[]): string {
  const fragments: string[] = [];

  for (const selector of selectors) {
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

function collectDeribitHints(): { structuralText: string; heuristicText: string } {
  return {
    structuralText: collectFragments(STRUCTURAL_SELECTORS),
    heuristicText: collectFragments(HEURISTIC_SELECTORS),
  };
}

let lastPublishedSignature: string | null = null;
let pendingSignature: string | null = null;

function publishContext(): void {
  const hints = collectDeribitHints();
  const context = detectDeribitContext({
    href: window.location.href,
    documentTitle: document.title,
    structuralText: hints.structuralText,
    bodyText: hints.heuristicText,
  });

  const signature = JSON.stringify({
    href: context.href,
    route: context.route,
    source: context.source,
    confidence: context.confidence,
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

// characterData is deliberately omitted: it fires on every live price tick
// (Deribit repaints quote text continuously), which would debounce-thrash
// the context refresh for no detection benefit.
observer.observe(document.documentElement, {
  subtree: true,
  childList: true,
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
