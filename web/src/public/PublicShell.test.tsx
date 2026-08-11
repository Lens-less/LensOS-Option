import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ResearchReport } from "../contracts";
import { safeResearchReport } from "../report/testFixtures";
import { PublicShell } from "./PublicShell";
import type { PublicFreshness } from "./publicModel";

const currentFreshness: PublicFreshness = {
  ageSec: 4,
  maxAgeSec: 60,
  mode: "live",
  phase: "current",
};

function renderShell({
  freshness = currentFreshness,
  report = safeResearchReport,
}: {
  freshness?: PublicFreshness;
  report?: ResearchReport;
} = {}): void {
  render(
    <PublicShell
      freshness={freshness}
      onRefresh={vi.fn()}
      refreshing={false}
      report={report}
      view="evidence"
    >
      <main id="surface-main">研究正文</main>
    </PublicShell>,
  );
}

afterEach(() => {
  window.history.replaceState({}, "", "/");
});

describe("PublicShell", () => {
  it("keeps the public footer aligned with the preview safety boundary", () => {
    renderShell();

    const footer = screen.getByRole("contentinfo");
    expect(footer).toHaveTextContent("RESEARCH_ONLY · NO_TRADE");
    expect(footer).toHaveTextContent(
      "执行授权始终关闭；页面不连接下单、仓位计算或自动执行。",
    );
  });

  it("marks a same-page chapter link as the current location", () => {
    window.history.replaceState({}, "", "/#surface");

    renderShell();

    expect(
      screen.getByRole("link", { name: "曲面贵在哪里" }),
    ).toHaveAttribute("aria-current", "location");
    expect(screen.getByRole("link", { name: "现在贵不贵" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("keeps the no-trade boundary visible when a publication is stale", () => {
    renderShell({
      freshness: {
        ageSec: 172_800,
        maxAgeSec: 86_400,
        mode: "published",
        phase: "expired",
      },
      report: {
        ...safeResearchReport,
        runtime_context: { mode: "published" },
        publish_edition: {
          captured_at: "2026-07-24T10:25:00Z",
          stale_after: "2026-07-25T10:25:00Z",
        },
      },
    });

    expect(screen.getByRole("alert")).toHaveTextContent("发布已停摆");
    expect(screen.getByText("RESEARCH_ONLY · NO_TRADE")).toBeInTheDocument();
  });
});
