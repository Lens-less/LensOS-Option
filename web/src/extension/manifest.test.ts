import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

interface ExtensionManifest {
  manifest_version: number;
  minimum_chrome_version: string;
  permissions: string[];
  host_permissions: string[];
  icons: Record<string, string>;
  background: { service_worker: string; type: string };
  action: { default_title: string; default_icon: Record<string, string> };
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

  it("declares icons for every required size and ships the referenced PNG files", () => {
    const manifest = readManifest();
    const requiredSizes = ["16", "32", "48", "128"];

    expect(Object.keys(manifest.icons).sort()).toEqual(requiredSizes.sort());
    expect(Object.keys(manifest.action.default_icon).sort()).toEqual(
      requiredSizes.sort(),
    );

    for (const size of requiredSizes) {
      const iconPath = manifest.icons[size];
      expect(iconPath).toBe(manifest.action.default_icon[size]);
      const absolutePath = resolve(process.cwd(), "extension", iconPath);
      expect(existsSync(absolutePath)).toBe(true);
      expect(statSync(absolutePath).size).toBeGreaterThan(0);
      const bytes = readFileSync(absolutePath);
      // PNG magic number.
      expect(bytes.subarray(0, 8).toString("hex")).toBe(
        "89504e470d0a1a0a",
      );
    }
  });
});
