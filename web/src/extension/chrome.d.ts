export {};

declare global {
  interface ChromeMessageSender {
    tab?: {
      id?: number;
    };
  }

  interface ChromeRuntimeOnMessage {
    addListener(
      callback: (
        message: unknown,
        sender: ChromeMessageSender,
        sendResponse: (response: unknown) => void,
      ) => boolean | void,
    ): void;
  }

  interface ChromeRuntimeOnInstalled {
    addListener(callback: () => void): void;
  }

  interface ChromeStorageArea {
    get(key: string): Promise<Record<string, unknown>>;
    set(items: Record<string, unknown>): Promise<void>;
  }

  interface ChromeSidePanel {
    setOptions(options: {
      tabId: number;
      path: string;
      enabled: boolean;
    }): Promise<void>;
    setPanelBehavior(options: {
      openPanelOnActionClick: boolean;
    }): Promise<void>;
  }

  interface ChromeRuntime {
    onMessage: ChromeRuntimeOnMessage;
    onInstalled: ChromeRuntimeOnInstalled;
    sendMessage(message: unknown): Promise<unknown>;
    getURL(path: string): string;
  }

  interface ChromeStorage {
    session: ChromeStorageArea;
    local: ChromeStorageArea;
  }

  interface ChromeTabs {
    query(options: {
      active: boolean;
      lastFocusedWindow: boolean;
    }): Promise<Array<{ id?: number }>>;
  }

  interface Chrome {
    runtime: ChromeRuntime;
    storage: ChromeStorage;
    sidePanel: ChromeSidePanel;
    tabs: ChromeTabs;
  }

  const chrome: Chrome;
}
