import { afterEach, describe, expect, it, vi } from "vitest";

import { loadPublicReport } from "./loadPublicReport";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("loadPublicReport", () => {
  it("loads the public summary change alongside the research report", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ schema_version: "research_report.v1" }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            change: {
              status: "available",
              vrp_percent_points_delta: 1.2,
            },
            schema_version: "public_summary.v1",
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const loaded = await loadPublicReport();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "./research/report",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "./api/v1/summary.json",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(loaded.summary?.change?.vrp_percent_points_delta).toBe(1.2);
  });

  it("keeps the report available when the comparison summary is missing", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ schema_version: "research_report.v1" }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(new Response("not found", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const loaded = await loadPublicReport();

    expect(loaded.report.schema_version).toBe("research_report.v1");
    expect(loaded.summary).toBeNull();
  });
});
