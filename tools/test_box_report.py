"""Hermetic tests for tools/box_report.py.

Synthetic tapes only — no live CSVs, no wall clock. Pins the two things that
could silently lie: the box must never include the bar being judged, and the
measurement must be sequential (one position at a time), censored at the end
of the tape, and must refuse to call a losing cell an edge.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import box_report as B  # noqa: E402

T0 = datetime(2026, 10, 7, 0, 0)          # after the struct-stop cutover


def bar(minute, o, h, l, c, atr=0.1):
    ts = T0 + timedelta(minutes=minute)
    return {"Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "Open": str(o), "High": str(h), "Low": str(l), "Close": str(c),
            "ATR": str(atr), "EMA_50": "100", "EMA_200": "99", "Volume": "10"}


def flat(minute, price=100.0, n=1, atr=0.1):
    return [bar(minute + k, price, price + 0.2, price - 0.2, price, atr) for k in range(n)]


class BoxLookup(unittest.TestCase):
    def test_box_is_taken_from_bars_before_the_judged_bar(self):
        rows = flat(0, n=25)
        # the judged bar is far outside the box; it must not leak into it
        rows.append(bar(25, 100.0, 420.0, 99.0, 410.0))
        bars = B.tape(rows)
        start = B.run_offsets(bars)
        hi, lo = B.box_at(bars, 25, 20, start)
        self.assertAlmostEqual(hi, 100.2)
        self.assertAlmostEqual(lo, 99.8)

    def test_box_needs_contiguous_prior_bars(self):
        rows = flat(0, n=25)                       # session 1
        rows += flat(600, n=25)                    # session 2, after a 9 h gap
        bars = B.tape(rows)
        start = B.run_offsets(bars)
        self.assertIsNotNone(B.box_at(bars, 24, 20, start))
        self.assertIsNone(B.box_at(bars, 30, 20, start))   # only 5 bars into run 2

    def test_forward_end_stops_at_a_gap(self):
        rows = flat(0, n=10) + flat(300, n=10)
        bars = B.tape(rows)
        self.assertEqual(B.forward_end(bars, 3, 120), 9)


class Measurement(unittest.TestCase):
    def tape_with_breakout(self, then_up=True, atr=0.1):
        """30 flat bars, a close above the box, then a run to the target."""
        rows = flat(0, n=30, atr=atr)
        rows.append(bar(30, 100.0, 100.6, 100.0, 100.5, atr))     # break: c > 100.2
        if then_up:
            for k, (h, l, c) in enumerate([(100.8, 100.4, 100.7),
                                           (101.2, 100.6, 101.0),
                                           (101.4, 101.0, 101.2)]):
                rows.append(bar(31 + k, 100.7, h, l, c, atr))
        else:
            for k in range(3):
                rows.append(bar(31 + k, 100.4, 100.5, 99.9, 100.0, atr))
        return B.tape(rows)

    def test_breakout_that_reaches_target_first_wins(self):
        bars = self.tape_with_breakout()
        # entry 100.5, near edge 100.2 -> risk = max(0.2, 0.3+0.05) = 0.35
        out = B._race(bars, 30, 50, 1, 100.5, 0.35, 0.525)
        self.assertEqual(out, "w")

    def test_bar_spanning_both_counts_as_a_stop(self):
        rows = flat(0, n=30)
        rows.append(bar(30, 100.0, 100.6, 100.0, 100.5))
        rows.append(bar(31, 100.5, 102.0, 99.0, 100.5))   # spans target and stop
        out = B._race(B.tape(rows), 30, 40, 1, 100.5, 0.35, 0.525)
        self.assertEqual(out, "l")

    def test_false_break_flagged_when_close_returns_inside(self):
        bars = self.tape_with_breakout(then_up=False)
        scan = B.scan(bars, 20, 60, 0.55)
        self.assertEqual(scan["breaks"], 1)
        self.assertEqual(scan["false_break_pct"], 100.0)

    def test_sequential_sampling_does_not_stack_overlapping_events(self):
        """Price re-breaks the same box every few bars; only one position is opened."""
        rows = flat(0, n=30)
        for k in range(12):
            rows.append(bar(30 + 2 * k, 100.0, 100.6, 99.9, 100.5 if k % 2 == 0 else 100.0))
            rows.append(bar(31 + 2 * k, 100.0, 100.4, 99.8, 100.0))
        scan = B.scan(B.tape(rows), 20, 60, 0.55)
        self.assertEqual(scan["breaks"], 1)

    def test_tape_end_is_censored_not_counted(self):
        rows = flat(0, n=30)
        rows.append(bar(30, 100.0, 100.6, 100.0, 100.5))   # break on the last bar
        scan = B.scan(B.tape(rows), 20, 60, 0.55)
        self.assertEqual(scan["breaks"], 0)

    def test_losing_cell_is_never_called_an_edge(self):
        # 1:1 geometry, 53% wins on n=2000: the Wilson lower bound clears the
        # 50% reference, and the cell still loses money because $0.55 of cost on
        # a $1 risk is half an R. Clearing the reference is not an edge.
        rows = ([{"outcome": "w", "risk": 1.0, "target": 1.0}] * 1060 +
                [{"outcome": "l", "risk": 1.0, "target": 1.0}] * 940)
        cell = B._cell(rows, 0.55)
        self.assertGreater(cell["ci"][0], cell["ref_pct"])
        self.assertLess(cell["expectancy_usd"], 0)
        self.assertEqual(cell["verdict"], "no edge (cost eats it)")

    def test_cell_counts_open_windows_separately(self):
        rows = [{"outcome": "w", "risk": 1.0, "target": 1.5},
                {"outcome": None, "risk": 1.0, "target": 1.5}]
        cell = B._cell(rows, 0.55)
        self.assertEqual((cell["n"], cell["open"]), (1, 1))


class LiveRead(unittest.TestCase):
    def test_prior_day_ignores_a_partial_day(self):
        rows = flat(0, n=700)                       # day 1
        rows += flat(1440, n=700)                   # day 2
        rows += flat(2880, n=100)                   # day 3, still trading
        live = B.live_boxes(rows, 0.55)
        names = [b["name"] for b in live["boxes"]]
        self.assertTrue(any("day" in n for n in names))
        self.assertFalse(any("1970-01-01" in n for n in names))

    def test_boxes_carry_structural_risk_and_cost_share(self):
        live = B.live_boxes(flat(0, n=60), 0.55)
        box = live["boxes"][0]
        self.assertGreater(box["buy_structural_risk_usd"], 0)
        self.assertAlmostEqual(box["buy_tp_usd"], 1.5 * box["buy_structural_risk_usd"], delta=0.02)
        self.assertGreater(box["sell_cost_share_pct"], 0)


class ReadOnly(unittest.TestCase):
    def test_tool_does_not_import_the_engine(self):
        # AST, not text: the docstring may name engine.py/trade_filter.py to
        # explain what this tool deliberately does NOT touch.
        import ast
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "box_report.py")
        with open(path) as fh:
            tree = ast.parse(fh.read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        self.assertNotIn("engine", mods)
        self.assertNotIn("trade_filter", mods)
        self.assertLessEqual(mods, {"argparse", "json", "os", "sys", "datetime", "pressure"})

    def test_tool_never_writes(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "box_report.py")) as fh:
            src = fh.read()
        for bad in ("open(", "write(", "os.remove", "shutil"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
