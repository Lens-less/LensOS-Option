/**
 * Number formatting shared by every surface.
 *
 * The two surfaces formatted the same quantities differently: the workbench
 * rendered `$-120` where the side panel rendered `-120.00 USDC`, and only one
 * of them prefixed positives with a sign. Money that changes shape between two
 * views of one report makes a reader check whether the number changed too.
 */

/** Money, with the sign outside the symbol: -$120, never $-120. */
export function money(
  value: number | null | undefined,
  { fallback = "—", digits = 2 }: { fallback?: string; digits?: number } = {},
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  const magnitude = Math.abs(value).toLocaleString("en-US", {
    maximumFractionDigits: digits,
  });
  return `${value < 0 ? "-" : ""}$${magnitude}`;
}

/**
 * A signed quantity where the sign is the point.
 *
 * Always explicit, and never carried by colour alone: a reader who cannot
 * distinguish the red from the green still reads the sign.
 */
export function signed(
  value: number | null | undefined,
  { digits = 2, fallback = "未评估" }: { digits?: number; fallback?: string } = {},
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  if (value === 0) {
    return "±0";
  }
  const magnitude = Math.abs(value).toFixed(digits);
  return `${value > 0 ? "+" : "-"}${magnitude}`;
}

export function signedMoney(
  value: number | null | undefined,
  options: { digits?: number; fallback?: string } = {},
): string {
  const { digits = 2, fallback = "未评估" } = options;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  if (value === 0) {
    return "±$0";
  }
  const magnitude = Math.abs(value).toLocaleString("en-US", {
    maximumFractionDigits: digits,
  });
  return `${value > 0 ? "+" : "-"}$${magnitude}`;
}

export function dte(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "不可用";
  }
  return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })} 天`;
}

export function strike(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "—";
  }
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function ratio(
  value: number | null | undefined,
  { digits = 3 }: { digits?: number } = {},
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "—";
  }
  return value.toFixed(digits);
}

export function percent(
  value: number | null | undefined,
  { digits = 1 }: { digits?: number } = {},
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(digits)}%`;
}

/**
 * The instrument, split from the structure suffix the engine appends.
 *
 * `BTC-7AUG26-72000-C:naked` identifies one contract; `:naked` identifies the
 * shape wrapped around it. Rows that showed only the shape were
 * indistinguishable from one another.
 */
export function instrumentOf(candidateId: string): string {
  return candidateId.split(":")[0] ?? candidateId;
}

/** Sign classification used to colour a value *in addition to* its sign glyph. */
export function signTone(
  value: number | null | undefined,
): "positive" | "negative" | undefined {
  if (typeof value !== "number" || !Number.isFinite(value) || value === 0) {
    return undefined;
  }
  return value > 0 ? "positive" : "negative";
}
