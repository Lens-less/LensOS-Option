import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SiteFooter } from "./SiteFooter";

describe("SiteFooter", () => {
  it("states the research-only no-trade boundary in clear Chinese", () => {
    render(<SiteFooter />);

    const footer = screen.getByRole("contentinfo");
    expect(footer).toHaveTextContent("RESEARCH_ONLY · NO_TRADE");
    expect(footer).toHaveTextContent(
      "执行授权始终关闭；页面不连接下单、仓位计算或自动执行。",
    );
    expect(footer).not.toHaveTextContent("仓位 sizing");
  });
});
