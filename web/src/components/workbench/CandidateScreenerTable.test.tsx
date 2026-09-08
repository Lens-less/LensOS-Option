import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { candidateRows } from "./candidateModel";
import { CandidateScreenerTable } from "./CandidateScreenerTable";

function rows(count: number) {
  return candidateRows({
    schema_version: "research_report.v1",
    ev_candidate_scanner: {
      status: "validated",
      ranked_candidates: Array.from({ length: count }, (_, index) => ({
        candidate_id: `BTC-7AUG26-${71000 + index}-C:naked`,
        action: "RESEARCH_ONLY",
      })),
    },
  });
}

describe("CandidateScreenerTable", () => {
  it("retains expanded rows when a fresh report has the same candidate order", () => {
    const props = { onSelect: vi.fn(), onSortChange: vi.fn(), selectedId: null, sort: null };
    const { rerender, container } = render(<CandidateScreenerTable {...props} rows={rows(70)} />);
    expect(container.querySelectorAll("tbody tr")).toHaveLength(60);
    fireEvent.click(screen.getByRole("button", { name: "再显示 10 行" }));
    expect(container.querySelectorAll("tbody tr")).toHaveLength(70);

    rerender(<CandidateScreenerTable {...props} rows={rows(70)} />);
    expect(container.querySelectorAll("tbody tr")).toHaveLength(70);
  });

  it("keeps the same candidate in the keyboard tab order after sorting", () => {
    const props = { onSelect: vi.fn(), onSortChange: vi.fn(), selectedId: null, sort: null };
    const candidates = rows(2);
    const { rerender, container } = render(<CandidateScreenerTable {...props} rows={candidates} />);
    const initialRows = container.querySelectorAll("tbody tr");
    fireEvent.keyDown(initialRows[0], { key: "ArrowDown" });
    expect(initialRows[1]).toHaveFocus();

    rerender(<CandidateScreenerTable {...props} rows={[...candidates].reverse()} />);
    expect(initialRows[1]).toHaveAttribute("tabindex", "0");
    expect(initialRows[0]).toHaveAttribute("tabindex", "-1");
  });
});
