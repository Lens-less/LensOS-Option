import type { CandidateAction } from "../../contracts";
import type { ScreenerFilters } from "./filterModel";
import { ALL_ACTION_TIERS, isDefaultFilters } from "./filterModel";

const TIER_LABELS: Record<CandidateAction, string> = {
  RESEARCH_ONLY: "仅研究",
  REVIEW: "待复核",
  REJECT: "已拒绝",
};

function parseOptionalNumber(raw: string): number | null {
  if (raw.trim() === "") {
    return null;
  }
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

export function ScreenerControls({
  disabled = false,
  filters,
  onChange,
  onReset,
  structureOptions,
}: {
  disabled?: boolean;
  filters: ScreenerFilters;
  onChange: (next: ScreenerFilters) => void;
  onReset: () => void;
  structureOptions: string[];
}): React.JSX.Element {
  const toggleStructure = (structureType: string) => {
    const isSelected = filters.structureTypes.includes(structureType);
    onChange({
      ...filters,
      structureTypes: isSelected
        ? filters.structureTypes.filter((value) => value !== structureType)
        : [...filters.structureTypes, structureType],
    });
  };

  const toggleTier = (tier: CandidateAction) => {
    const isSelected = filters.actionTiers.includes(tier);
    const nextTiers = isSelected
      ? filters.actionTiers.filter((value) => value !== tier)
      : [...filters.actionTiers, tier];
    onChange({ ...filters, actionTiers: nextTiers });
  };

  return (
    <fieldset className="screener-controls" disabled={disabled}>
      <legend className="section-kicker">Screener filters / 筛选器</legend>

      <div className="screener-control-group" role="group" aria-label="结构类型">
        <span className="screener-control-label">结构类型</span>
        <div className="screener-checkbox-row">
          {structureOptions.length === 0 ? (
            <span className="screener-control-empty">无可用结构</span>
          ) : (
            structureOptions.map((structureType) => (
              <label className="screener-checkbox" key={structureType}>
                <input
                  checked={filters.structureTypes.includes(structureType)}
                  onChange={() => toggleStructure(structureType)}
                  type="checkbox"
                />
                <span>{structureType}</span>
              </label>
            ))
          )}
        </div>
      </div>

      <div className="screener-control-group" role="group" aria-label="到期天数区间">
        <span className="screener-control-label">到期天数（DTE）</span>
        <div className="screener-range-row">
          <label>
            <span>最少</span>
            <input
              aria-label="最少到期天数"
              inputMode="decimal"
              onChange={(event) =>
                onChange({
                  ...filters,
                  dteMin: parseOptionalNumber(event.target.value),
                })
              }
              type="number"
              value={filters.dteMin ?? ""}
            />
          </label>
          <label>
            <span>最多</span>
            <input
              aria-label="最多到期天数"
              inputMode="decimal"
              onChange={(event) =>
                onChange({
                  ...filters,
                  dteMax: parseOptionalNumber(event.target.value),
                })
              }
              type="number"
              value={filters.dteMax ?? ""}
            />
          </label>
        </div>
      </div>

      <div className="screener-control-group" role="group" aria-label="绝对 Delta 区间">
        <span className="screener-control-label">|Delta| 区间</span>
        <div className="screener-range-row">
          <label>
            <span>最小</span>
            <input
              aria-label="最小绝对 Delta"
              inputMode="decimal"
              onChange={(event) =>
                onChange({
                  ...filters,
                  absDeltaMin: parseOptionalNumber(event.target.value),
                })
              }
              step="0.01"
              type="number"
              value={filters.absDeltaMin ?? ""}
            />
          </label>
          <label>
            <span>最大</span>
            <input
              aria-label="最大绝对 Delta"
              inputMode="decimal"
              onChange={(event) =>
                onChange({
                  ...filters,
                  absDeltaMax: parseOptionalNumber(event.target.value),
                })
              }
              step="0.01"
              type="number"
              value={filters.absDeltaMax ?? ""}
            />
          </label>
        </div>
      </div>

      <div className="screener-control-group">
        <label className="screener-control-label" htmlFor="screener-min-credit">
          最低可成交信用（USDC）
        </label>
        <input
          id="screener-min-credit"
          inputMode="decimal"
          onChange={(event) =>
            onChange({
              ...filters,
              minCreditUsdc: parseOptionalNumber(event.target.value),
            })
          }
          type="number"
          value={filters.minCreditUsdc ?? ""}
        />
      </div>

      <div className="screener-control-group" role="group" aria-label="研究分层">
        <span className="screener-control-label">研究分层（服务端判定，筛选不改变分层）</span>
        <div className="screener-checkbox-row">
          {ALL_ACTION_TIERS.map((tier) => (
            <label className="screener-checkbox" key={tier}>
              <input
                checked={filters.actionTiers.includes(tier)}
                onChange={() => toggleTier(tier)}
                type="checkbox"
              />
              <span>{TIER_LABELS[tier]}</span>
            </label>
          ))}
        </div>
      </div>

      {disabled ? null : (
        <button
          className="screener-reset-button"
          disabled={isDefaultFilters(filters)}
          onClick={onReset}
          type="button"
        >
          重置筛选
        </button>
      )}
    </fieldset>
  );
}
