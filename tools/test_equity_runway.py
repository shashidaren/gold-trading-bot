#!/usr/bin/env python3
"""
Hermetic tests for tools/equity_runway.py — synthetic ledgers only, no live data.

    python3 tools/test_equity_runway.py          # or: python3 -m unittest tools.test_equity_runway

What is pinned here, and why each one matters:
  * true equity is 500 + summed P&L, and the ledger drift is reported separately
    (the two numbers owners quote differ by that drift; conflating them is how the
    2026-09-09 "reported equity is wrong" incident stayed hidden for five days);
  * risk is recovered from the reward leg (|TP - Entry| / 1.5) on rows whose stop
    was ratcheted to entry - risk must never come out as 0 on a BE row;
  * the runway is arithmetic on the era's net $-per-trade, and it is None rather
    than a divide-by-zero when the book is flat or the ledger is already spent;
  * the rebaseline policy fires at exactly true equity <= 0 and at nothing else
    (a floor that fires early would let a bar be rescued before the outcome);
  * malformed rows with no Entry_Time are skipped, not crashed on;
  * the tool never writes: the temp root's file bytes and mtimes are unchanged.
"""
import csv
import json
import os
import shutil
import tempfile
import unittest

import equity_runway as er

HEADER = ["Trade_Num", "Trade_Type", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss",
          "Take_Profit", "Exit_Price", "Exit_Reason", "Profit", "Balance_After",
          "RSI_At_Entry", "ATR_At_Entry", "Wick_Ratio_At_Entry", "EMA50_At_Entry",
          "EMA200_At_Entry"]


def row(num, side, et, entry, sl, tp, exit_p, reason, profit, bal, atr=2.0):
    return dict(zip(HEADER, [num, side, et, et, f"{entry:.2f}", f"{sl:.2f}", f"{tp:.2f}",
                             f"{exit_p:.2f}", reason, f"{profit:.2f}", f"{bal:.2f}",
                             "50.0", f"{atr:.2f}", "50.0%", f"{entry:.2f}", f"{entry:.2f}"]))


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="runway-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rows, status=None):
        with open(os.path.join(self.root, "trades.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        if status is not None:
            with open(os.path.join(self.root, "status.json"), "w") as f:
                json.dump(status, f)

    def status(self, **kw):
        base = {"equity": 500.0, "total_trades": 0, "trade_active": False,
                "current_trade_num": 0}
        base.update(kw)
        return base


class TestRiskRecovery(Base):
    def test_reward_leg(self):
        r = {"Entry_Price": "4000.00", "Take_Profit": "4030.00", "ATR_At_Entry": "2.00"}
        self.assertAlmostEqual(er.risk_of(r), 20.0)          # 30 / 1.5

    def test_ratcheted_stop_is_not_zero_risk(self):
        """A BE row logs Stop_Loss == Entry; risk must come from TP, never from |E-S|."""
        r = {"Entry_Price": "4000.00", "Stop_Loss": "4000.00",
             "Take_Profit": "4015.00", "ATR_At_Entry": "2.00"}
        self.assertAlmostEqual(er.risk_of(r), 10.0)
        self.assertGreater(er.risk_of(r), 0)

    def test_short_side(self):
        r = {"Entry_Price": "4000.00", "Take_Profit": "3970.00", "ATR_At_Entry": "2.00"}
        self.assertAlmostEqual(er.risk_of(r), 20.0)

    def test_falls_back_to_atr_when_no_tp(self):
        r = {"Entry_Price": "4000.00", "Take_Profit": "0", "ATR_At_Entry": "3.00"}
        self.assertAlmostEqual(er.risk_of(r), 6.0)           # 2 x ATR

    def test_garbage_is_none(self):
        self.assertIsNone(er.risk_of({"Entry_Price": "", "Take_Profit": "", "ATR_At_Entry": ""}))


class TestAccounting(Base):
    def test_true_equity_uses_pnl_sum_not_ledger(self):
        """Ledger says $490 (a reset drifted it); true equity must be 500 + P&L."""
        self.write([row(1, "BUY", "2026-10-07 00:00:00", 4000, 3990, 4015, 3990, "SL", -10, 490)],
                   self.status(equity=490.0, total_trades=1))
        d = er.build(self.root, 0.20)
        self.assertAlmostEqual(d["true_equity"], 490.0)
        self.assertAlmostEqual(d["drift"], 0.0)              # ledger == true here

    def test_drift_is_reported(self):
        self.write([row(1, "BUY", "2026-10-07 00:00:00", 4000, 3990, 4015, 3990, "SL", -10, 505)],
                   self.status(equity=505.0, total_trades=1))
        d = er.build(self.root, 0.20)
        self.assertAlmostEqual(d["true_equity"], 490.0)
        self.assertAlmostEqual(d["drift"], 15.0)             # 505 - 490

    def test_rows_without_entry_time_are_skipped(self):
        bad = row(2, "BUY", "", 0, 0, 0, 0, "TP", -4000, 90)
        self.write([row(1, "BUY", "2026-10-07 00:00:00", 4000, 3990, 4015, 4015, "TP", 15, 515),
                    bad], self.status(equity=515.0, total_trades=1))
        d = er.build(self.root, 0.20)
        self.assertEqual(d["closed"], 1)
        self.assertAlmostEqual(d["true_equity"], 515.0)

    def test_open_trade_is_reported(self):
        self.write([row(1, "BUY", "2026-10-07 00:00:00", 4000, 3990, 4015, 4015, "TP", 15, 515)],
                   self.status(equity=515.0, trade_active=True, trade_type="SELL",
                               current_trade_num=2))
        self.assertEqual(er.build(self.root, 0.20)["open_trade"], "SELL #2")


class TestRunway(Base):
    def era_rows(self, n=10, profit=-1.0):
        """n losing era trades, risk exactly $10 each (TP 15 away / 1.5)."""
        bal = 500.0
        rows = []
        for i in range(n):
            bal += profit
            rows.append(row(i + 1, "BUY", "2026-10-07 00:00:00", 4000, 3990, 4015,
                            3990, "SL", profit, bal))
        return rows

    def test_runway_arithmetic(self):
        rows = self.era_rows(10, -1.0)                       # -0.10R gross, 1R = $10
        self.write(rows, self.status(equity=490.0, total_trades=10))
        # gross -0.10R/t; the $0.40 round trip is 0.04R at 1R = $10, so net is -0.14R/t
        # = -$1.40/trade. 490/1.4 = 350 trades left, at 10 trades/active day = 35 days.
        d = er.build(self.root, 0.20)
        self.assertAlmostEqual(d["era"]["net_r_per_trade"], -0.14, places=6)
        self.assertAlmostEqual(d["runway"]["usd_per_trade"], -1.40, places=6)
        self.assertAlmostEqual(d["runway"]["trades"], 350.0, places=6)
        self.assertAlmostEqual(d["runway"]["trading_days"], 35.0, places=6)

    def test_no_runway_when_flat(self):
        rows = self.era_rows(4, 0.0)                         # every trade a scratch
        self.write(rows, self.status(equity=500.0, total_trades=4))
        d = er.build(self.root, 0.20)
        self.assertIsNone(d["runway"]["trades"])             # no burn to extrapolate

    def test_spent_ledger_has_no_runway(self):
        rows = self.era_rows(10, -60.0)                      # classic overdraw
        self.write(rows, self.status(equity=-100.0, total_trades=10))
        d = er.build(self.root, 0.20)
        self.assertIsNone(d["runway"]["trades"])
        self.assertTrue(d["policy"]["fired"])

    def test_bootstrap_range_brackets_point_estimate(self):
        rows = self.era_rows(40, -1.0)
        self.write(rows, self.status(equity=460.0, total_trades=40))
        r = er.build(self.root, 0.20)["runway"]
        self.assertLessEqual(r["trades_p05"], r["trades_p95"])
        self.assertIsNotNone(r["p_no_burn"])


class TestPolicy(Base):
    def _d(self, balance, profit=-1.0):
        self.write([row(1, "BUY", "2026-10-07 00:00:00", 4000, 3990, 4015, 3990, "SL",
                        profit, balance)], self.status(equity=balance, total_trades=1))
        return er.build(self.root, 0.20)

    def test_does_not_fire_with_money_left(self):
        d = self._d(51.0, -449.0)                            # true equity $51
        self.assertFalse(d["policy"]["fired"])
        self.assertAlmostEqual(d["policy"]["to_go_usd"], 51.0)

    def test_fires_at_exactly_zero(self):
        d = self._d(0.0, -500.0)
        self.assertTrue(d["policy"]["fired"])
        self.assertAlmostEqual(d["policy"]["to_go_usd"], 0.0)

    def test_fires_below_zero(self):
        self.assertTrue(self._d(-40.0, -540.0)["policy"]["fired"])

    def test_rebase_target_is_the_start_balance(self):
        self.assertEqual(self._d(-40.0, -540.0)["policy"]["rebase_to_usd"], 500.0)


class TestNoSideEffects(Base):
    def test_reads_only(self):
        self.write([row(1, "BUY", "2026-10-07 00:00:00", 4000, 3990, 4015, 4015, "TP", 15, 515)],
                   self.status(equity=515.0, total_trades=1))
        before = {}
        for name in ("trades.csv", "status.json"):
            p = os.path.join(self.root, name)
            st = os.stat(p)
            with open(p, "rb") as f:
                before[name] = (f.read(), st.st_mtime, st.st_size)
        er.build(self.root, 0.20)
        er.build(self.root, 0.275)
        after = sorted(os.listdir(self.root))
        self.assertEqual(after, ["status.json", "trades.csv"])
        for name, (blob, mt, size) in before.items():
            p = os.path.join(self.root, name)
            st = os.stat(p)
            with open(p, "rb") as f:
                self.assertEqual(f.read(), blob)
            self.assertEqual((st.st_mtime, st.st_size), (mt, size))


if __name__ == "__main__":
    unittest.main(verbosity=2)
