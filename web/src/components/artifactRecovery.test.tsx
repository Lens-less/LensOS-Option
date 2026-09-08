import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSignalArtifact } from "./signal/SignalValidationView";
import { useSeriesArtifact } from "./series/SeriesHistoryView";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe.each([
  ["signal", useSignalArtifact],
  ["series", useSeriesArtifact],
] as const)("%s artifact recovery", (_name, useArtifact) => {
  it("refetches after an explicit retry without continuing to display the failed artifact", async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "ready" })));
    vi.stubGlobal("fetch", fetchMock);
    const { result, rerender } = renderHook(({ retry }) => useArtifact("/artifact", undefined, retry), {
      initialProps: { retry: 0 },
    });
    await waitFor(() => expect(result.current?.status).toBe("not_configured"));
    rerender({ retry: 1 });
    expect(result.current).toBeNull();
    await waitFor(() => expect(result.current?.status).toBe("ready"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("bounds response reading and offers a safe recovery action", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => new Promise(() => undefined) });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useArtifact("/artifact"));
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(result.current?.detail).toContain("超时");
    expect(result.current?.detail).toContain("刷新");
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it("aborts pending work when the view unmounts", () => {
    const fetchMock = vi.fn().mockReturnValue(new Promise(() => undefined));
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = renderHook(() => useArtifact("/artifact"));
    unmount();
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
  });
});
