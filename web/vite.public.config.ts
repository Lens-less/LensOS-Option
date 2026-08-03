import react from "@vitejs/plugin-react";
import { copyFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

const publicRoot = resolve(__dirname, "public-entry");
const publicOutDir =
  process.env.PUBLIC_BUILD_OUT_DIR ?? resolve(__dirname, "dist-public");
const publicLicenseFiles = ["LICENSE", "LICENSE-DATA"] as const;

export default defineConfig({
  base: "./",
  publicDir: resolve(__dirname, "public"),
  root: publicRoot,
  plugins: [
    react(),
    {
      name: "copy-public-license-files",
      closeBundle() {
        mkdirSync(publicOutDir, { recursive: true });
        for (const filename of publicLicenseFiles) {
          copyFileSync(
            resolve(__dirname, "..", filename),
            resolve(publicOutDir, filename),
          );
        }
      },
    },
  ],
  build: {
    emptyOutDir: true,
    outDir: publicOutDir,
    sourcemap: false,
  },
});
