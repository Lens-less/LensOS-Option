import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/evidence/",
  plugins: [react()],
  build: {
    emptyOutDir: true,
    outDir: "../crypto_options_report/static/evidence",
    sourcemap: false,
  },
  server: {
    proxy: {
      "/research": "http://127.0.0.1:8000",
    },
  },
  test: {
    css: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
