import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { safeResearchReport } from "../../report/testFixtures";
import { AppShell } from "./AppShell";

afterEach(() => vi.unstubAllGlobals());

describe("compact research navigation", () => {
  it("keeps the demo boundary visible while the user opens navigation and closes it with Escape", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const report = structuredClone(safeResearchReport);
    report.runtime_context = { ...report.runtime_context!, mode: "replay", replay: true, demo_mode: true, evaluation_clock: "2026-07-07T00:00:00Z" };
    render(<AppShell report={report} view="series" refreshing={false}
      freshness={{ phase: "expired", mode: "replay", ageSec: 61, maxAgeSec: 60 }}>
      <main id="surface-main"><h1>当前研究结论</h1></main>
    </AppShell>);

    expect(screen.getByText("演示快照")).toBeVisible();
    expect(screen.getByText("仅研究 · NO_TRADE")).toBeVisible();
    expect(screen.getByRole("heading", { name: "当前研究结论" })).toBeVisible();
    const toggle = screen.getByRole("button", { name: "波动时序 · 导航" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("navigation", { name: "全视图导航" })).not.toBeInTheDocument();
    fireEvent.click(toggle);
    const nav = screen.getByRole("navigation", { name: "全视图导航" });
    expect(within(nav).getByRole("link", { name: "② 波动时序" })).toHaveAttribute("aria-current", "page");
    const signal = within(nav).getByRole("link", { name: "④ 排序验证" });
    signal.focus();
    fireEvent.keyDown(signal, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
    expect(screen.getByText("仅研究 · NO_TRADE")).toBeVisible();
  });

  it("keeps desktop links and report context expanded", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    render(<AppShell report={safeResearchReport} view="signal" refreshing={false}>
      <main id="surface-main"><h1>当前研究结论</h1></main>
    </AppShell>);
    const nav = screen.getByRole("navigation", { name: "全视图导航" });
    expect(within(nav).getByRole("link", { name: "④ 排序验证" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "学习导览" })).toHaveAttribute("href", "./index.html?view=demo");
    expect(screen.queryByRole("button", { name: /导航/ })).not.toBeInTheDocument();
    expect(screen.getByText("数据截止")).toBeVisible();
    expect(screen.getByRole("link", { name: "原始 JSON" })).toBeVisible();
  });
});
