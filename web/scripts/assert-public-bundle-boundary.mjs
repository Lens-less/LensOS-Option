import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { join, extname, dirname, resolve } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(here, "..");
const viteBin = resolve(webDir, "node_modules", "vite", "bin", "vite.js");
const outDir = mkdtempSync(join(tmpdir(), "lensos-public-bundle-"));
const forbiddenPolicyPath = resolve(
  webDir,
  "..",
  "crypto_options_report",
  "resources",
  "public_bundle_forbidden_tokens.json",
);
const forbiddenPolicy = JSON.parse(readFileSync(forbiddenPolicyPath, "utf8"));
if (
  forbiddenPolicy.schema_version !== "public_bundle_forbidden_tokens.v1" ||
  !Array.isArray(forbiddenPolicy.tokens) ||
  forbiddenPolicy.tokens.length === 0
) {
  throw new Error("public bundle forbidden-token policy is invalid");
}
const forbiddenTokens = forbiddenPolicy.tokens;

const requiredTokens = [
  "五幕叙事",
  "RESEARCH_ONLY",
  "NO_TRADE",
  "view=series",
  "#signal",
];

function collectTextFiles(dir) {
  const paths = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      paths.push(...collectTextFiles(fullPath));
      continue;
    }
    const extension = extname(entry.name);
    if ([".css", ".html", ".js"].includes(extension)) {
      paths.push(fullPath);
    }
  }
  return paths;
}

function containsPolicyToken(text, token) {
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?<![a-z0-9_])${escaped}(?![a-z0-9_])`).test(text);
}

try {
  const result = spawnSync(
    process.execPath,
    [viteBin, "build", "--config", "vite.public.config.ts"],
    {
      cwd: webDir,
      encoding: "utf8",
      env: {
        ...process.env,
        PUBLIC_BUILD_OUT_DIR: outDir,
      },
      stdio: "pipe",
    },
  );

  if (result.status !== 0) {
    process.stderr.write(result.stdout);
    process.stderr.write(result.stderr);
    throw new Error("public bundle build failed");
  }

  const files = collectTextFiles(outDir);
  const combined = files.map((file) => readFileSync(file, "utf8")).join("\n");
  const normalizedCombined = combined.toLowerCase();

  const leaked = forbiddenTokens.filter((token) =>
    containsPolicyToken(normalizedCombined, token),
  );
  if (leaked.length > 0) {
    throw new Error(`public bundle leaked forbidden tokens: ${leaked.join(", ")}`);
  }

  const missing = requiredTokens.filter((token) => !combined.includes(token));
  if (missing.length > 0) {
    throw new Error(`public bundle is missing required public markers: ${missing.join(", ")}`);
  }

  process.stdout.write(
    `Public bundle boundary passed. Scanned ${files.length} files in ${outDir}.\n`,
  );
} finally {
  rmSync(outDir, { force: true, recursive: true });
}
