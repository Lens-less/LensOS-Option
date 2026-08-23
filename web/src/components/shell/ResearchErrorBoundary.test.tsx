import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ResearchErrorBoundary } from "./ResearchErrorBoundary";

function Boom(): React.JSX.Element {
  throw new TypeError("component.value.toLocaleString is not a function");
}

describe("ResearchErrorBoundary", () => {
  it("degrades its own region instead of unmounting the page", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    try {
      render(
        <ResearchErrorBoundary label="候选研究工作台">
          <p>周围界面</p>
          <Boom />
        </ResearchErrorBoundary>,
      );

      expect(screen.getByRole("alert")).toHaveTextContent("研究数据不可用");
      expect(screen.getByRole("alert")).toHaveTextContent("候选研究工作台");
      // The failure is logged for triage, not swallowed.
      expect(consoleError).toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
  });

  it("renders children untouched when nothing throws", () => {
    render(
      <ResearchErrorBoundary label="证据控制台">
        <p>正常内容</p>
      </ResearchErrorBoundary>,
    );

    expect(screen.getByText("正常内容")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
