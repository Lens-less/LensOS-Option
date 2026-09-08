import { Component, type ReactNode } from "react";

interface ResearchErrorBoundaryProps {
  children: ReactNode;
  /** Names the fallen-back region in the fallback card and the console log. */
  label: string;
  /** Identity of freshly validated input; a valid replacement recovers the region. */
  resetKey?: unknown;
  onRetry?: () => void;
  retrying?: boolean;
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

  componentDidCatch(): void {
    console.error(`${this.props.label} failed to render`);
  }

  componentDidUpdate(previousProps: ResearchErrorBoundaryProps): void {
    if (this.state.error && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render(): ReactNode {
    if (this.state.error !== null) {
      return (
        <section aria-label={this.props.label} className="panel-error" role="alert">
          <h3>研究数据不可用</h3>
          <p>
            这一区域（{this.props.label}）的数据无法安全渲染，已按 fail-closed
            原则整体停用；其余界面不受影响。可在此重新读取并恢复该区域。
          </p>
          <button
            className="refresh-button"
            disabled={this.props.retrying}
            onClick={() => {
              this.props.onRetry?.();
              this.setState({ error: null });
            }}
            type="button"
          >
            {this.props.retrying ? "重新读取中…" : "重试此区域"}
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}
