import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

interface ExtensionManifest {
  manifest_version: number;
  minimum_chrome_version: string;
  permissions: string[];
  host_permissions: string[];
  background: { service_worker: string; type: string };
  action: { default_title: string };
  side_panel: { default_path: string };
  content_scripts: Array<{
    matches: string[];
    js: string[];
    run_at: string;
  }>;
}

function readManifest(): ExtensionManifest {
  return JSON.parse(
    readFileSync(resolve(process.cwd(), "extension/manifest.json"), "utf8"),
  ) as ExtensionManifest;
}

describe("Chrome extension manifest", () => {
  it("declares only the permissions and fixed entrypoints needed by the local companion", () => {
    const manifest = readManifest();

    expect(manifest.manifest_version).toBe(3);
    expect(Number(manifest.minimum_chrome_version)).toBeGreaterThanOrEqual(114);
    expect(manifest.permissions).toEqual(["sidePanel", "storage"]);
    expect(manifest.host_permissions).toEqual([
      "http://127.0.0.1/*",
      "http://localhost/*",
    ]);
    expect(manifest.background).toEqual({
      service_worker: "assets/service-worker.js",
      type: "module",
    });
    expect(manifest.side_panel.default_path).toBe("sidepanel.html");
    expect(manifest.action.default_title).toMatch(/LensOS/i);
    expect(manifest.content_scripts).toEqual([
      {
        matches: [
          "https://www.deribit.com/*",
          "https://deribit.com/*",
        ],
        js: ["assets/content-script.js"],
        run_at: "document_idle",
      },
    ]);
  });
});
