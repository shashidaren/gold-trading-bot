"""Hermetic tests for journal.py (self-journal + indicator scoreboard).

Synthetic tape + synthetic ledger only — no live CSVs, no wall clock. The
tests pin the accounting the dashboard and CLI both print:

  * decisive WR excludes BE and TIME; all-in does not;
  * risk comes from the reward leg, so a ratcheted row keeps its R;
  * the assumed cost is charged on every closed trade, scratches included;
  * the open trade is never counted;
  * the entry context is the bar STRICTLY BEFORE the entry (no look-ahead);
  * give-backs are factual: a scratch that was +0.75R ahead is listed;
  * the scoreboard's permutation guard flags a real separation but not noise.

Run: python3 tools/test_journal.py
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import indicators as IND  # noqa: E402
import journal as J  # noqa: E402

T0 = datetime(2026, 10, 23, 6, 0)
LEDGER_COLS = ["Trade_Num", "Trade_Type", "Entry_Time", "Exit_Time", "Entry_Price",
               "Stop_Loss", "Take_Profit", "Exit_Price", "Exit_Reason", "Profit",
               "Balance_After", "RSI_At_Entry", "ATR_At_Entry", "Wick_Ratio_At_Entry",
               "EMA50_At_Entry", "EMA200_At_Entry"]


def tape(n=520, start=4000.0, step=0.5, band=1.0):
    rows = []
    for k in range(n):
        ts = T0 + timedelta(minutes=k)
        c = start + step * k
        o = c - step / 2
        rows.append({
            "Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "Open": f"{o:.2f}", "High": f"{c + band:.2f}", "Low": f"{o - band:.2f}",
            "Close": f"{c:.2f}", "Volume": str(20 + (k % 5)),
            "RSI": "55.0", "ATR": "2.0", "EMA_50": f"{c - 1:.2f}",
            "EMA_200": f"{c - 3:.2f}", "Wick_Ratio": "0.0%",
        })
    return rows


def trade(num, side, entry_min, exit_min, entry, sl, tp, exit_px, reason, profit,
          rsi=50.0, atr=2.0, wick="50.0%"):
    return {
        "Trade_Num": str(num), "Trade_Type": side,
        "Entry_Time": (T0 + timedelta(minutes=entry_min)).strftime("%Y-%m-%d %H:%M:%S"),
        "Exit_Time": (T0 + timedelta(minutes=exit_min)).strftime("%Y-%m-%d %H:%M:%S"),
        "Entry_Price": f"{entry}", "Stop_Loss": f"{sl}", "Take_Profit": f"{tp}",
        "Exit_Price": f"{exit_px}", "Exit_Reason": reason, "Profit": f"{profit}",
        "Balance_After": "500", "RSI_At_Entry": f"{rsi}", "ATR_At_Entry": f"{atr}",
        "Wick_Ratio_At_Entry": wick, "EMA50_At_Entry": f"{entry - 1}",
        "EMA200_At_Entry": f"{entry - 3}",
    }


def book():
    # 1 TP (+1.5R), 1 SL (-1R), 1 BE (0, ratcheted stop == entry), 1 TIME (-0.2R)
    return [
        trade(1, "BUY", 30, 40, 4015.0, 4005.0, 4030.0, 4030.0, "TP", 15.0),
        trade(2, "SELL", 70, 80, 4030.0, 4040.0, 4015.0, 4040.0, "SL", -10.0),
        trade(3, "BUY", 90, 110, 4045.0, 4045.0, 4060.0, 4045.0, "BE", 0.0),
        trade(4, "SELL", 120, 130, 4060.0, 4070.0, 4045.0, 4065.0, "TIME", -2.0),
    ]


def status():
    return {
        "trade_active": True, "trade_type": "BUY", "current_trade_num": 5,
        "entry_time": (T0 + timedelta(minutes=140)).strftime("%Y-%m-%d %H:%M:%S"),
        "entry_price": 4080.0, "stop_loss": 4070.0, "take_profit": 4095.0,
        "entry_rsi": 58.0, "entry_atr": 2.1, "entry_wick_ratio": 0.55,
        "entry_ema_fast": 4078.0, "entry_ema_slow": 4074.0,
    }


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = J.build(tape(), book(), status(), [], cost=0.40, permutations=0)

    def test_all_rows_join_and_the_open_trade_is_not_counted(self):
        self.assertTrue(self.report["ok"])
        self.assertEqual(self.report["book"]["n"], 4)
        self.assertEqual(self.report["unparsed_rows"], 0)
        self.assertIsNotNone(self.report["open"])
        self.assertEqual(self.report["open"]["reason"], "OPEN")

    def test_outcome_counts_and_decisive_win_rate(self):
        b = self.report["book"]
        self.assertEqual((b["counts"]["TP"], b["counts"]["SL"], b["counts"]["BE"], b["counts"]["TIME"]),
                         (1, 1, 1, 1))
        self.assertAlmostEqual(b["decisive_wr"], 50.0)
        self.assertAlmostEqual(b["all_in_pct"], 25.0)

    def test_risk_comes_from_the_reward_leg_not_the_ratcheted_stop(self):
        be = [e for e in self.report["entries"] if e["num"] == "3"][0]
        self.assertAlmostEqual(be["risk"], 10.0)          # |4060 - 4045| / 1.5
        self.assertAlmostEqual(be["r"], 0.0)
        tp = [e for e in self.report["entries"] if e["num"] == "1"][0]
        self.assertAlmostEqual(tp["r"], 1.5)

    def test_cost_is_charged_on_every_closed_trade(self):
        b = self.report["book"]
        self.assertAlmostEqual(b["gross"], 3.0)
        self.assertAlmostEqual(b["net"], 3.0 - 4 * 0.40)
        self.assertAlmostEqual(b["net_per_trade"], b["net"] / 4)

    def test_payoff_and_breakeven(self):
        b = self.report["book"]
        self.assertAlmostEqual(b["payoff"], 1.5)
        self.assertAlmostEqual(b["breakeven_wr_pct"], 40.0)

    def test_entry_context_is_the_bar_before_the_entry(self):
        for e in self.report["entries"]:
            self.assertLess(e["context"]["ts"], e["entry_time"], f"trade {e['num']}")

    def test_giveback_is_flagged_for_a_scratch_that_was_ahead(self):
        g = self.report["givebacks"]
        self.assertEqual(g["was_ahead_n"], 1)
        self.assertEqual(g["scratched_runners"], 1)
        self.assertEqual(g["stopped_after_profit"], 0)
        self.assertGreater(g["worst"][0]["mfe_r"], 0.75)

    def test_daily_grouping_uses_entry_date(self):
        days = J.daily(self.report["entries"])
        self.assertEqual(len(days), 1)
        self.assertEqual(days[0]["n"], 4)

    def test_open_trade_has_r_now_and_is_not_in_the_book(self):
        o = self.report["open"]
        self.assertIsNotNone(o["r_now"])
        self.assertAlmostEqual(o["risk"], 10.0)

    def test_report_lines_and_csv(self):
        self.report["board"] = J.indicator_board(self.report["entries"], permutations=0)
        text = "\n".join(J.report_lines(self.report))
        self.assertIn("SUCCESS RATE", text)
        self.assertIn("decisive 50.0%", text)
        csv_text = J.entries_csv(self.report["entries"])
        self.assertEqual(csv_text.splitlines()[0].split(",")[0], "Trade_Num")
        self.assertEqual(len(csv_text.strip().splitlines()), 5)


class Summaries(unittest.TestCase):
    def test_empty_book_is_all_none_not_an_exception(self):
        s = J.summarise([])
        self.assertEqual(s["n"], 0)
        self.assertIsNone(s["decisive_wr"])
        self.assertIsNone(s["net_per_trade"])

    def test_bad_rows_are_skipped_not_counted(self):
        rows = [{"Trade_Num": "9", "Trade_Type": "", "Entry_Time": "2026-10-23 06:30:00"}]
        rep = J.build(tape(60), rows, None, [])
        self.assertEqual(rep["book"]["n"], 0)
        self.assertEqual(rep["unparsed_rows"], 1)


def fake_entry(i, reason, adx, r=None):
    """A journal entry dict good enough for indicator_board()."""
    ctx = {}
    for key in IND.CONTEXT_FIELDS:
        ctx[key] = ((i * 37 + (len(key) * 13)) % 100) / 100.0   # deterministic, outcome-independent
    ctx.update({"adx": adx, "rsi": 50.0, "atr": 2.0, "ema_spread_atr": 0.0,
                "plus_di": 20.0, "minus_di": 20.0, "macd_hist": 0.0})
    side = "BUY" if (i // 2) % 2 == 0 else "SELL"
    r = r if r is not None else (1.5 if reason == "TP" else -1.0)
    return {
        "num": str(i + 1), "side": side, "reason": reason, "r": r, "net": r - 0.4,
        "entry_time": T0 + timedelta(minutes=i), "context": ctx, "open": False,
    }


class Scoreboard(unittest.TestCase):
    def test_a_real_separation_is_flagged_as_a_candidate(self):
        entries = [fake_entry(i, "TP" if i % 2 == 0 else "SL", 30.0 if i % 2 == 0 else 10.0)
                   for i in range(40)]
        board = J.indicator_board(entries, permutations=200, seed=7)
        self.assertEqual(board["n_decisive"], 40)
        self.assertIsNotNone(board["p_global_wr"])
        self.assertLess(board["p_global_wr"], 0.05)
        verdict = board["verdict"]
        self.assertTrue(verdict.startswith("1 ") or verdict.startswith("2 ")
                        or verdict.startswith("3 "), verdict)
        adx = [r for r in board["rows"] if r["key"] == "adx"][0]
        self.assertTrue(adx["verdict"].startswith("candidate"), adx["verdict"])
        self.assertAlmostEqual(adx["lift"], 100.0)

    def test_pure_noise_does_not_produce_a_candidate(self):
        # outcome follows a pattern unrelated to the ADX split (which alternates)
        entries = []
        for i in range(60):
            win = (i * 17) % 60 < 30
            entries.append(fake_entry(i, "TP" if win else "SL",
                                      30.0 if i % 2 == 0 else 10.0))
        board = J.indicator_board(entries, permutations=200, seed=7)
        self.assertFalse(board["verdict"].startswith("1 "), board["verdict"])

    def test_a_categorical_feature_with_one_empty_bucket_is_reported_not_crashed(self):
        entries = []
        for i in range(40):
            e = fake_entry(i, "TP" if i % 2 == 0 else "SL", 25.0)
            e["context"]["di_side"] = e["side"]          # every trade agrees
            entries.append(e)
        board = J.indicator_board(entries, permutations=40, seed=7)
        keys = [s["key"] for s in board["skipped"]]
        self.assertIn("di_side", keys)
        self.assertTrue(board["rows"])

    def test_zero_permutations_still_tabulates(self):
        entries = [fake_entry(i, "TP" if i % 2 == 0 else "SL", 25.0) for i in range(40)]
        board = J.indicator_board(entries, permutations=0)
        self.assertIsNone(board["p_global_wr"])
        self.assertTrue(board["rows"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
