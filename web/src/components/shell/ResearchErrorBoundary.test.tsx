import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchErrorBoundary } from "./ResearchErrorBoundary";

function View({ broken }: { broken: boolean }): React.JSX.Element {
  if (broken) throw new Error("private report contents");
  return <p>已恢复研究视图</p>;
}

describe("ResearchErrorBoundary recovery", () => {
  afterEach(() => vi.restoreAllMocks());

  it("degrades only its own region and logs the failure", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<><p>周围界面</p><ResearchErrorBoundary label="候选研究工作台"><View broken /></ResearchErrorBoundary></>);
    expect(screen.getByRole("alert")).toHaveTextContent("研究数据不可用");
    expect(screen.getByRole("alert")).toHaveTextContent("候选研究工作台");
    expect(screen.getByText("周围界面")).toBeInTheDocument();
    expect(consoleError).toHaveBeenCalled();
  });

  it("renders children untouched when nothing throws", () => {
    render(<ResearchErrorBoundary label="证据控制台"><p>正常内容</p></ResearchErrorBoundary>);
    expect(screen.getByText("正常内容")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("recovers on new validated data without remounting the page", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { rerender } = render(<ResearchErrorBoundary label="研究区域" resetKey="first"><View broken /></ResearchErrorBoundary>);
    expect(screen.getByRole("alert")).not.toHaveTextContent("private report contents");
    rerender(<ResearchErrorBoundary label="研究区域" resetKey="second"><View broken={false} /></ResearchErrorBoundary>);
    expect(screen.getByText("已恢复研究视图")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("can retry a transient rendering failure inside the page", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    let broken = true;
    const onRetry = vi.fn(() => { broken = false; });
    function Transient(): React.JSX.Element { return <View broken={broken} />; }
    render(<ResearchErrorBoundary label="研究区域" onRetry={onRetry}><Transient /></ResearchErrorBoundary>);
    fireEvent.click(screen.getByRole("button", { name: "重试此区域" }));
    expect(onRetry).toHaveBeenCalledOnce();
    expect(screen.getByText("已恢复研究视图")).toBeInTheDocument();
  });
});
