/**
 * Terminal payoff from a structure's legs.
 *
 * This mirrors `structures.py`: a European multi-leg position is piecewise
 * linear in terminal spot with kinks only at the strikes, so the whole curve is
 * a signed sum of leg intrinsics and every interesting point is a strike.
 *
 * It is a deliberate mirror rather than a server call, because a payoff curve
 * has to redraw as the reader moves between candidates and a round trip per
 * hover is not a curve. The mirror is kept to one expression and is tested
 * against the same structures the Python tests pin — condor, put spread, ratio —
 * so a divergence fails a test rather than reaching a chart.
 */
export interface PayoffLeg {
  option_type?: string | null;
  strike?: number | null;
  quantity?: number | null;
  expiry_date?: string | null;
}

export interface ParsedLeg {
  optionType: "call" | "put";
  strike: number;
  quantity: number;
  expiryDate: string | null;
}

export function parseLegs(legs: unknown): ParsedLeg[] {
  if (!Array.isArray(legs)) {
    return [];
  }
  const parsed: ParsedLeg[] = [];
  for (const raw of legs) {
    if (!raw || typeof raw !== "object") {
      continue;
    }
    const leg = raw as PayoffLeg;
    const optionType = leg.option_type === "put" ? "put" : "call";
    const strike = typeof leg.strike === "number" ? leg.strike : NaN;
    const quantity = typeof leg.quantity === "number" ? leg.quantity : NaN;
    if (!Number.isFinite(strike) || !Number.isFinite(quantity) || quantity === 0) {
      continue;
    }
    parsed.push({
      optionType,
      strike,
      quantity,
      expiryDate:
        typeof leg.expiry_date === "string" ? leg.expiry_date : null,
    });
  }
  return parsed;
}

/** Signed value to the holder at expiry: negative where a short leg finished ITM. */
export function valueAt(legs: ParsedLeg[], terminalSpot: number): number {
  let total = 0;
  for (const leg of legs) {
    const intrinsic =
      leg.optionType === "call"
        ? Math.max(terminalSpot - leg.strike, 0)
        : Math.max(leg.strike - terminalSpot, 0);
    total += leg.quantity * intrinsic;
  }
  return total;
}

export function pnlAt(
  legs: ParsedLeg[],
  terminalSpot: number,
  entryCash: number,
): number {
  return entryCash + valueAt(legs, terminalSpot);
}

/** Net call quantity: the payoff slope above every strike. */
export function upsideSlope(legs: ParsedLeg[]): number {
  return legs
    .filter((leg) => leg.optionType === "call")
    .reduce((total, leg) => total + leg.quantity, 0);
}

export function lossIsBounded(legs: ParsedLeg[]): boolean {
  return upsideSlope(legs) >= 0;
}

/**
 * The spot range worth drawing.
 *
 * Wide enough that the outer strikes are not on the frame, and always centred
 * so the reader can see both sides of the position rather than the side the
 * structure happens to face.
 */
export function payoffDomain(
  legs: ParsedLeg[],
  spot: number | null,
): [number, number] {
  const strikes = legs.map((leg) => leg.strike);
  const anchors = strikes.concat(
    typeof spot === "number" && Number.isFinite(spot) ? [spot] : [],
  );
  if (anchors.length === 0) {
    return [0, 1];
  }
  const low = Math.min(...anchors);
  const high = Math.max(...anchors);
  const pad = Math.max((high - low) * 0.6, high * 0.12, 1);
  return [Math.max(low - pad, 0), high + pad];
}

export function payoffPoints(
  legs: ParsedLeg[],
  {
    entryCash,
    spot,
    samples = 120,
  }: { entryCash: number; spot: number | null; samples?: number },
): Array<{ spot: number; pnl: number }> {
  if (legs.length === 0) {
    return [];
  }
  const [low, high] = payoffDomain(legs, spot);
  // Sample evenly, then force every strike into the sample set: the kinks are
  // where the curve changes and a uniform grid can step straight over one.
  const grid = new Set<number>();
  for (let index = 0; index <= samples; index += 1) {
    grid.add(low + ((high - low) * index) / samples);
  }
  for (const leg of legs) {
    if (leg.strike >= low && leg.strike <= high) {
      grid.add(leg.strike);
    }
  }
  return Array.from(grid)
    .sort((left, right) => left - right)
    .map((terminalSpot) => ({
      spot: terminalSpot,
      pnl: pnlAt(legs, terminalSpot, entryCash),
    }));
}

/** Breakevens by exact interpolation between adjacent sampled points. */
export function breakevens(
  points: Array<{ spot: number; pnl: number }>,
): number[] {
  const crossings: number[] = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const left = points[index];
    const right = points[index + 1];
    if (left.pnl === 0) {
      crossings.push(left.spot);
      continue;
    }
    if (left.pnl < 0 === right.pnl < 0) {
      continue;
    }
    const span = right.pnl - left.pnl;
    if (span === 0) {
      continue;
    }
    crossings.push(left.spot + (-left.pnl / span) * (right.spot - left.spot));
  }
  return Array.from(new Set(crossings.map((value) => Math.round(value))));
}
