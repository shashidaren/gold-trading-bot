"""Signal — a named, swappable entry hypothesis. Not a claim of edge.

BE HONEST ABOUT WHAT THIS IS
----------------------------
This repo has measured, repeatedly and on its own data, that it does not have a
directional edge on gold:

  * after a full 8/8 v1 signal the tape goes the trade's way 49% [41-57] at 30 min
    (docs/ANALYSIS-2026-10-19-signal-outlook.md)
  * box breakouts and fades land on or below the driftless reference in all eight
    geometries tested; 73-75% of breaks close back inside within 15 min
    (docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md)
  * of ~15 extra indicators measured in the lab, none cleared the adoption bar
    (docs/INDICATOR-AUDIT-2026-10-23.md §5b — the one p=0.014 does not survive a
    BUY/SELL split: p=0.294 within BUY, p=0.373 within SELL)

So `trend_pullback` below is a HYPOTHESIS with a name, so that a result can never be
quoted apart from the thing that produced it. It is the hypothesis the v1 evidence
points at, not one that the evidence has already confirmed:

  1. Higher timeframe, because cost/risk is the only lever with a measured payoff.
  2. With-trend, because side ~= momentum is the one relationship that replicated
     (BUY 92% of signals in a rising tape, SELL 93% in a falling one).
  3. Enter on a pullback to the box edge rather than on a break, because the break
     itself measured as noise (74% fail within 15 min) while the *edge* is the one
     thing boxes are genuinely good for — placing a stop behind.

Write a new one by adding a function with the same signature and passing it to
`replay.run(..., signal_fn=your_fn)`. Do not edit this one in place to make a number
look better; that is how the v1 funnel acquired a level gate that is TRUE on 86.9%
of bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from .config import Config
from .data import Bar
from . import indicators


@dataclass(frozen=True)
class Signal:
    """A proposed entry, with the reason it was proposed.

    `level` is the box edge the trade's premise rests on — and therefore the price
    the stop must clear. Carrying it on the signal is what lets `risk` enforce the
    structural stop instead of trusting a multiple of ATR.
    """

    side: str  # "BUY" or "SELL"
    price: float
    level: float
    reasons: List[str]

    def __post_init__(self) -> None:
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {self.side!r}")


@dataclass
class Market:
    """The indicator state at one closed bar, precomputed once per bar.

    Passing this around — rather than letting the signal function recompute EMAs on
    every call — is what keeps a 20-year replay fast enough to iterate on.

    NOT frozen: `index` is a cursor the replay advances, not part of the object's
    identity. The indicator series themselves are built once and never mutated, so a
    signal function still cannot see the future — it can only read `bars[index]` and
    the series at `index`.
    """

    bars: Sequence[Bar]
    index: int
    ema_fast: Sequence[Optional[float]]
    ema_slow: Sequence[Optional[float]]
    ema_fast_slope: Sequence[Optional[float]]
    atr: Sequence[Optional[float]]
    rsi: Sequence[Optional[float]]

    @property
    def bar(self) -> Bar:
        return self.bars[self.index]

    def _at(self, series: Sequence[Optional[float]]) -> Optional[float]:
        return series[self.index]


def build_market(bars: Sequence[Bar], cfg: Config) -> Market:
    """Precompute every indicator series for a bar list, once."""
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    fast = indicators.ema(closes, cfg.ema_fast)
    return Market(
        bars=bars,
        index=0,
        ema_fast=fast,
        ema_slow=indicators.ema(closes, cfg.ema_slow),
        ema_fast_slope=indicators.slope(fast, cfg.slope_bars),
        atr=indicators.atr(highs, lows, closes, cfg.atr_period),
        rsi=indicators.rsi(closes, cfg.rsi_period),
    )


def warmup_bars(cfg: Config) -> int:
    """Bars needed before EVERY indicator this config reads can produce a value.

    Must include the ATR period. Omitting it is not a crash — it is worse: ATR comes
    back None, `risk.place` refuses with "no ATR", and the replay reports zero trades
    with a straight face. Caught by `test_warmup_covers_every_indicator_the_signal_reads`.
    """
    return max(
        cfg.ema_slow,
        cfg.lookback,
        cfg.slope_bars + cfg.ema_fast,
        cfg.atr_period,
        cfg.rsi_period + 1,
    ) + 1


def trend_pullback(market: Market, cfg: Config) -> Optional[Signal]:
    """The default hypothesis: with-trend pullback to the box edge, rejection bar.

    BUY requires ALL of:
      * close above the slow EMA and fast EMA above slow EMA  (with-trend)
      * fast EMA rising over `slope_bars`                     (trend is live, not stale)
      * the bar's low reached within one box of the rolling low (at the edge)
      * close back above the rolling low                      (the edge held)
      * lower wick >= `wick_ratio_min` of bar range           (a rejection, not a pass-through)
    SELL is the exact mirror. Symmetry is enforced by construction, not by a second
    copy of the logic that can drift.
    """
    i = market.index
    if i < warmup_bars(cfg):
        return None

    bar = market.bar
    fast = market._at(market.ema_fast)
    slow = market._at(market.ema_slow)
    sl = market._at(market.ema_fast_slope)
    atr_now = market._at(market.atr)
    if None in (fast, slow, sl, atr_now) or atr_now <= 0:
        return None
    if bar.range <= 0:
        return None

    window = market.bars[i - cfg.lookback : i]
    if len(window) < cfg.lookback:
        return None
    box_low = min(b.low for b in window)
    box_high = max(b.high for b in window)

    for side in ("BUY", "SELL"):
        long = side == "BUY"
        # --- trend ---
        if long and not (bar.close > slow and fast > slow and sl > 0):
            continue
        if not long and not (bar.close < slow and fast < slow and sl < 0):
            continue
        # --- location: the bar must have reached the edge, and held it ---
        if long:
            touched = bar.low <= box_low
            held = bar.close > box_low
            rejection = bar.lower_wick_ratio >= cfg.wick_ratio_min
            level = box_low
        else:
            touched = bar.high >= box_high
            held = bar.close < box_high
            rejection = bar.upper_wick_ratio >= cfg.wick_ratio_min
            level = box_high
        if not (touched and held and rejection):
            continue

        reasons = [
            f"trend {'up' if long else 'down'} (close {bar.close:.2f} vs EMA{cfg.ema_slow} {slow:.2f})",
            f"EMA{cfg.ema_fast} slope {sl:+.2f} over {cfg.slope_bars} bars",
            f"{'tested' if long else 'tagged'} {cfg.lookback}-bar {'low' if long else 'high'} {level:.2f}",
            f"wick {100 * (bar.lower_wick_ratio if long else bar.upper_wick_ratio):.0f}% "
            f">= {100 * cfg.wick_ratio_min:.0f}%",
        ]
        return Signal(side=side, price=bar.close, level=level, reasons=reasons)

    return None


#: Registry so a replay can be selected by name from the CLI or a report.
SIGNALS = {"trend_pullback": trend_pullback}
