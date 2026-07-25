import { describe, expect, it } from "vitest";
import {
  DEFAULT_ENGINE_ORIGIN,
  buildEvidenceUrl,
  buildReportUrl,
  normalizeEngineOrigin,
} from "./config";

describe("extension engine config", () => {
  it("falls back to the default loopback origin", () => {
    expect(normalizeEngineOrigin(undefined)).toBe(DEFAULT_ENGINE_ORIGIN);
    expect(normalizeEngineOrigin("")).toBe(DEFAULT_ENGINE_ORIGIN);
  });

  it("accepts localhost and 127.0.0.1 over http with any explicit port", () => {
    expect(normalizeEngineOrigin("http://127.0.0.1:9000/")).toBe(
      "http://127.0.0.1:9000",
    );
    expect(normalizeEngineOrigin("http://localhost:8123")).toBe(
      "http://localhost:8123",
    );
  });

  it("rejects non-loopback or non-http origins", () => {
    expect(() => normalizeEngineOrigin("https://127.0.0.1:8000")).toThrow(
      /loopback/i,
    );
    expect(() => normalizeEngineOrigin("http://192.168.1.4:8000")).toThrow(
      /loopback/i,
    );
    expect(() => normalizeEngineOrigin("https://example.com")).toThrow(
      /loopback/i,
    );
  });

  it("rejects credentials, paths, search params, fragments and missing ports", () => {
    expect(() =>
      normalizeEngineOrigin("http://user:pass@127.0.0.1:8000"),
    ).toThrow(/credentials/i);
    expect(() => normalizeEngineOrigin("http://127.0.0.1:8000/api")).toThrow(
      /path/i,
    );
    expect(() => normalizeEngineOrigin("http://127.0.0.1:8000?x=1")).toThrow(
      /search|hash/i,
    );
    expect(() => normalizeEngineOrigin("http://127.0.0.1:8000/#frag")).toThrow(
      /search|hash/i,
    );
    expect(() => normalizeEngineOrigin("http://127.0.0.1")).toThrow(/port/i);
  });

  it("builds fixed report and evidence URLs from the configured origin", () => {
    const origin = "http://127.0.0.1:8000";
    expect(buildReportUrl(origin)).toBe("http://127.0.0.1:8000/research/report");
    expect(buildEvidenceUrl(origin)).toBe("http://127.0.0.1:8000/evidence/");
  });
});
