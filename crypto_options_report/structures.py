"""Multi-leg option structures: terminal payoff, risk bounds, position greeks.

Before this module the product knew exactly two shapes, and it knew them as
string constants. `naked_short_call` and `call_credit_spread` were branched on
in the path-risk tracer, in the edge score, in the portfolio arbiter and in the
P&L tracer, and every one of those branches also hard-coded the assumption that
the position was short and that the risk was on the upside. Adding a put spread
would have meant finding all of them; adding a calendar would have meant
rewriting them.

The replacement rests on one observation: a European multi-leg position has a
payoff that is **piecewise linear in terminal spot, with kinks only at the
strikes**. That makes every question the product asks answerable exactly, with
no simulation and no per-structure special case:

* the payoff is evaluated by summing signed leg intrinsics;
* the maximum loss is found by evaluating at the kinks and inspecting the two
  asymptotic slopes, so "is this risk bounded" is decided rather than declared;
* position greeks are the quantity-weighted sum of leg greeks, which removes the
  sign-flipping that each call site used to do by hand.

Two conventions are fixed here and relied on everywhere else:

* **Quantity carries direction.** `quantity` is positive for a long leg and
  negative for a short one. There is no separate "short" flag, so no code path
  can disagree about which way a position faces.
* **Cash follows the holder.** `entry_cash` is positive when the position was
  opened for a net credit and negative for a net debit, so profit is always
  `entry_cash + value_at_expiry` regardless of structure.

Unboundedness is a real answer, not an error. A naked short call is genuinely
exposed without limit, and `max_loss` is `None` for it rather than some large
finite number that would let a downstream ratio quietly succeed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

STRUCTURE_SCHEMA_VERSION = "option_structure.v1"

CALL = "call"
PUT = "put"
OPTION_TYPES = frozenset({CALL, PUT})

# Spot cannot go below zero, so the downside of any position is bounded by the
# payoff at zero. Only the upside can be genuinely unbounded, and only when the
# net call quantity is negative.
ZERO_SPOT = 0.0


@dataclass(frozen=True)
class Leg:
    """One option leg. `quantity` is signed: positive long, negative short."""

    option_type: str
    strike: float
    quantity: float
    expiry_date: str | None = None
    instrument_name: str | None = None

    def __post_init__(self) -> None:
        if self.option_type not in OPTION_TYPES:
            raise ValueError(f"leg option_type must be call or put: {self.option_type!r}")
        if not _is_finite(self.strike) or self.strike <= 0:
            raise ValueError("leg strike must be a positive finite number")
        if not _is_finite(self.quantity) or self.quantity == 0:
            raise ValueError("leg quantity must be a non-zero finite number")

    def intrinsic_at(self, terminal_spot: float) -> float:
        """Per-unit intrinsic value at expiry, before the quantity sign."""
        if self.option_type == CALL:
            return max(terminal_spot - self.strike, 0.0)
        return max(self.strike - terminal_spot, 0.0)

    def value_at(self, terminal_spot: float) -> float:
        """Signed value to the holder: negative for a short leg that finished ITM."""
        return self.quantity * self.intrinsic_at(terminal_spot)

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_type": self.option_type,
            "strike": self.strike,
            "quantity": self.quantity,
            "expiry_date": self.expiry_date,
            "instrument_name": self.instrument_name,
            "direction": "long" if self.quantity > 0 else "short",
        }


@dataclass(frozen=True)
class RiskProfile:
    """The exact terminal risk of a structure, given what it was opened for.

    `max_loss` is None precisely when the loss is unbounded. Callers that need
    a denominator must treat None as "no ratio is defined" rather than
    substituting a number, which is why the flag and the value are reported
    together rather than one being inferred from the other.
    """

    max_loss: float | None
    max_profit: float | None
    loss_is_bounded: bool
    profit_is_bounded: bool
    breakevens: tuple[float, ...]
    upside_slope: float
    downside_slope: float
    entry_cash: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_loss": self.max_loss,
            "max_profit": self.max_profit,
            "loss_is_bounded": self.loss_is_bounded,
            "profit_is_bounded": self.profit_is_bounded,
            "breakevens": list(self.breakevens),
            "upside_slope": self.upside_slope,
            "downside_slope": self.downside_slope,
            "entry_cash": self.entry_cash,
            "is_credit": self.entry_cash > 0,
        }


@dataclass(frozen=True)
class Structure:
    """A set of signed legs treated as one position."""

    structure_type: str
    legs: tuple[Leg, ...]
    contract_size: float = 1.0

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("structure must contain at least one leg")
        if not _is_finite(self.contract_size) or self.contract_size <= 0:
            raise ValueError("structure contract_size must be positive and finite")
        expiries = {leg.expiry_date for leg in self.legs if leg.expiry_date}
        if len(expiries) > 1 and not self.is_multi_expiry:
            # Reaching here means a caller built a calendar through a
            # single-expiry constructor; the terminal-payoff model below is only
            # valid when every leg expires together.
            raise ValueError(
                "structure spans multiple expiries but is not declared multi-expiry"
            )

    @property
    def is_multi_expiry(self) -> bool:
        """True when the legs do not all expire together.

        A terminal payoff is only well defined for a single expiry date. A
        calendar's near leg expires while the far leg still carries time value,
        which no function in this module can price, so the multi-expiry case is
        flagged and refused rather than silently evaluated at one date.
        """
        expiries = {leg.expiry_date for leg in self.legs if leg.expiry_date}
        return len(expiries) > 1

    @property
    def expiry_date(self) -> str | None:
        expiries = sorted({leg.expiry_date for leg in self.legs if leg.expiry_date})
        return expiries[0] if len(expiries) == 1 else None

    @property
    def strikes(self) -> tuple[float, ...]:
        return tuple(sorted({leg.strike for leg in self.legs}))

    @property
    def upside_slope(self) -> float:
        """Payoff slope above every strike: the net call quantity."""
        return round(
            sum(leg.quantity for leg in self.legs if leg.option_type == CALL), 10
        )

    @property
    def downside_slope(self) -> float:
        """Payoff slope below every strike: puts gain as spot falls."""
        return round(
            -sum(leg.quantity for leg in self.legs if leg.option_type == PUT), 10
        )

    def value_at(self, terminal_spot: float) -> float:
        """Signed value of the position at expiry, in quote currency."""
        self._require_single_expiry("value_at")
        if not _is_finite(terminal_spot) or terminal_spot < 0:
            raise ValueError("terminal_spot must be a non-negative finite number")
        total = sum(leg.value_at(terminal_spot) for leg in self.legs)
        return round(total * self.contract_size, 8)

    def amount_owed_at(self, terminal_spot: float) -> float:
        """What the position owes at expiry; zero when it finishes in credit.

        This is the quantity a short seller settles, and it is what the
        path-risk tracer treats as the payout. It is never negative: value the
        position keeps is profit, not a negative obligation.
        """
        return round(max(-self.value_at(terminal_spot), 0.0), 8)

    def finishes_in_obligation(self, terminal_spot: float) -> bool:
        """The general form of "expired ITM" for a structure rather than a leg."""
        return self.amount_owed_at(terminal_spot) > 0.0

    def pnl_at(self, terminal_spot: float, *, entry_cash: float) -> float:
        """Profit at expiry. `entry_cash` is positive for a net credit."""
        return round(entry_cash + self.value_at(terminal_spot), 8)

    def risk_profile(self, *, entry_cash: float) -> RiskProfile:
        """Exact maximum loss, maximum profit and breakevens.

        The payoff is piecewise linear with kinks only at the strikes, so
        scanning the kinks plus zero and inspecting the two asymptotic slopes is
        not an approximation — it is the complete answer.
        """
        self._require_single_expiry("risk_profile")
        if not _is_finite(entry_cash):
            raise ValueError("entry_cash must be finite")

        points = self._evaluation_points()
        values = [self.pnl_at(point, entry_cash=entry_cash) for point in points]

        upside = self.upside_slope
        downside = self.downside_slope
        # Below the lowest strike the payoff runs to the spot-zero boundary, so
        # the downside is always bounded; above the highest strike it runs
        # forever, so only a negative net call quantity is unbounded.
        loss_is_bounded = upside >= 0
        profit_is_bounded = upside <= 0

        max_loss = None if not loss_is_bounded else round(-min(values), 8)
        max_profit = None if not profit_is_bounded else round(max(values), 8)
        if max_loss is not None and max_loss < 0:
            # Every evaluated point is profitable. That is an arbitrage claim,
            # so it is reported as a zero floor rather than a negative loss.
            max_loss = 0.0

        return RiskProfile(
            max_loss=max_loss,
            max_profit=max_profit,
            loss_is_bounded=loss_is_bounded,
            profit_is_bounded=profit_is_bounded,
            breakevens=self._breakevens(points, values, upside_slope=upside),
            upside_slope=upside,
            downside_slope=downside,
            entry_cash=round(entry_cash, 8),
        )

    def position_greeks(self, leg_greeks: dict[str, dict[str, float]]) -> dict[str, Any]:
        """Quantity-weighted greeks, keyed by instrument name.

        Every call site used to negate the long option's greeks by hand to get
        the short position's, which is correct exactly until a structure mixes
        directions. Weighting by signed quantity gives the position's greeks for
        any structure without a sign convention to remember.

        A leg with no greeks blocks the aggregate rather than contributing zero:
        a missing vega is not a vega of nothing, and summing it as zero would
        make an under-hedged position look neutral.
        """
        totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
        missing: list[str] = []
        for leg in self.legs:
            key = leg.instrument_name or ""
            greeks = leg_greeks.get(key)
            if not isinstance(greeks, dict):
                missing.append(key or "<unnamed leg>")
                continue
            for name in totals:
                value = greeks.get(name)
                if not _is_number(value):
                    missing.append(f"{key or '<unnamed leg>'}.{name}")
                    continue
                totals[name] += leg.quantity * float(value) * self.contract_size

        if missing:
            return {
                "status": "blocked",
                "reason_code": "MISSING_LEG_GREEKS",
                "missing": sorted(set(missing)),
                "delta": None,
                "gamma": None,
                "theta": None,
                "vega": None,
            }
        return {
            "status": "aggregated",
            "reason_code": None,
            "missing": [],
            **{name: round(value, 8) for name, value in totals.items()},
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STRUCTURE_SCHEMA_VERSION,
            "structure_type": self.structure_type,
            "contract_size": self.contract_size,
            "expiry_date": self.expiry_date,
            "is_multi_expiry": self.is_multi_expiry,
            "leg_count": len(self.legs),
            "legs": [leg.to_dict() for leg in self.legs],
            "upside_slope": self.upside_slope,
            "downside_slope": self.downside_slope,
        }

    # --- internals ---------------------------------------------------------

    def _require_single_expiry(self, operation: str) -> None:
        if self.is_multi_expiry:
            raise ValueError(
                f"{operation} is undefined for a multi-expiry structure: the near "
                "leg settles while the far leg still carries time value"
            )

    def _evaluation_points(self) -> tuple[float, ...]:
        """Kinks, plus one point beyond the outermost strike on each side.

        The outside points do not add information about the maximum on a bounded
        side, but they make the sign of each tail explicit for the breakeven
        scan below.
        """
        strikes = self.strikes
        highest = strikes[-1]
        beyond = highest * 2.0 if highest > 0 else 1.0
        return (ZERO_SPOT, *strikes, beyond)

    def _breakevens(
        self,
        points: tuple[float, ...],
        values: list[float],
        *,
        upside_slope: float,
    ) -> tuple[float, ...]:
        """Spot levels where profit crosses zero, by exact linear interpolation."""
        crossings: list[float] = []
        for index in range(len(points) - 1):
            left_value, right_value = values[index], values[index + 1]
            if left_value == 0.0:
                crossings.append(points[index])
                continue
            if (left_value < 0) == (right_value < 0):
                continue
            span = right_value - left_value
            if span == 0:
                continue
            fraction = -left_value / span
            crossings.append(
                points[index] + fraction * (points[index + 1] - points[index])
            )
        if values[-1] == 0.0:
            crossings.append(points[-1])

        # Beyond the last strike the payoff is a straight line, so a tail that
        # has not crossed yet crosses at a computable point rather than never.
        if upside_slope != 0 and values[-1] != 0:
            tail_root = points[-1] - values[-1] / (upside_slope * self.contract_size)
            if tail_root > points[-1]:
                crossings.append(tail_root)

        return tuple(sorted({round(value, 6) for value in crossings}))


# --- constructors ----------------------------------------------------------


def build_structure(
    *,
    structure_type: str,
    legs: list[dict[str, Any]],
    contract_size: float = 1.0,
) -> Structure:
    """Build a structure from plain leg dictionaries, validating each leg."""
    if not isinstance(legs, list) or not legs:
        raise ValueError("structure legs must be a non-empty list")
    built = tuple(
        Leg(
            option_type=str(leg.get("option_type") or ""),
            strike=_required_number(leg.get("strike"), "leg strike"),
            quantity=_required_number(leg.get("quantity"), "leg quantity"),
            expiry_date=(
                str(leg["expiry_date"]) if leg.get("expiry_date") is not None else None
            ),
            instrument_name=(
                str(leg["instrument_name"])
                if leg.get("instrument_name") is not None
                else None
            ),
        )
        for leg in legs
        if isinstance(leg, dict)
    )
    if len(built) != len(legs):
        raise ValueError("every structure leg must be an object")
    return Structure(
        structure_type=str(structure_type),
        legs=built,
        contract_size=contract_size,
    )


def naked_short_call(
    *,
    strike: float,
    expiry_date: str | None = None,
    instrument_name: str | None = None,
    contract_size: float = 1.0,
) -> Structure:
    return Structure(
        structure_type="naked_short_call",
        legs=(
            Leg(
                option_type=CALL,
                strike=strike,
                quantity=-1.0,
                expiry_date=expiry_date,
                instrument_name=instrument_name,
            ),
        ),
        contract_size=contract_size,
    )


def call_credit_spread(
    *,
    short_strike: float,
    long_strike: float,
    expiry_date: str | None = None,
    short_instrument: str | None = None,
    long_instrument: str | None = None,
    contract_size: float = 1.0,
) -> Structure:
    if long_strike <= short_strike:
        raise ValueError("call_credit_spread long strike must exceed the short strike")
    return Structure(
        structure_type="call_credit_spread",
        legs=(
            Leg(
                option_type=CALL,
                strike=short_strike,
                quantity=-1.0,
                expiry_date=expiry_date,
                instrument_name=short_instrument,
            ),
            Leg(
                option_type=CALL,
                strike=long_strike,
                quantity=1.0,
                expiry_date=expiry_date,
                instrument_name=long_instrument,
            ),
        ),
        contract_size=contract_size,
    )


# --- helpers ---------------------------------------------------------------


def _is_finite(value: Any) -> bool:
    return _is_number(value) and math.isfinite(float(value))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _required_number(value: Any, field_name: str) -> float:
    if not _is_finite(value):
        raise ValueError(f"{field_name} must be a finite number")
    return float(value)
