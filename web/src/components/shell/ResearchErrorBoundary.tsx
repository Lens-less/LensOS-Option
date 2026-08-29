import { Component, type ErrorInfo, type ReactNode } from "react";

interface ResearchErrorBoundaryProps {
  children: ReactNode;
  /** Names the fallen-back region in the fallback card and the console log. */
  label: string;
}

interface ResearchErrorBoundaryState {
  error: Error | null;
}

/**
 * Fail-closed render guard: a payload the model layer could not narrow must
 * degrade its own region to an explicit "research data unavailable" card
 * instead of letting React unmount the whole tree to a white screen.
 */
export class ResearchErrorBoundary extends Component<
  ResearchErrorBoundaryProps,
  ResearchErrorBoundaryState
> {
  state: ResearchErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ResearchErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`${this.props.label} failed to render`, error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error !== null) {
      return (
        <section aria-label={this.props.label} className="panel-error" role="alert">
          <h3>研究数据不可用</h3>
          <p>
            这一区域（{this.props.label}）的数据无法安全渲染，已按 fail-closed
            原则整体停用；其余界面不受影响。请刷新或检查本地引擎输出后重试。
          </p>
        </section>
      );
    }
    return this.props.children;
  }
}
