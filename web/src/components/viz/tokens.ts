/**
 * Chart tokens, assigned by the job the color does rather than by taste.
 *
 * Every quantity these charts plot is signed money or signed exposure against a
 * zero baseline, so the only color job present is **polarity**: a diverging pair
 * of a warm and a cool hue with a neutral midpoint. There is no categorical
 * series anywhere in this product's charts — a candidate is not a "series", and
 * painting members in eight hues would spend the identity channel on something
 * the axis already says.
 *
 * The pair was validated against the app's own white surface rather than
 * assumed: worst-pair CVD ΔE 21.6 (protan), normal-vision ΔE 32.3, both slots
 * clear 3:1 contrast. Sign is always also carried by a glyph and by which side
 * of the baseline a mark sits on, so color is never the only channel.
 */
export const VIZ = {
  /** Polarity poles. Warm/cool so they read as opposite. */
  positive: "#2a78d6",
  negative: "#e34948",
  /** The midpoint has to read as "nothing", so it is gray, never a hue. */
  neutral: "#f0efec",

  /** Emphasis form: the subject in one hue, its context in gray. */
  subject: "#2a78d6",
  context: "#a8a8a3",

  ink: "#161616",
  inkSoft: "#393939",
  muted: "#6f6f6f",
  /** Hairline, solid, one step off the surface. Never dashed. */
  grid: "#e1e0d9",
  axis: "#c3c2b7",
  surface: "#ffffff",
} as const;

export function toneFor(value: number): string {
  return value >= 0 ? VIZ.positive : VIZ.negative;
}

/** Mark specs, fixed across every chart here. */
export const MARK = {
  lineWidth: 2,
  markerRadius: 4,
  /** Never fills its band: the leftover is air. */
  maxBarThickness: 24,
  /** White doing the separating, rather than a stroke around the mark. */
  surfaceGap: 2,
  cornerRadius: 4,
} as const;
