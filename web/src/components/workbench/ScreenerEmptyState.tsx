export function ScreenerEmptyState({
  onReset,
  showReset,
  totalCount,
  visibleCount,
}: {
  onReset: () => void;
  showReset: boolean;
  totalCount: number;
  visibleCount: number;
}): React.JSX.Element {
  return (
    <div className="screener-empty-state" role="status">
      <strong>当前筛选条件排除了全部候选</strong>
      <p>
        {visibleCount} / {totalCount} 个候选通过当前筛选；调整或重置条件以查看更多研究候选。
      </p>
      {showReset ? (
        <button
          className="screener-reset-cta"
          onClick={onReset}
          type="button"
        >
          重置筛选条件
        </button>
      ) : null}
    </div>
  );
}
