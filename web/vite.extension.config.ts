import { existsSync, mkdirSync, readFileSync, renameSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { type Plugin } from "vite";
import { defineConfig } from "vitest/config";

function emitManifest(): Plugin {
  return {
    name: "emit-extension-manifest",
    generateBundle() {
      const manifest = readFileSync(
        resolve(__dirname, "extension/manifest.json"),
        "utf8",
      );
      this.emitFile({
        type: "asset",
        fileName: "manifest.json",
        source: manifest,
      });
    },
    writeBundle() {
      const distDir = resolve(__dirname, "dist/chrome-extension");
      const nestedDir = resolve(distDir, "extension");
      const nestedSidepanel = resolve(nestedDir, "sidepanel.html");
      const rootSidepanel = resolve(distDir, "sidepanel.html");

      if (!existsSync(nestedSidepanel)) {
        return;
      }

      if (existsSync(rootSidepanel)) {
        rmSync(rootSidepanel);
      }
      mkdirSync(distDir, { recursive: true });
      renameSync(nestedSidepanel, rootSidepanel);
      if (existsSync(nestedDir)) {
        rmSync(nestedDir, { recursive: true, force: true });
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), emitManifest()],
  publicDir: false,
  build: {
    emptyOutDir: true,
    outDir: "dist/chrome-extension",
    sourcemap: false,
    rollupOptions: {
      input: {
        sidepanel: resolve(__dirname, "extension/sidepanel.html"),
        "service-worker": resolve(__dirname, "src/extension/service-worker.ts"),
        "content-script": resolve(__dirname, "src/extension/content-script.ts"),
      },
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
  test: {
    css: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
