import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RAW_REPORT_HREF } from "../publicPaths";
import { safeResearchReport } from "../report/testFixtures";
import publicStyles from "../styles.css?raw";
import { PublicApp } from "./PublicApp";
import { loadPublicReport } from "./loadPublicReport";

vi.mock("./loadPublicReport", () => ({
  loadPublicReport: vi.fn(),
}));

const LOADED_AT_MS = Date.parse("2026-07-24T10:25:04Z");

function loadedPublicReport() {
  return {
    receivedAtMs: LOADED_AT_MS,
    report: safeResearchReport,
    summary: null,
  };
}

describe("PublicApp static paths and lifecycle refresh", () => {
  beforeEach(() => {
    window.history.pushState(window.history.state, "", "/index.html");
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(LOADED_AT_MS));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false }),
    );
    vi.mocked(loadPublicReport).mockResolvedValue(loadedPublicReport());
  });

  afterEach(() => {
    window.history.pushState(window.history.state, "", "/");
    vi.mocked(loadPublicReport).mockReset();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("keeps the research-only boundary explicit while public evidence is loading", () => {
    vi.mocked(loadPublicReport).mockReturnValue(new Promise(() => undefined));

    render(<PublicApp />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "RESEARCH_ONLY · NO_TRADE",
    );
  });

  it("resolves the raw JSON beside both the root page and an immutable edition", async () => {
    expect(
      new URL(RAW_REPORT_HREF, "https://option.example/index.html").pathname,
    ).toBe("/research/report");
    expect(
      new URL(
        RAW_REPORT_HREF,
        "https://option.example/editions/2026-08-11/index.html",
      ).pathname,
    ).toBe("/editions/2026-08-11/research/report");

    render(<PublicApp />);

    expect(
      await screen.findByRole("link", { name: "原始 JSON" }),
    ).toHaveAttribute("href", "./research/report");
  });

  it("keeps the raw evidence link visible in the compact spine layout", () => {
    expect(publicStyles).not.toMatch(
      /\n\s*\.text-link\s*\{\s*display:\s*none;/,
    );
    expect(publicStyles).toMatch(
      /@media \(max-width: 899px\)[\s\S]*?\.spine-actions\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) auto auto;/,
    );
  });

  it("refreshes only when a hidden page becomes visible after wall-clock expiry", async () => {
    let visibility: DocumentVisibilityState = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(
      () => visibility,
    );

    render(<PublicApp />);
    await screen.findByRole("link", { name: "原始 JSON" });
    expect(loadPublicReport).toHaveBeenCalledTimes(1);

    fireEvent(document, new Event("visibilitychange"));
    expect(loadPublicReport).toHaveBeenCalledTimes(1);

    vi.setSystemTime(new Date(LOADED_AT_MS + 61_000));
    visibility = "hidden";
    fireEvent(document, new Event("visibilitychange"));
    expect(loadPublicReport).toHaveBeenCalledTimes(1);

    visibility = "visible";
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => {
      expect(loadPublicReport).toHaveBeenCalledTimes(2);
    });
  });

  it("fails closed when a visibility-triggered refresh cannot be verified", async () => {
    let visibility: DocumentVisibilityState = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(
      () => visibility,
    );
    vi.mocked(loadPublicReport)
      .mockResolvedValueOnce(loadedPublicReport())
      .mockRejectedValueOnce(new Error("unverifiable replacement"));

    render(<PublicApp />);
    await screen.findByRole("link", { name: "原始 JSON" });

    vi.setSystemTime(new Date(LOADED_AT_MS + 61_000));
    visibility = "visible";
    fireEvent(document, new Event("visibilitychange"));

    expect(
      await screen.findByRole("heading", { name: "公开研究数据不可用" }),
    ).toBeInTheDocument();
  });

  it("refetches signal and series artifacts under each verified publication identity", async () => {
    const firstCapturedAt = "2026-07-24T10:25:00Z";
    const secondCapturedAt = "2026-07-25T10:25:00Z";
    const withEdition = (capturedAt: string, publishedAt: string) => ({
      ...safeResearchReport,
      runtime_context: {
        mode: "published" as const,
        replay: false,
        evaluation_clock: capturedAt,
      },
      publish_edition: {
        cadence: "daily" as const,
        captured_at: capturedAt,
        next_expected_at: "2026-07-26T10:25:00Z",
        published_at: publishedAt,
        stale_after: "2026-07-27T10:25:00Z",
      },
    });
    vi.mocked(loadPublicReport)
      .mockResolvedValueOnce({
        receivedAtMs: LOADED_AT_MS,
        report: withEdition(firstCapturedAt, "2026-07-24T10:26:00Z"),
        summary: null,
      })
      .mockResolvedValueOnce({
        receivedAtMs: LOADED_AT_MS + 1_000,
        report: withEdition(secondCapturedAt, "2026-07-25T10:26:00Z"),
        summary: null,
      });
    const fetchMock = vi.fn().mockImplementation((url: string) =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            generated_at: url.includes("2026-07-25")
              ? secondCapturedAt
              : firstCapturedAt,
            status: "projected",
          }),
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<PublicApp />);
    await screen.findByRole("link", { name: "原始 JSON" });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    fireEvent.click(
      screen.getByRole("button", { name: "重新读取静态快照" }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(4);
    });
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls.filter((url) => url.startsWith("./research/signal"))).toHaveLength(2);
    expect(urls.filter((url) => url.startsWith("./research/series"))).toHaveLength(2);
    expect(urls.some((url) => url.includes(encodeURIComponent(secondCapturedAt)))).toBe(true);
  });
});
