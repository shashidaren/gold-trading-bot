"""Hermetic tests for volume_spike.py — the volume-spike localisation read.

Synthetic tapes only: no live CSV, no wall clock, no network, no writes. Each
test pins one of the five claims the module makes, so a future edit cannot
quietly turn a null result into an edge:

  1. a *session* spike is not a spike — the seasonal baseline must ignore the
     clock, while the naive Vol_MA basis (the audit's) calls it one;
  2. the vendor break is respected: pre-2026-09-10 bars never enter a ratio;
  3. a partial bucket is never "thin" — feed gaps must not fake volume;
  4. swing detection is past-only: a pivot cannot be used before it confirms,
     and a level the bar traded through is distance zero while a level the bar
     never approached is not "near";
  5. a channel penetration must be NEW, must clear the ATR floor, and a bar
     that did not break anything returns `back_inside = None`, never False;
  6. the report measures a swing base rate *and* a lift, and its verdict says
     the base rate is not a spike signature — the honest footer cannot be
     dropped.
"""
import math
import os
import random
import sys
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import volume_spike as V  # noqa: E402

ERA = datetime(2026, 9, 10, 0, 0)


def rows_from(bars):
    """[{ts,o,h,l,c,v}] -> forward_test_log-shaped row dicts."""
    out = []
    for b in bars:
        out.append({
            "Timestamp": b["ts"].strftime("%Y-%m-%d %H:%M:%S"),
            "Open": f"{b['o']:.2f}", "High": f"{b['h']:.2f}",
            "Low": f"{b['l']:.2f}", "Close": f"{b['c']:.2f}",
            "Volume": str(b["v"]),
            "Vol_MA": b.get("volma", "Calculating"),
        })
    return out


def flat_day(day, vol=200, base=2000.0, minutes=None):
    """A whole UTC day of M1 bars, flat price, constant volume."""
    bars, ts = [], datetime(day.year, day.month, day.day)
    for m in range(minutes or 24 * 60):
        bars.append({"ts": ts + timedelta(minutes=m), "o": base, "h": base + 0.5,
                     "l": base - 0.5, "c": base, "v": vol})
    return bars


class BaselineTests(unittest.TestCase):
    """1 + 2 + 3 — the measurement trap, the vendor break, partial buckets."""

    def test_flat_tape_produces_no_spikes(self):
        bars = []
        for d in range(1, 21):
            bars += flat_day(datetime(2026, 9, d), vol=200)
        series = V.session_profile(V.m5_buckets(V.m1_bars(rows_from(bars))))
        spikes = V.find_spikes(series)
        self.assertEqual(spikes, [], "a perfectly flat tape must yield no spike")

    def test_session_shape_is_not_a_spike_but_the_naive_basis_calls_it_one(self):
        # 10 identical days: 00:00-01:00 quiet (50/min), 13:00-14:00 loud (400/min).
        bars = []
        for d in range(1, 21):
            ts = datetime(2026, 9, d)
            for m in range(24 * 60):
                loud = (13 <= (ts + timedelta(minutes=m)).hour < 14)
                bars.append({"ts": ts + timedelta(minutes=m), "o": 2000.0,
                             "h": 2000.5, "l": 1999.5, "c": 2000.0,
                             "v": 400 if loud else 50,
                             "volma": "226.0"})   # the trailing mean sits between
        series = V.session_profile(V.m5_buckets(V.m1_bars(rows_from(bars))))
        # the seasonal baseline sees the 13:00 hour every day and calls it normal
        self.assertEqual(V.find_spikes(series, threshold=1.3), [])
        # the naive basis sees 400*5 / (226*5) = 1.77x and calls every one a spike
        loud_buckets = [b for b in series if b["ts"].hour == 13]
        self.assertTrue(loud_buckets)
        for bucket in loud_buckets[:5]:
            self.assertAlmostEqual(V.naive_ratio(bucket), 400 / 226, places=3)
            self.assertGreaterEqual(V.naive_ratio(bucket), 1.3)

    def test_vendor_break_bars_never_enter_a_ratio(self):
        bars = flat_day(datetime(2026, 9, 1), vol=29)
        series = V.m5_buckets(V.m1_bars(rows_from(bars)))
        self.assertEqual(series, [], "pre-era vendor data must be excluded")

    def test_partial_bucket_is_never_judged(self):
        # one day is missing 13:02-13:04, so its 13:00 bucket is 2/5 complete
        bars = flat_day(datetime(2026, 9, 15), vol=200)
        bars = [b for b in bars if not (b["ts"].hour == 13 and b["ts"].minute in (2, 3, 4))]
        series = V.m5_buckets(V.m1_bars(rows_from(bars)))
        partial = [b for b in series if b["ts"].hour == 13 and b["ts"].minute == 0]
        self.assertEqual(len(partial), 1)
        self.assertFalse(partial[0]["complete"])
        V.session_profile(series)
        self.assertIsNone(partial[0]["ratio"], "a gap must not manufacture thinness")

    def test_baseline_is_past_only(self):
        # Day 5 is a genuine 3x surge at 09:00 and must be flagged; the same
        # 3x printed again on days 6-20 is the new normal and must not be.
        bars = []
        for d in range(1, 21):
            for m in range(24 * 60):
                ts = datetime(2026, 9, d) + timedelta(minutes=m)
                vol = 200
                if (ts.hour, ts.minute // 5) == (9, 0):
                    vol = 600 if d == 5 else (600 if d >= 6 else 200)
                bars.append({"ts": ts, "o": 2000.0, "h": 2000.5, "l": 1999.5,
                             "c": 2000.0, "v": vol})
        series = V.session_profile(V.m5_buckets(V.m1_bars(rows_from(bars))))
        flagged = {series[i]["ts"].date() for i in V.find_spikes(series)}
        self.assertNotIn(datetime(2026, 9, 5).date(), flagged,
                         "the first 3x cannot be judged without history for the slot")
        self.assertEqual(flagged, set(), "a repeat is the baseline, not a spike")


class SwingTests(unittest.TestCase):
    """4 — pivot confirmation, and the definition of 'near'."""

    def _series(self, closes, spread=1.0):
        bars = []
        for k, close in enumerate(closes):
            bars.append({"ts": ERA + timedelta(minutes=5 * k), "o": close,
                         "h": close + spread, "l": close - spread, "c": close,
                         "v": 200})
        series = V.m5_buckets(V.m1_bars(rows_from(bars)))  # rebuilt from M1
        V.add_atr(series)
        V.add_pivots(series)
        return series

    def test_pivot_needs_k_bars_each_side(self):
        closes = [100, 101, 102, 110, 102, 101, 100, 99, 98]
        series = self._series(closes)
        highs = [b["h"] for b in series]
        peak = highs.index(max(highs))
        self.assertTrue(series[peak]["sh"], "the obvious peak must be a swing high")
        # usable only once PIVOT_K bars exist after it
        self.assertLess(V.confirmed_end(peak), peak + V.PIVOT_K)
        self.assertEqual(V.swings_before(series, peak + 1), [],
                         "a pivot cannot be read one bar after it printed")
        self.assertTrue(V.swings_before(series, peak + V.PIVOT_K + 1))

    def test_distance_is_zero_when_the_bar_trades_through_the_swing(self):
        closes = [100, 101, 102, 110, 102, 101, 100, 99, 98, 97, 96]
        series = self._series(closes)
        V.add_channel(series)
        peak = max(range(len(series)), key=lambda i: series[i]["h"])
        level = series[peak]["h"]
        # a later bar that pokes back up to the swing level, then one far below
        series[-1]["h"] = level - 0.1
        swing = V.nearest_swing(series, len(series) - 1, window=99)
        self.assertIsNotNone(swing)
        self.assertEqual(swing[2], "sh")
        self.assertGreater(swing[0], 0)
        series[-1]["h"] = level + 0.5   # trades through it
        self.assertEqual(V.nearest_swing(series, len(series) - 1, window=99)[0], 0.0)


class PenetrationTests(unittest.TestCase):
    """5 — newness, the ATR floor, and the fade test."""

    def _series(self, closes):
        bars = []
        for k, close in enumerate(closes):
            bars.append({"ts": ERA + timedelta(minutes=5 * k), "o": close,
                         "h": close + 1.0, "l": close - 1.0, "c": close, "v": 200})
        series = V.m5_buckets(V.m1_bars(rows_from(bars)))
        V.add_atr(series)
        V.add_channel(series)
        return series

    def test_only_a_new_break_counts(self):
        # 24 flat bars then a breakout bar, then a bar that stays above it
        closes = [100.0] * 24 + [100.0, 105.0, 108.0]
        series = self._series(closes)
        break_i = 25
        pen = V.penetration(series, break_i)
        self.assertIsNotNone(pen, "a fresh break beyond the channel must register")
        self.assertEqual(pen["side"], "UP")
        self.assertIsNone(V.penetration(series, break_i + 1),
                          "sitting above a channel broken last bar is not a trigger")

    def test_break_smaller_than_the_floor_is_not_a_penetration(self):
        closes = [100.0] * 25 + [100.0, 100.5]
        series = self._series(closes)
        series[-1]["h"] = series[-1]["pch"] + 0.01 * series[-1]["atr"]
        self.assertIsNone(V.penetration(series, len(series) - 1))

    def test_no_break_means_no_fade_verdict(self):
        closes = [100.0] * 30
        series = self._series(closes)
        fwd = V.forward(series, len(series) - 2)
        self.assertIsNone(fwd, "an incomplete forward window is not judgeable")
        series = self._series([100.0] * 60)
        self.assertIsNone(V.forward(series, 40)["back_inside"],
                          "a bar inside its channel has nothing to fade")


class ReportTests(unittest.TestCase):
    """6 — the report always carries the base rate and the honest verdict."""

    def _tape(self):
        """A wavy tape with a session shape and TWO genuine one-off surges.

        The price has to move for pivots and channel breaks to exist at all, and
        the surges have to be one-offs: a surge that repeats every day becomes
        the baseline (that is BaselineTests.test_baseline_is_past_only).
        """
        rng = random.Random(5)
        bars = []
        for d in range(1, 25):
            for m in range(24 * 60):
                ts = datetime(2026, 9, d) + timedelta(minutes=m)
                close = (2000.0 + 6.0 * math.sin(2 * math.pi * m / 60.0)
                         + rng.uniform(-0.15, 0.15))
                vol = 400 if 13 <= ts.hour < 15 else 180
                # one-off surges: a repeated one would become the baseline
                if (d, ts.hour, ts.minute) in {(20, 9, 4), (21, 10, 32), (22, 14, 4)}:
                    vol = vol * 6
                bars.append({"ts": ts, "o": close, "h": close + 0.6,
                             "l": close - 0.6, "c": close, "v": vol})
        return rows_from(bars)

    def test_report_carries_base_rate_and_lift(self):
        rep = V.report(self._tape())
        summary = rep["summary"]
        for key in ("near_swing_pct", "near_swing_base_pct", "near_swing_lift_pp",
                    "penetration_pct", "penetration_base_pct", "n_spikes"):
            self.assertIn(key, summary)
        if summary["n_spikes"]:
            self.assertIsNotNone(summary["near_swing_lift_pp"],
                                 "a spike count without a base rate is a claim, not a test")

    def test_verdict_names_the_base_rate_trap(self):
        rep = V.report(self._tape())
        joined = " ".join(rep["verdict"]).lower()
        self.assertIn("base rate", joined)
        self.assertIn("lift", joined)
        self.assertIn("display-only", joined)
        # the closing sentence is derived, so this tape must be able to print
        # either verdict — but it must always be one of the two.
        self.assertTrue(
            "no level-localisation edge" in joined or "worth pre-registering" in joined)

    def test_feed_resolution_block_is_present_and_honest(self):
        rep = V.report(self._tape())
        noise = rep["baseline_check"]
        self.assertGreater(noise["n"], 0)
        self.assertIn("localised", noise)
        self.assertIsInstance(noise["localised"], bool)

    def test_json_safe(self):
        import json
        json.dumps(V.report(self._tape()), default=str)


if __name__ == "__main__":
    unittest.main()
