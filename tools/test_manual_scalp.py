"""Hermetic tests for the manual scalping calculator and private journal."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import manual_scalp as M  # noqa: E402


def ticket(**changes):
    payload = {
        "side": "BUY", "entry": "100", "stop": "95", "target": "110",
        "account_balance": "10000", "risk_pct": "1", "spread": "0.50",
        "contract_size": "100", "volume_step": "0.01",
        "timeframe": "M5", "setup": "M5 retest", "notes": "synthetic",
    }
    payload.update(changes)
    return payload


class CalculatorTests(unittest.TestCase):
    def test_buy_costed_geometry_and_size_round_down(self):
        c = M.calculate(ticket())
        self.assertEqual(c["gross_risk_per_oz"], 5)
        self.assertEqual(c["gross_reward_per_oz"], 10)
        self.assertEqual(c["net_risk_per_oz"], 5.5)
        self.assertEqual(c["net_reward_per_oz"], 9.5)
        self.assertAlmostEqual(c["gross_rr"], 2.0)
        self.assertAlmostEqual(c["net_rr"], 9.5 / 5.5)
        self.assertAlmostEqual(c["risk_budget_usd"], 100)
        self.assertAlmostEqual(c["raw_lots"], 100 / 550)
        self.assertEqual(c["lots"], 0.18)             # never rounded up to .19
        self.assertAlmostEqual(c["planned_risk_usd"], 99)
        self.assertAlmostEqual(c["planned_reward_usd"], 171)
        self.assertEqual(c["warnings"], [])

    def test_sell_uses_the_correct_legs(self):
        c = M.calculate(ticket(side="SELL", entry="100", stop="105", target="90"))
        self.assertEqual(c["gross_risk_per_oz"], 5)
        self.assertEqual(c["gross_reward_per_oz"], 10)
        self.assertAlmostEqual(c["net_rr"], 9.5 / 5.5)

    def test_wrong_side_stop_or_target_is_refused(self):
        with self.assertRaises(M.ValidationError):
            M.calculate(ticket(stop="101"))
        with self.assertRaises(M.ValidationError):
            M.calculate(ticket(side="SELL", stop="105", target="101"))

    def test_bad_numbers_are_refused(self):
        for key, value in (("entry", "nan"), ("entry", "inf"), ("spread", "-0.1"),
                           ("risk_pct", "0"), ("risk_pct", "101"), ("account_balance", ""),
                           ("volume_step", "0")):
            with self.subTest(key=key, value=value), self.assertRaises(M.ValidationError):
                M.calculate(ticket(**{key: value}))

    def test_derived_overflow_is_a_validation_error_not_a_500(self):
        with self.assertRaises(M.ValidationError):
            M.calculate(ticket(account_balance="1e308", risk_pct="100"))
        with self.assertRaises(M.ValidationError):
            M.calculate(ticket(volume_step="1e-320"))

    def test_tiny_size_and_expensive_geometry_are_warnings(self):
        c = M.calculate(ticket(account_balance="10", spread="2", target="101"))
        self.assertEqual(c["lots"], 0)
        self.assertLess(c["net_reward_per_oz"], 0)
        self.assertGreaterEqual(len(c["warnings"]), 3)
        self.assertIsNone(c["breakeven_win_pct"])

    def test_close_charges_spread_once_and_uses_original_sized_risk(self):
        record = M.calculate(ticket())
        result = M.close_result(record, "110")
        self.assertAlmostEqual(result["gross_pnl"], 180)
        self.assertAlmostEqual(result["net_pnl"], 171)
        self.assertAlmostEqual(result["result_r"], 171 / 99)
        sell = M.calculate(ticket(side="SELL", entry="100", stop="105", target="90"))
        self.assertAlmostEqual(M.close_result(sell, "90")["net_pnl"], 171)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="manual-scalp-test-")
        self.path = os.path.join(self.tmp.name, "nested", "journal.json")
        self.store = M.JournalStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_taken_persists_server_recalculated_snapshot(self):
        row = self.store.create(ticket(decision="taken", lots="99", planned_risk_usd="1"))
        self.assertEqual(row["status"], "OPEN")
        self.assertEqual(row["source"], "manual-self-reported")
        self.assertEqual(row["lots"], 0.18)
        self.assertAlmostEqual(row["planned_risk_usd"], 99)
        self.assertEqual(row["net_pnl"], None)
        with open(self.path, encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk["version"], 1)
        self.assertEqual(len(on_disk["entries"]), 1)
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), "0o600")

    def test_skipped_zero_size_is_loggable_but_taken_is_not(self):
        row = self.store.create(ticket(decision="skipped", account_balance="10", setup="too expensive"))
        self.assertEqual(row["status"], "SKIPPED")
        self.assertEqual(row["lots"], 0)
        with self.assertRaises(M.ValidationError):
            self.store.create(ticket(decision="taken", account_balance="10"))

    def test_close_open_row_and_summary(self):
        opened = self.store.create(ticket(decision="taken"))
        self.store.create(ticket(decision="skipped", setup="mid-box"))
        closed = self.store.close(opened["id"], {"exit_price": "110", "exit_reason": "TP"})
        self.assertEqual(closed["status"], "CLOSED")
        self.assertAlmostEqual(closed["net_pnl"], 171)
        read = self.store.read()
        self.assertEqual(read["summary"]["open"], 0)
        self.assertEqual(read["summary"]["skipped"], 1)
        self.assertEqual(read["summary"]["closed"], 1)
        self.assertEqual(read["summary"]["wins"], 1)
        self.assertAlmostEqual(read["summary"]["net_pnl"], 171)
        self.assertEqual(read["summary"]["review_remaining"], 99)
        self.assertEqual(read["rows"][0]["status"], "SKIPPED")  # newest first

    def test_close_rejects_missing_repeat_and_skipped_rows(self):
        skipped = self.store.create(ticket(decision="skipped"))
        with self.assertRaises(M.ValidationError):
            self.store.close(skipped["id"], {"exit_price": "101"})
        with self.assertRaises(M.ValidationError):
            self.store.close("missing", {"exit_price": "101"})
        opened = self.store.create(ticket(decision="taken"))
        self.store.close(opened["id"], {"exit_price": "101"})
        with self.assertRaises(M.ValidationError):
            self.store.close(opened["id"], {"exit_price": "102"})

    def test_close_reason_and_text_are_validated(self):
        opened = self.store.create(ticket(decision="taken"))
        with self.assertRaises(M.ValidationError):
            self.store.close(opened["id"], {"exit_price": "101", "exit_reason": "OTHER"})
        with self.assertRaises(M.ValidationError):
            self.store.create(ticket(decision="skipped", setup=" "))
        with self.assertRaises(M.ValidationError):
            self.store.create(ticket(decision="skipped", setup="x" * 161))

    def test_corrupt_journal_is_never_silently_reset(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("not json")
        with self.assertRaises(M.JournalError):
            self.store.read()
        with self.assertRaises(M.JournalError):
            self.store.create(ticket(decision="skipped"))
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "not json")

    def test_no_engine_or_bot_ledger_dependency(self):
        source_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "manual_scalp.py")
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("import engine", source)
        self.assertNotIn("trades.csv", source)


if __name__ == "__main__":
    unittest.main()
