"""Risk — stop placement, the cost floor, and position sizing.

THE TWO RULES THAT MATTER
-------------------------
1. The stop goes beyond the level the trade's premise rests on. v1 measured what
   happens otherwise: on 63.8% of its book the stop sat *inside* the 20-bar level,
   a median 0.42 ATR short of it, so price only had to come BACK to the level to
   stop the trade out — no structural break required. Median stop lifetime 7.2 min
   out of a 240-min budget (docs/ANALYSIS-2026-10-05-stop-loss-geometry.md).

2. Refuse the trade if the round trip is not a small share of the risk. This is the
   rule v1 never had, and it is the one its ledger says it needed: median risk
   $3.94 against a $0.55 round trip is 14.0% of R, which moves the break-even
   decisive win rate at 1:1.5 from 40.0% to 43.2%. The whole book lost $0.31/trade
   gross and $0.86/trade net — cost was 1.8x the gross loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import Config


@dataclass(frozen=True)
class Placement:
    """Entry/stop/target geometry, with the reason for the stop distance."""

    entry: float
    stop: float
    target: float
    risk: float  # always > 0, in price units ($ for gold)
    stop_basis: str  # "level" or "atr_floor" — which of the two rules bound


@dataclass(frozen=True)
class Refusal:
    """Why a setup was not taken. Recorded, never silent."""

    reason: str


def place(side: str, entry: float, level: float, atr: float, cfg: Config):
    """Compute the stop/target, or refuse. Returns Placement | Refusal.

    Stop distance is the LARGER of:
      * |entry - level| + stop_clear_atr * atr  — clear the premise
      * min_stop_atr * atr                      — and never so tight that cost eats it
    which of the two bound is reported, because a book whose stops are all
    ATR-floor-bound is a book whose levels are not actually being used.
    """
    if atr is None or atr <= 0:
        return Refusal("no ATR")
    if side not in ("BUY", "SELL"):
        return Refusal(f"bad side {side!r}")

    level_dist = abs(entry - level)
    level_stop_dist = level_dist + cfg.stop_clear_atr * atr
    floor_dist = cfg.min_stop_atr * atr

    if level_stop_dist >= floor_dist:
        dist, basis = level_stop_dist, "level"
    else:
        dist, basis = floor_dist, "atr_floor"

    if side == "BUY":
        stop, target = entry - dist, entry + cfg.rr_target * dist
    else:
        stop, target = entry + dist, entry - cfg.rr_target * dist

    if dist <= 0:
        return Refusal("non-positive stop distance")

    return Placement(entry=entry, stop=stop, target=target, risk=dist, stop_basis=basis)


def cost_gate(risk: float, cfg: Config) -> Optional[str]:
    """Return a refusal reason if this risk is too small to carry the round trip.

    None means "allowed". Kept separate from `place` so a report can count how many
    setups the cost floor rejected — that count is the direct measure of whether a
    timeframe is tradeable at all.
    """
    floor = cfg.min_risk_usd
    if risk < floor:
        return (
            f"risk ${risk:.2f} < {cfg.min_risk_to_cost:.0f}x round trip "
            f"(${floor:.2f}); cost would be {100 * cfg.cost_round_trip / risk:.1f}% of R"
            if risk > 0
            else "risk is zero"
        )
    return None


def lots(risk: float, cfg: Config, contract_size: float = 100.0, volume_step: float = 0.01) -> float:
    """Lot size for `risk_per_trade_usd` of account risk. Rounds DOWN.

    Gold is quoted in USD per troy ounce and a standard lot is 100 oz, so $1.00 of
    price movement on 0.01 lots is $1.00 of P&L. Rounding down is deliberate: sizing
    must never exceed the risk budget because of a rounding direction.

    This is presentation, not expectancy. Judging a signal does not need it; showing
    an operator what the trade would have been does.
    """
    if risk <= 0 or contract_size <= 0 or volume_step <= 0:
        return 0.0
    usd_per_lot_per_point = contract_size
    raw = cfg.risk_per_trade_usd / (risk * usd_per_lot_per_point)
    steps = int(raw / volume_step)
    return max(0.0, round(steps * volume_step, 8))


def pnl(side: str, entry: float, exit_price: float, lot: float, contract_size: float = 100.0) -> float:
    """Realised P&L in USD for a closed position, gross of cost."""
    move = (exit_price - entry) if side == "BUY" else (entry - exit_price)
    return move * lot * contract_size
