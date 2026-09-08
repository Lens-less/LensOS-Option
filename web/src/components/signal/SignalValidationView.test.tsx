import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import demoSignal from "../../../../crypto_options_report/resources/demo-signal-preflight.json";
import { SignalValidationView } from "./SignalValidationView";

describe("signal evidence progress", () => {
  it("explains what the bundled preflight has collected and what still prevents a measured conclusion", () => {
    render(<SignalValidationView artifact={demoSignal} />);

    const panel = screen.getByRole("region", { name: "信号验证进度" });
    const progress = within(panel).getByRole("progressbar", { name: "已结算到期组" });
    expect(progress).toHaveAttribute("value", "0");
    expect(progress).toHaveAttribute("max", "8");
    expect(within(panel).getByText("2026-07-07")).toBeVisible();
    expect(within(panel).getByText(/还需 8 个已结算到期组/)).toBeVisible();
    expect(within(panel).getByText("待结算观测")).toHaveTextContent("待结算观测 8");
    expect(within(panel).getByText(/预检.*未产生预测力结论/)).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("keeps unknown sample counts unknown and explains how to resume a missing artifact", () => {
    const { rerender } = render(<SignalValidationView artifact={{ status: "blocked", sample: {}, reason_codes: ["INSUFFICIENT_OBSERVATIONS"] }} />);
    expect(screen.getByRole("region", { name: "信号验证进度" })).toHaveTextContent("未提供");
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByText(/已采集 0/)).not.toBeInTheDocument();

    rerender(<SignalValidationView artifact={{ status: "not_configured", detail: "本地引擎不可达。" }} />);
    expect(screen.getByRole("heading", { name: "信号验证产物尚不可用" })).toBeVisible();
    expect(screen.getByText(/重新读取当前报告/)).toBeVisible();
    expect(screen.getByText("本地引擎不可达。")).toBeVisible();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});
