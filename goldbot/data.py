"""Bar loading and timeframe aggregation.

One loader, because `tools/history_to_log.py` already normalises broker history into
the `forward_test_log.csv` schema (and proves the broker-server -> UTC offset rather
than guessing it). So both the live log and the large-N research path arrive here in
the same shape.

AGGREGATION INVARIANT (tested): aggregation must never invent a bar. A bucket is
emitted only when a later bar proves it closed, and the caller decides whether the
still-forming bucket is exposed. Getting this wrong is the classic way a backtest
learns to trade the future.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Iterator, List, Optional, Sequence

TS_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class Bar:
    """One OHLC bar. `ts` is when the bar CLOSED, matching forward_test_log.csv."""

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    #: Tick count, if the source carries one. Not traded volume — the feed is MT5
    #: *tick* volume, so anything that treats this as volume is a guess in a formula
    #: (docs/INDICATOR-AUDIT-2026-10-23.md).
    ticks: Optional[int] = None

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body_bottom(self) -> float:
        return min(self.open, self.close)

    @property
    def body_top(self) -> float:
        return max(self.open, self.close)

    @property
    def lower_wick_ratio(self) -> float:
        """Lower wick as a share of bar range; 0.0 on a zero-range bar."""
        r = self.range
        return (self.body_bottom - self.low) / r if r > 0 else 0.0

    @property
    def upper_wick_ratio(self) -> float:
        r = self.range
        return (self.high - self.body_top) / r if r > 0 else 0.0


def _to_float(value) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    # the log writes the literal string "Calculating" during warm-up
    return out


def load_log(path: str) -> List[Bar]:
    """Read a forward_test_log.csv-schema file into Bars, in timestamp order.

    Rows with an unparsable timestamp or a missing/invalid close are skipped rather
    than fatal: the live log is written by a long-running process and has survived
    schema migrations, so a single bad row must not take the harness down.
    """
    bars: List[Bar] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            raw_ts = (row.get("Timestamp") or "").strip()
            if not raw_ts:
                continue
            try:
                ts = datetime.strptime(raw_ts, TS_FORMAT)
            except ValueError:
                continue
            o, h, l, c = (_to_float(row.get(k)) for k in ("Open", "High", "Low", "Close"))
            if None in (o, h, l, c):
                continue
            ticks = row.get("Volume")
            tick_val = int(ticks) if (ticks or "").strip().isdigit() else None
            bars.append(Bar(ts=ts, open=o, high=h, low=l, close=c, ticks=tick_val))
    bars.sort(key=lambda b: b.ts)
    return bars


def bucket_start(ts: datetime, timeframe_minutes: int) -> datetime:
    """Start of the aggregation bucket containing `ts` (UTC, anchored at midnight)."""
    if timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be > 0")
    if timeframe_minutes >= 1440:
        days = timeframe_minutes // 1440
        return datetime(ts.year, ts.month, ts.day) - timedelta(days=(ts.toordinal() % days))
    minutes = ts.hour * 60 + ts.minute
    bucket = (minutes // timeframe_minutes) * timeframe_minutes
    return datetime(ts.year, ts.month, ts.day) + timedelta(minutes=bucket)


def aggregate(bars: Sequence[Bar], timeframe_minutes: int, include_forming: bool = False) -> List[Bar]:
    """Aggregate M1 bars into `timeframe_minutes` bars.

    Returns CLOSED buckets only unless `include_forming` is set. A bucket is closed
    when a later source bar belongs to a different bucket — that is the only honest
    evidence available, and it is why the last bucket is dropped by default.

    Bars are aggregated by bucket, not by counting: a market closure produces a gap
    in the source, and counting 240 source bars would silently weld two sessions
    together across a weekend.
    """
    if timeframe_minutes <= 1:
        out = list(bars)
        return out if include_forming else out[:-1] if out else []

    buckets: "dict[datetime, List[Bar]]" = {}
    order: List[datetime] = []
    for b in bars:
        key = bucket_start(b.ts, timeframe_minutes)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(b)

    out: List[Bar] = []
    for i, key in enumerate(order):
        is_last = i == len(order) - 1
        if is_last and not include_forming:
            continue
        chunk = buckets[key]
        # bucket CLOSE time = start + timeframe, which is what a higher-TF bar stamps
        close_ts = key + timedelta(minutes=min(timeframe_minutes, 1440))
        out.append(
            Bar(
                ts=close_ts,
                open=chunk[0].open,
                high=max(b.high for b in chunk),
                low=min(b.low for b in chunk),
                close=chunk[-1].close,
                ticks=sum(b.ticks for b in chunk) if all(b.ticks is not None for b in chunk) else None,
            )
        )
    return out


def iter_closed(bars: Iterable[Bar]) -> Iterator[Bar]:
    """Alias for readability at call sites that walk a closed-bar series."""
    return iter(bars)
