import {
  DEFAULT_ENGINE_ORIGIN,
  normalizeEngineOrigin,
} from "./config";
import {
  projectResearchReportForSidePanel,
  validateResearchReport,
} from "../report";
import type {
  DeribitContext,
  EngineConfig,
  ExtensionMessage,
  ExtensionResponse,
} from "./messages";
import { loadResearchReportHttp } from "../transport";
import type { LoadedReport } from "../transport";

const ENGINE_CONFIG_KEY = "engineConfig";
const PANEL_REPORT_KEY = "panelReport";
const DERIBIT_CONTEXT_KEY_PREFIX = "deribitContext";

interface CachedPanelReport {
  origin: string;
  loaded: LoadedReport;
}

interface WorkerDeps {
  loadReport(origin: string): Promise<LoadedReport>;
  readSession<T>(key: string): Promise<T | undefined>;
  writeSession<T>(key: string, value: T): Promise<void>;
  readLocal<T>(key: string): Promise<T | undefined>;
  writeLocal<T>(key: string, value: T): Promise<void>;
  getActiveTabId?(): Promise<number | undefined>;
  setSidePanelOptions(options: {
    tabId: number;
    path: string;
    enabled: boolean;
  }): Promise<void>;
}

async function readOrigin(deps: WorkerDeps): Promise<string> {
  const stored = await deps.readLocal<EngineConfig>(ENGINE_CONFIG_KEY);
  return normalizeEngineOrigin(stored?.origin ?? DEFAULT_ENGINE_ORIGIN);
}

async function writeOrigin(
  deps: WorkerDeps,
  origin: string,
): Promise<string> {
  const normalized = normalizeEngineOrigin(origin);
  await deps.writeLocal<EngineConfig>(ENGINE_CONFIG_KEY, { origin: normalized });
  return normalized;
}

function validateLoadedReportEnvelope(loaded: LoadedReport): LoadedReport {
  const receivedAtMs = loaded.receivedAtMs;
  if (!Number.isFinite(receivedAtMs)) {
    throw new Error("loaded report envelope must include a finite receivedAtMs");
  }

  return {
    ...loaded,
    report: validateResearchReport(loaded.report),
  };
}

function projectLoadedReportEnvelope(loaded: LoadedReport): LoadedReport {
  const validated = validateLoadedReportEnvelope(loaded);
  return {
    ...validated,
    report: projectResearchReportForSidePanel(validated.report),
  };
}

function contextKey(tabId: number): string {
  return `${DERIBIT_CONTEXT_KEY_PREFIX}:${tabId}`;
}

export function createExtensionWorkerController(deps: WorkerDeps): {
  handleMessage(
    message: ExtensionMessage,
    sender?: { tab?: { id?: number } },
  ): Promise<ExtensionResponse>;
} {
  return {
    async handleMessage(
      message: ExtensionMessage,
      sender?: { tab?: { id?: number } },
    ): Promise<ExtensionResponse> {
      try {
        switch (message.type) {
          case "REPORT_GET": {
            const origin = await readOrigin(deps);
            const cached =
              await deps.readSession<CachedPanelReport>(PANEL_REPORT_KEY);
            if (cached?.origin === origin && !message.force) {
              const validatedCached =
                projectLoadedReportEnvelope(cached.loaded);
              return {
                ok: true,
                origin,
                loaded: {
                  ...validatedCached,
                  cached: true,
                },
                fromCache: true,
              };
            }

            const loaded = projectLoadedReportEnvelope(
              await deps.loadReport(origin),
            );
            const cachedReport: LoadedReport = {
              ...loaded,
              cached: loaded.cached ?? false,
            };
            await deps.writeSession<CachedPanelReport>(PANEL_REPORT_KEY, {
              origin,
              loaded: cachedReport,
            });
            return {
              ok: true,
              origin,
              loaded: cachedReport,
              fromCache: false,
            };
          }
          case "REPORT_GET_CACHED_ONLY": {
            // Offline onboarding path: read whatever was last cached for the
            // configured origin without touching the network. A miss is not
            // an error - it just means there is nothing to fall back to yet.
            const origin = await readOrigin(deps);
            const cached =
              await deps.readSession<CachedPanelReport>(PANEL_REPORT_KEY);
            if (!cached || cached.origin !== origin) {
              return { ok: true, origin };
            }
            const validatedCached = projectLoadedReportEnvelope(cached.loaded);
            return {
              ok: true,
              origin,
              loaded: { ...validatedCached, cached: true },
              fromCache: true,
            };
          }
          case "DERIBIT_CONTEXT_UPDATE": {
            const tabId = sender?.tab?.id;
            if (typeof tabId !== "number") {
              return {
                ok: false,
                error: "deribit context update requires a sender tab",
              };
            }
            await deps.writeSession<DeribitContext>(
              contextKey(tabId),
              message.context,
            );
            await deps.setSidePanelOptions({
              tabId,
              path: "sidepanel.html",
              enabled: true,
            });
            return { ok: true, context: message.context };
          }
          case "CONTEXT_GET": {
            const tabId =
              sender?.tab?.id ?? (await deps.getActiveTabId?.());
            if (typeof tabId !== "number") {
              return { ok: true, context: null };
            }
            const context =
              (await deps.readSession<DeribitContext>(contextKey(tabId))) ??
              null;
            return { ok: true, context };
          }
          case "ENGINE_CONFIG_GET": {
            return { ok: true, origin: await readOrigin(deps) };
          }
          case "ENGINE_CONFIG_SET": {
            return { ok: true, origin: await writeOrigin(deps, message.origin) };
          }
          default: {
            return { ok: false, error: "unsupported extension message" };
          }
        }
      } catch (error) {
        const messageText =
          error instanceof Error ? error.message : "extension request failed";
        return { ok: false, error: messageText };
      }
    },
  };
}

async function readStorage<T>(
  area: Chrome["storage"]["session"] | Chrome["storage"]["local"],
  key: string,
): Promise<T | undefined> {
  const record = await area.get(key);
  return record[key] as T | undefined;
}

async function writeStorage<T>(
  area: Chrome["storage"]["session"] | Chrome["storage"]["local"],
  key: string,
  value: T,
): Promise<void> {
  await area.set({ [key]: value });
}

if (typeof chrome !== "undefined") {
  void chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch(() => undefined);

  const runtimeController = createExtensionWorkerController({
    loadReport: (origin) =>
      loadResearchReportHttp({
        url: `${origin}/research/report`,
      }),
    readSession: (key) => readStorage(chrome.storage.session, key),
    writeSession: (key, value) =>
      writeStorage(chrome.storage.session, key, value),
    readLocal: (key) => readStorage(chrome.storage.local, key),
    writeLocal: (key, value) => writeStorage(chrome.storage.local, key, value),
    getActiveTabId: async () => {
      const [activeTab] = await chrome.tabs.query({
        active: true,
        lastFocusedWindow: true,
      });
      return activeTab?.id;
    },
    setSidePanelOptions: (options) => chrome.sidePanel.setOptions(options),
  });

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    void runtimeController.handleMessage(message as ExtensionMessage, sender).then(
      (response) => sendResponse(response),
    );
    return true;
  });

  chrome.runtime.onInstalled.addListener(() => {
    void chrome.sidePanel
      .setPanelBehavior({ openPanelOnActionClick: true })
      .catch(() => undefined);
  });
}
