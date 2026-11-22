#!/usr/bin/env python3
"""Hermetic tests for tools/feed_forensics.py.

The failure mode this tool exists to prevent is a review quietly re-reading the
P&L of a trade that was open while the data was missing. So the assertions are:

  * a scheduled closure is NOT reported as an outage (both feeds silent is normal
    after 20:55 UTC and at the weekend);
  * a hole where a position was open is flagged EXPOSED, and one where it was not
    is not;
  * the four kinds are separated by the OTHER feed's evidence, not by a clock guess;
  * a period before either feed existed is reported as a COVERAGE gap, not an
    outage — the difference between "we lost data" and "we had not started yet";
  * the tool never writes and never imports the engine.

Run: python3 tools/test_feed_forensics.py
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import feed_forensics as FF  # noqa: E402


def series(start, minutes, step=1):
    return [start + timedelta(minutes=i * step) for i in range(minutes)]


class ExpectedOpenTests(unittest.TestCase):
    def test_the_daily_break_and_the_weekend_are_not_expected_open(self):
        # 2026-11-04 is a Wednesday; the repo's closure rule pads the break to 20:55-23:10
        self.assertTrue(FF.expected_open(datetime(2026, 11, 4, 12, 0)))
        self.assertFalse(FF.expected_open(datetime(2026, 11, 4, 21, 30)))
        self.assertFalse(FF.expected_open(datetime(2026, 11, 4, 22, 30)))
        # Saturday and Sunday daytime are shut; Sunday 23:30 is open again
        self.assertFalse(FF.expected_open(datetime(2026, 11, 7, 12, 0)))
        self.assertFalse(FF.expected_open(datetime(2026, 11, 8, 12, 0)))
        self.assertTrue(FF.expected_open(datetime(2026, 11, 8, 23, 30)))
        # Friday after the padded close is shut
        self.assertFalse(FF.expected_open(datetime(2026, 11, 6, 21, 30)))

    def test_expected_open_is_the_repo_rule_not_a_second_table(self):
        import xm_quote_report as QR
        for h in (0, 3, 12, 20, 21, 22, 23):
            for day in (2, 3, 6, 8):
                m = datetime(2026, 11, day, h, 30)
                self.assertEqual(FF.expected_open(m),
                                 not QR.in_closed_window(m.replace(tzinfo=FF.UTC).timestamp()), m)


class HoleDetectionTests(unittest.TestCase):
    def _analyse(self, bar_ts, quote_ts, trades=(), now=None, days=3):
        """Drive `analyse` on synthetic feeds instead of the repo's CSVs."""
        import xm_quote_report as QR
        now = now or datetime(2026, 11, 4, 20, 0)
        d = tempfile.mkdtemp()
        # a minimal xm_data dir: one file whose rows are all fresh usable samples
        qdir = os.path.join(d, "xm_data")
        os.makedirs(qdir)
        with open(os.path.join(qdir, "quotes-2026-11-04.csv"), "w") as fh:
            fh.write("ts_utc,bid,ask,spread,spread_min,spread_max,n_ok,n_bad,"
                     "tick_age_s,srv_offset_s,flags\n")
            for t in quote_ts:
                fh.write(f"{t:%Y-%m-%d %H:%M:%S},4000.00,4000.55,0.55,0.55,0.55,"
                         f"6,0,1.0,7200,\n")
        with open(os.path.join(d, "forward_test_log.csv"), "w") as fh:
            fh.write("Timestamp,Open,High,Low,Close\n")
            for t in bar_ts:
                fh.write(f"{t:%Y-%m-%d %H:%M:%S},4000,4001,3999,4000\n")
        with open(os.path.join(d, "trades.csv"), "w") as fh:
            fh.write("Trade_Num,Trade_Type,Entry_Time,Exit_Time,Entry_Price,Stop_Loss,"
                     "Take_Profit,Exit_Price,Exit_Reason,Profit,Balance_After,"
                     "RSI_At_Entry,ATR_At_Entry,Wick_Ratio_At_Entry\n")
            for n, (et, xt) in enumerate(trades, 1):
                fh.write(f"{n},BUY,{et:%Y-%m-%d %H:%M:%S},{xt:%Y-%m-%d %H:%M:%S},"
                         f"4000,3998,4003,4003,TP,3.00,503.0,50,2.0,50%\n")
        try:
            return FF.analyse(d, qdir=qdir, days=days, now=now)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_a_shared_hole_in_an_open_session_is_both_feeds_down(self):
        start = datetime(2026, 11, 4, 8, 0)
        bars = series(start, 240) + series(datetime(2026, 11, 4, 13, 0), 60)
        quotes = series(start, 240) + series(datetime(2026, 11, 4, 13, 0), 60)
        res = self._analyse(bars, quotes, now=datetime(2026, 11, 4, 14, 30))
        self.assertEqual(len(res["holes"]), 1, res["holes"])
        hole = res["holes"][0]
        self.assertEqual(hole["kind"], "BOTH FEEDS DOWN")
        # the hole is 12:00-13:00; the +-2 min coverage tolerance trims a minute each side
        self.assertGreaterEqual(hole["open_min"], 50)

    def test_a_bar_only_hole_is_a_price_feed_problem(self):
        start = datetime(2026, 11, 4, 8, 0)
        bars = series(start, 60) + series(datetime(2026, 11, 4, 12, 0), 60)
        quotes = series(start, 300)
        res = self._analyse(bars, quotes, now=datetime(2026, 11, 4, 13, 30))
        self.assertEqual([h["kind"] for h in res["holes"]], ["PRICE-FEED ONLY"])

    def test_a_quote_only_hole_is_a_logger_problem(self):
        start = datetime(2026, 11, 4, 8, 0)
        bars = series(start, 300)
        quotes = series(start, 60) + series(datetime(2026, 11, 4, 12, 0), 60)
        res = self._analyse(bars, quotes, now=datetime(2026, 11, 4, 13, 30))
        self.assertEqual([h["kind"] for h in res["holes"]], ["QUOTE-FEED ONLY"])

    def test_a_scheduled_daily_break_is_not_reported(self):
        # feeds alive all afternoon, silent through the 20:55-23:10 break, alive after
        bars = series(datetime(2026, 11, 4, 12, 0), 536) + series(
            datetime(2026, 11, 4, 23, 15), 40)     # 536 min ends at 20:55 exactly
        quotes = list(bars)
        res = self._analyse(bars, quotes, now=datetime(2026, 11, 5, 0, 0))
        self.assertEqual(res["holes"], [])

    def test_a_short_blip_is_below_the_reporting_threshold(self):
        start = datetime(2026, 11, 4, 8, 0)
        bars = series(start, 30) + series(datetime(2026, 11, 4, 8, 33), 60)
        quotes = series(start, 90)
        res = self._analyse(bars, quotes, now=datetime(2026, 11, 4, 9, 30))
        self.assertEqual(res["holes"], [])            # 3 minutes < HOLE_MIN

    def test_a_trade_open_across_the_hole_is_flagged_exposed(self):
        start = datetime(2026, 11, 4, 8, 0)
        bars = series(start, 240) + series(datetime(2026, 11, 4, 13, 0), 60)
        quotes = list(bars)
        exposed = (datetime(2026, 11, 4, 11, 30), datetime(2026, 11, 4, 12, 30))
        clear = (datetime(2026, 11, 4, 8, 0), datetime(2026, 11, 4, 8, 30))
        res = self._analyse(bars, quotes, trades=[exposed, clear],
                            now=datetime(2026, 11, 4, 14, 30))
        self.assertEqual(len(res["holes"]), 1, res["holes"])
        hole = res["holes"][0]
        self.assertEqual([t["num"] for t in hole["trades"]], [1])
        self.assertEqual(len(res["summary"]["exposed"]), 1)

    def test_a_hole_with_no_exposure_is_reported_as_an_ops_note(self):
        start = datetime(2026, 11, 4, 8, 0)
        bars = series(start, 240) + series(datetime(2026, 11, 4, 13, 0), 60)
        res = self._analyse(bars, list(bars), now=datetime(2026, 11, 4, 14, 30))
        self.assertEqual(len(res["holes"]), 1)
        self.assertEqual(res["summary"]["exposed"], [])
        self.assertIn("no position was open", FF.render(res))

    def test_absence_before_either_feed_existed_is_a_coverage_gap(self):
        # bars start a week before quotes; that week must not be called an outage
        bars = series(datetime(2026, 10, 26, 9, 0), 60) + series(
            datetime(2026, 11, 4, 9, 0), 120)
        quotes = series(datetime(2026, 11, 4, 9, 0), 120)
        res = self._analyse(bars, quotes, now=datetime(2026, 11, 4, 12, 0), days=10)
        self.assertTrue(res["clamped"])
        self.assertEqual(res["judged_since"][:10], "2026-11-04")
        self.assertEqual(res["holes"], [])
        self.assertIn("COVERAGE gap", FF.render(res))


class SafetyTests(unittest.TestCase):
    def test_never_imports_the_engine_and_never_writes(self):
        with open(os.path.join(HERE, "feed_forensics.py"), encoding="utf-8") as fh:
            src = fh.read()
        body = src.split('"""')[2]
        self.assertNotIn("import engine", body)
        for banned in (".write(", "makedirs", "os.remove(", "os.rename("):
            self.assertNotIn(banned, body, banned)

    def test_reuses_the_repos_definitions_instead_of_copying_numbers(self):
        with open(os.path.join(HERE, "feed_forensics.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("QR.usable", src)                 # one definition of a fresh quote
        self.assertIn("QR.in_closed_window", src)       # one definition of a closure
        self.assertIn("L.load_ledger", src)             # one ledger parser

    def test_cli_returns_zero_on_the_real_repo(self):
        self.assertEqual(FF.main(["--root", ROOT, "--days", "20"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
