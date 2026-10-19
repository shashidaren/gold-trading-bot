"""Hermetic tests for the signal-outlook read layer (pressure.signal_outlook).

Synthetic tapes only: direction signs, reward-leg risk, censoring, the
barrier race and the applied cone. No live CSVs, no wall clock.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pressure as P

T0 = datetime(2026, 10, 7, 0, 0)          # after the struct-stop cutover


def bar(minute, o, h, l, c):
    ts = T0 + timedelta(minutes=minute)
    return dict(Timestamp=ts.strftime("%Y-%m-%d %H:%M:%S"),
                Open=str(o), High=str(h), Low=str(l), Close=str(c),
                EMA_50="101", EMA_200="100", ATR="1.0", RSI="50", Volume="10")


def flat_tape(minutes, price=100.0):
    return [bar(m, price, price + 0.1, price - 0.1, price) for m in range(minutes)]


def trade(side="BUY", entry="100", tp="103", minute=10, reason="TP", sl="98"):
    et = T0 + timedelta(minutes=minute)
    xt = et + timedelta(minutes=30)
    return dict(Trade_Type=side, Entry_Time=et.strftime("%Y-%m-%d %H:%M:%S"),
                Exit_Time=xt.strftime("%Y-%m-%d %H:%M:%S"),
                Entry_Price=entry, Take_Profit=tp, Stop_Loss=sl,
                ATR_At_Entry="1.0", Exit_Reason=reason, Profit="3")


class SignalOutlookTests(unittest.TestCase):
    def outlook(self, rows, trades, horizons=(15,)):
        return P.signal_outlook(rows, trades, P.STRUCT_STOP_CUTOVER, horizons=horizons)

    def test_buy_drift_and_target_first(self):
        rows = flat_tape(60)
        # after the entry bar (minute 10): grind up, high touches 103 at minute 20,
        # close 101 at minute 25 (entry+15). Risk from reward leg = |103-100|/1.5 = 2.
        for m in range(11, 26):
            rows[m] = bar(m, 100, 100.5, 99.9, 100 + (m - 10) / 15.0)
        rows[20] = bar(20, 100, 103.0, 99.9, 100.7)
        out = self.outlook(rows, [trade()])
        self.assertTrue(out["ok"])
        cell = out["sides"]["BUY"]["horizons"][15]
        self.assertEqual(cell["n"], 1)
        self.assertEqual(cell["fav_pct"], 100.0)
        self.assertAlmostEqual(cell["drift_r_median"], 0.5, places=2)   # +$1 / $2 risk
        self.assertAlmostEqual(cell["drift_atr_median"], 1.0, places=2)
        self.assertEqual((cell["race_tp"], cell["race_sl"]), (1, 0))
        self.assertEqual(cell["tp_first_pct"], 100.0)
        self.assertAlmostEqual(cell["mfe_r_median"], 1.5, places=2)     # high 103
        self.assertEqual(out["barrier_reference_pct"], 40.0)

    def test_sell_favourable_extreme_is_the_low(self):
        rows = flat_tape(60)
        for m in range(11, 26):
            rows[m] = bar(m, 100, 100.2, 99.5, 100 - (m - 10) / 15.0)
        rows[20] = bar(20, 100, 100.2, 97.0, 99.3)   # low prints the 97 target
        out = self.outlook(rows, [trade(side="SELL", tp="97", sl="102")])
        cell = out["sides"]["SELL"]["horizons"][15]
        self.assertAlmostEqual(cell["drift_r_median"], 0.5, places=2)   # fell $1, SELL's way
        self.assertAlmostEqual(cell["mfe_r_median"], 1.5, places=2)     # from the LOW
        self.assertEqual(cell["ever_tp_pct"], 100.0)
        self.assertEqual(cell["race_tp"], 1)

    def test_signal_bar_itself_is_never_counted(self):
        rows = flat_tape(60)
        rows[10] = bar(10, 100, 150.0, 50.0, 100)    # entry-minute bar spans everything
        out = self.outlook(rows, [trade()])
        cell = out["sides"]["BUY"]["horizons"][15]
        self.assertEqual(cell["race_none"], 1)       # path starts strictly after Entry_Time
        self.assertAlmostEqual(cell["mfe_r_median"], 0.05, places=2)

    def test_gap_censors_instead_of_guessing(self):
        rows = [r for r in flat_tape(60)
                if not ("00:12" <= r["Timestamp"][11:16] <= "00:20")]  # 9-min hole
        out = self.outlook(rows, [trade()])
        cell = out["sides"]["BUY"]["horizons"][15]
        self.assertEqual((cell["n"], cell["censored"]), (0, 1))

    def test_same_bar_double_touch_is_ambiguous(self):
        rows = flat_tape(60)
        rows[12] = bar(12, 100, 103.5, 97.5, 100)    # spans +1.5R and -1R in one minute
        out = self.outlook(rows, [trade()])
        cell = out["sides"]["BUY"]["horizons"][15]
        self.assertEqual(cell["race_amb"], 1)
        self.assertIsNone(cell["tp_first_pct"])      # no decisive race to share out

    def test_ratcheted_row_keeps_reward_leg_risk(self):
        rows = flat_tape(60)
        rows[25] = bar(25, 100, 102.1, 101.9, 102.0)
        rows[24] = bar(24, 100, 102.1, 101.9, 102.0)
        # logged stop == entry (ratcheted); risk must come from |TP-entry|/1.5 = 2, not 0
        out = self.outlook(rows, [trade(sl="100", reason="BE")])
        self.assertTrue(out["ok"])
        self.assertEqual(out["excluded"], 0)

    def test_era_and_unusable_rows(self):
        early = trade(minute=10)
        early["Entry_Time"] = "2026-09-01 00:10:00"          # before cutover: not in sample
        early["Exit_Time"] = "2026-09-01 00:40:00"
        bad = trade()
        bad["Take_Profit"] = ""                               # no reward leg: excluded
        out = self.outlook(flat_tape(60), [early, bad, trade()])
        self.assertEqual(out["n"], 1)
        self.assertEqual(out["excluded"], 1)

    def test_quantile(self):
        self.assertIsNone(P._quantile([], 0.5))
        self.assertEqual(P._quantile([3.0], 0.9), 3.0)
        self.assertAlmostEqual(P._quantile([0, 10], 0.25), 2.5)

    def test_outlook_now_applies_cone_only_when_ready(self):
        rows = flat_tape(60)
        out = self.outlook(rows, [trade(side="SELL", tp="97", sl="102")])
        base = {"ok": True, "as_of": "x", "close": 100.0, "atr": 1.0,
                "BUY": {"ready": False, "passed": 3, "total": 8, "level": 99.0},
                "SELL": {"ready": False, "passed": 7, "total": 8, "level": 101.0}}
        self.assertIsNone(P.outlook_now(dict(base), out, horizon=15)["ready_side"])
        base["SELL"]["ready"] = True
        now = P.outlook_now(base, out, horizon=15)
        self.assertEqual(now["ready_side"], "SELL")
        self.assertGreater(now["stop"], now["entry"])         # SELL stop above
        self.assertLess(now["target"], now["entry"])          # SELL target below
        # cone endpoints are real prices (their order depends on the drift sign)
        self.assertIsNotNone(now["cone"]["median"])
        self.assertTrue(all(now["cone"][k] == now["cone"][k] for k in ("q25", "median", "q75")))


if __name__ == "__main__":
    unittest.main()
