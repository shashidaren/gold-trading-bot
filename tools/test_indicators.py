"""Hermetic tests for indicators.py (candidate indicators, no engine dependency).

Synthetic tapes only — no live CSVs, no wall clock. The property that matters
most is CAUSALITY: a value at bar i must not change when future bars are
appended. The rest pin the textbook definitions to small cases whose answers
can be checked by hand.

Run: python3 tools/test_indicators.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import indicators as I  # noqa: E402


def bars_from_closes(closes, spread=1.0, volume=10):
    """A bar per close: open = prior close, high/low = body ± spread."""
    rows = []
    prev = closes[0]
    for k, c in enumerate(closes):
        o = prev
        rows.append({
            "Timestamp": f"2026-10-23 {6 + k // 60:02d}:{k % 60:02d}:00",
            "Open": f"{o}", "High": f"{max(o, c) + spread}", "Low": f"{min(o, c) - spread}",
            "Close": f"{c}", "Volume": str(volume),
        })
        prev = c
    return rows


def series_from_closes(closes, spread=1.0, volume=10):
    return I.build(I.bars_from_rows(bars_from_closes(closes, spread, volume)))


class Primitives(unittest.TestCase):
    def test_sma_waits_for_a_full_window_and_handles_gaps(self):
        self.assertEqual(I.sma([1, 2, 3, 4], 3), [None, None, 2.0, 3.0])
        self.assertEqual(I.sma([1, None, 3], 2), [None, None, None])

    def test_ema_of_a_constant_is_the_constant(self):
        out = I.ema([5.0] * 30, 10)
        self.assertIsNone(out[8])
        self.assertAlmostEqual(out[9], 5.0)
        self.assertAlmostEqual(out[-1], 5.0)

    def test_rsis(self):
        rising = I.rsi_sma(list(range(1, 40)), 14)
        self.assertAlmostEqual(rising[-1], 100.0)          # no losses
        wilder = I.rsi_wilder(list(range(1, 40)), 14)
        self.assertAlmostEqual(wilder[-1], 100.0)
        flat = I.rsi_wilder([10.0] * 40, 14)
        self.assertAlmostEqual(flat[-1], 100.0)            # 0/0 -> 100 by convention

    def test_atr_of_constant_bars_is_the_bar_range(self):
        closes = [100.0] * 40
        rows = bars_from_closes(closes, spread=1.0)
        b = I.bars_from_rows(rows)
        atr = I.atr_sma([x["h"] for x in b], [x["l"] for x in b], [x["c"] for x in b], 14)
        # high-low = 2, no gaps -> TR = 2 everywhere
        self.assertAlmostEqual(atr[20], 2.0)

    def test_rolling_extremes_are_trailing_and_not_leading(self):
        self.assertEqual(I._rolling_max([1, 2, 3, 4, 5], 3), [None, None, 3, 4, 5])
        self.assertEqual(I._rolling_min([1, 2, 3, 4, 5], 3), [None, None, 1, 2, 3])


class TextbookShapes(unittest.TestCase):
    def test_uptrend_reads_as_uptrend(self):
        s = series_from_closes([4000.0 + 0.5 * k for k in range(240)])
        snap = I.at(s, 239)
        self.assertGreater(snap["adx"], 20)
        self.assertGreater(snap["plus_di"], snap["minus_di"])
        self.assertEqual(snap["di_side"], "BUY")
        self.assertGreater(snap["macd"], 0)
        self.assertGreater(snap["keltner_pos"], 0)
        self.assertGreater(snap["donchian_pos"], 0.5)
        self.assertGreater(snap["er30"], 0.9)
        self.assertGreater(snap["stoch_k"], 80.0)
        self.assertGreaterEqual(snap["rsi_slope"], 0)

    def test_downtrend_reads_as_downtrend(self):
        s = series_from_closes([4200.0 - 0.5 * k for k in range(240)])
        snap = I.at(s, 239)
        self.assertLess(snap["plus_di"], snap["minus_di"])
        self.assertEqual(snap["di_side"], "SELL")
        self.assertLess(snap["macd"], 0)
        self.assertLess(snap["keltner_pos"], 0)
        self.assertLess(snap["donchian_pos"], 0.5)
        self.assertLess(snap["stoch_k"], 20.0)

    def test_flat_tape_has_no_division_by_zero(self):
        s = series_from_closes([4000.0] * 60, spread=0.0)
        snap = I.at(s, 59)
        self.assertIsNone(snap["stoch_k"])                # zero range: refuse
        self.assertIsNone(snap["er30"])                   # no travel: refuse
        self.assertIsNone(snap["bb_pct_b"])               # zero-width bands: refuse
        self.assertIsNone(snap["donchian_pos"])
        self.assertEqual(snap["rvol"], 1.0)

    def test_bollinger_stays_inside_its_own_band(self):
        closes = [4000.0 + (5.0 if k % 2 else -5.0) for k in range(120)]
        s = series_from_closes(closes)
        snap = I.at(s, 119)
        self.assertIsNotNone(snap["bb_pct_b"])
        self.assertGreaterEqual(snap["bb_pct_b"], 0.0)
        self.assertLessEqual(snap["bb_pct_b"], 1.0)
        self.assertGreater(snap["bb_bandwidth"], 0.0)

    def test_efficiency_ratio_distinguishes_straight_from_zigzag(self):
        straight = I.efficiency_ratio([100.0 + k for k in range(60)], 30)
        self.assertAlmostEqual(straight[-1], 1.0)
        zig = I.efficiency_ratio([100.0 + (1.0 if k % 2 else -1.0) for k in range(60)], 30)
        self.assertLess(zig[-1], 0.2)

    def test_atr_percentile_and_rvol_are_bounded(self):
        s = series_from_closes([4000.0 + (k % 7) for k in range(500)])
        snap = I.at(s, 499)
        self.assertGreaterEqual(snap["atr_pct"], 0.0)
        self.assertLessEqual(snap["atr_pct"], 100.0)
        self.assertAlmostEqual(snap["rvol"], 1.0)


class Causality(unittest.TestCase):
    def test_future_bars_never_change_a_past_snapshot(self):
        closes = [4000.0 + 0.3 * k + (2.0 if k % 11 == 0 else 0.0) for k in range(320)]
        s1 = series_from_closes(closes[:260])
        before = I.at(s1, 250)
        s2 = series_from_closes(closes)
        after = I.at(s2, 250)
        for key in before:
            a, b = before[key], after[key]
            if isinstance(a, float) and isinstance(b, float):
                self.assertAlmostEqual(a, b, places=9, msg=key)
            else:
                self.assertEqual(a, b, msg=key)

    def test_at_refuses_out_of_range(self):
        s = series_from_closes([4000.0] * 40)
        self.assertIsNone(I.at(s, -1))
        self.assertIsNone(I.at(s, 40))
        self.assertIsNone(I.at(None, 0))


class Splits(unittest.TestCase):
    def test_fixed_splits_are_not_fitted(self):
        self.assertEqual(I.split_value("adx", [1, 2, 3]), 20.0)
        self.assertEqual(I.split_value("macd_hist", [1, 2, 3]), 0.0)
        self.assertEqual(I.split_value("er30", [1, 2, 3]), 0.3)

    def test_median_split_is_the_sample_median(self):
        self.assertEqual(I.split_value("bb_bandwidth", [1, 3, 5, 7]), 4.0)
        self.assertEqual(I.split_value("bb_bandwidth", [1, 2, 10]), 2)

    def test_every_context_field_has_a_description(self):
        for key in I.CONTEXT_FIELDS:
            self.assertIn(key, I.DESCRIPTIONS, key)


class EngineParity(unittest.TestCase):
    def test_parity_reports_counts_without_raising(self):
        rows = bars_from_closes([4000.0 + 0.1 * k for k in range(320)])
        s = I.build(I.bars_from_rows(rows))
        par = I.engine_parity(s, step=50)
        for key in ("atr", "rsi", "ema50", "ema200"):
            self.assertIn(key, par)
            self.assertGreaterEqual(par[key]["n"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
