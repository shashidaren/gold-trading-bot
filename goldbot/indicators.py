"""Indicators — pure functions over sequences, no state, no classes.

v1 carried EMA/RSI/ATR as mutable state on a 1,760-line engine object, updated in
place as ticks arrived. That is the right shape for a live loop and the wrong shape
for anything you want to test or replay, because the value at bar N depends on the
whole path taken to reach it. Here every indicator is `f(values) -> list`, so a
replay and a live loop compute the same number by calling the same function.

DEFINITIONS MATCH v1 ON PURPOSE (docs/INDICATOR-AUDIT-2026-10-23.md): simple means,
not Wilder smoothing. Two implementations of "RSI(14)" that differ are how a lab
result fails to reproduce.
"""

from __future__ import annotations

from typing import List, Optional, Sequence


def ema(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Exponential moving average, same length as `values`, None until seeded.

    Seeded with the SMA of the first `period` values (the common convention, and the
    one v1's warm-up implies), then alpha = 2/(period+1).
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    prev = seed
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def sma(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Simple moving average, None until `period` values exist."""
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    out: List[Optional[float]] = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> List[float]:
    """True range. The first element is just high-low (no prior close exists)."""
    n = len(closes)
    if not (len(highs) == len(lows) == n):
        raise ValueError("highs/lows/closes must be the same length")
    out: List[float] = []
    for i in range(n):
        if i == 0:
            out.append(highs[i] - lows[i])
        else:
            pc = closes[i - 1]
            out.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return out


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> List[Optional[float]]:
    """ATR as the SIMPLE MEAN of true range (not Wilder) — matches v1 and the lab."""
    return sma(true_range(highs, lows, closes), period)


def rsi(closes: Sequence[float], period: int = 14) -> List[Optional[float]]:
    """RSI on simple means of gains/losses — matches v1's `calculate_rsi`.

    A zero average loss gives 100.0, not a division error.
    """
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains[i] = max(d, 0.0)
        losses[i] = max(-d, 0.0)
    for i in range(period, n):
        avg_gain = sum(gains[i - period + 1 : i + 1]) / period
        avg_loss = sum(losses[i - period + 1 : i + 1]) / period
        if avg_loss == 0.0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def slope(series: Sequence[Optional[float]], bars: int) -> List[Optional[float]]:
    """Change in `series` over `bars` steps. None where either endpoint is missing."""
    out: List[Optional[float]] = [None] * len(series)
    for i in range(bars, len(series)):
        a, b = series[i - bars], series[i]
        if a is None or b is None:
            continue
        out[i] = b - a
    return out
