#!/usr/bin/env python3
"""Hermetic tests for tools/cost_model.py — the A6 all-in cost model.

The point of these tests is the tool's HONESTY, not its arithmetic: a cost model
that silently turns an assumption into a "measurement", or that quietly re-costs
the book on the way past, is worse than no model at all. So the assertions are:

  * every leg is labelled OBSERVED / ASSUMED / COMPUTED, and the unobservable
    legs are never presented as measurements;
  * swap arithmetic matches the spec (points -> USD at 0.01 lot) and the triple
    day, with the convention stated;
  * the rollover instant follows the SAME EU DST rule the logger confirmed;
  * the report never writes, never imports engine.py, and never re-registers the
    $0.40 assumption (it recommends a figure and leaves the decision to the owner);
  * the measured sheet is used where it exists and an explicit median fallback
    where it does not — never $0.00 (a zero cost is a data fault, not a cheap trade).

Run: python3 tools/test_cost_model.py
"""
import ast
import json
import os
import sys
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import cost_model as CM  # noqa: E402

SPEC = dict(point=0.01, trade_contract_size=100.0,
            swap_long=-69.5, swap_short=15.07, swap_rollover3days=3)


class SwapTests(unittest.TestCase):
    def test_points_to_usd_at_the_engines_fixed_lot(self):
        # 0.01 lot on a 100 oz contract, point 0.01  ->  $0.01 per point
        # one night at swap_long -69.5 pts = -$0.695 (what XM would actually charge)
        swap, nights, triple = CM.swap_for_trade(
            "BUY", datetime(2026, 11, 4, 20, 8), datetime(2026, 11, 5, 0, 4), SPEC)
        self.assertEqual((nights, triple), (1, 0))
        self.assertAlmostEqual(swap, -0.695, places=3)

    def test_short_swap_is_a_credit_on_this_account(self):
        # XM GOLD pays shorts (+15.07 pts) — the sign must survive, not be assumed negative
        swap, _, _ = CM.swap_for_trade(
            "SELL", datetime(2026, 11, 4, 20, 8), datetime(2026, 11, 5, 0, 4), SPEC)
        self.assertAlmostEqual(swap, 0.1507, places=4)

    def test_not_carried_overnight_means_no_swap(self):
        swap, nights, triple = CM.swap_for_trade(
            "BUY", datetime(2026, 11, 4, 10, 0), datetime(2026, 11, 4, 14, 30), SPEC)
        self.assertEqual((nights, triple, swap), (0, 0, 0.0))

    def test_a_trade_closed_exactly_at_rollover_does_pay_it(self):
        # the server 00:00 boundary is inclusive on the exit side, as at the broker
        swap, nights, _ = CM.swap_for_trade(
            "BUY", datetime(2026, 11, 4, 20, 0), datetime(2026, 11, 4, 22, 0), SPEC)
        self.assertEqual(nights, 1)
        self.assertAlmostEqual(swap, -0.695, places=3)

    def test_rollover_instant_follows_the_confirmed_dst_rule(self):
        # EU +3h until 2026-10-25 -> rollover at 21:00 UTC;  EU +2h after -> 22:00 UTC.
        # THE discriminating case: the SAME 12:00-21:30 UTC window is carried in summer
        # and is not carried in winter. A model that hard-coded 22:00 would fail one half.
        self.assertEqual(
            CM.rollover_nights(datetime(2026, 10, 20, 12, 0), datetime(2026, 10, 20, 21, 30)),
            (1, 1))                                    # Tue -> night ending Wed 00:00 = triple
        self.assertEqual(
            CM.rollover_nights(datetime(2026, 11, 17, 12, 0), datetime(2026, 11, 17, 21, 30)),
            (0, 0))                                    # winter: 22:00 rollover not reached
        self.assertEqual(
            CM.rollover_nights(datetime(2026, 11, 17, 12, 0), datetime(2026, 11, 17, 23, 0)),
            (1, 1))                                    # winter: now it is

    def test_triple_day_uses_the_mt5_enum_convention_and_says_so(self):
        # ENUM_DAY_OF_WEEK 3 = WEDNESDAY -> Python weekday 2. The night out of Tuesday
        # earns the triple charge under this reading; the choice is disclosed, not hidden.
        self.assertEqual(CM._swap_day_enum({"swap_rollover3days": 3}), 2)
        self.assertEqual(CM._swap_day_enum({"swap_rollover3days": 0}), 6)   # SUNDAY
        self.assertEqual(CM._swap_day_enum({"swap_rollover3days": 6}), 5)   # SATURDAY
        self.assertEqual(CM._swap_day_enum({}), 2)                          # MT5 default = 3
        with open(os.path.join(HERE, "cost_model.py"), encoding="utf-8") as fh:
            self.assertIn("CONVENTION RISK", fh.read())

    def test_triple_night_is_charged_three_times(self):
        # Tue 2026-11-03 12:00 -> Thu 2026-11-05 12:00: nights ending Wed and Thu 00:00;
        # the Wednesday one is the triple
        swap, nights, triple = CM.swap_for_trade(
            "BUY", datetime(2026, 11, 3, 12, 0), datetime(2026, 11, 5, 12, 0), SPEC)
        self.assertEqual((nights, triple), (2, 1))
        self.assertAlmostEqual(swap, -0.695 * 4, places=3)     # night + triple counted 3x


class ClassificationTests(unittest.TestCase):
    """The model's central claim: only the spread is a measurement."""

    def setUp(self):
        self.m = CM.build(root=ROOT)

    def test_every_leg_states_its_class(self):
        legs = self.m["legs"]
        self.assertEqual(legs["spread"]["kind"], "OBSERVED")
        self.assertEqual(legs["commission"]["kind"], "ASSUMED")
        self.assertEqual(legs["slippage"]["kind"], "ASSUMED")
        self.assertEqual(legs["swap"]["kind"], "COMPUTED")
        for name, leg in legs.items():
            self.assertIn(leg["kind"], ("OBSERVED", "ASSUMED", "COMPUTED"), name)
            self.assertTrue(leg["source"], name)

    def test_slippage_and_commission_are_never_called_measurements(self):
        text = CM.render(self.m)
        self.assertIn("OBSERVED = measured", text)
        self.assertIn("ASSUMED = a planning value, not a measurement", text)
        # the two unobservable legs must be declared unobservable, in those words
        self.assertIn("NOT observable", text)

    def test_the_registered_assumption_is_not_silently_replaced(self):
        rec = self.m["recommendation"]
        self.assertEqual(rec["registered_now"], CM.REGISTERED_RT)
        self.assertNotEqual(rec["suggested_rt"], CM.REGISTERED_RT)
        self.assertIn("owner decides", rec["note"])
        text = CM.render(self.m)
        self.assertIn("still binding", text)

    def test_share_of_r_uses_measured_trades_only(self):
        # 578 trades predate the quote logger; they must not be presented as measured
        a = self.m["all_in_share_of_1r"]
        self.assertEqual(a["n"], self.m["coverage"]["joined"])
        self.assertLess(a["n"], self.m["trades"])
        self.assertGreater(a["p50"], self.m["spread_share_of_1r"]["p50"])

    def test_all_in_cost_is_never_below_the_measured_spread(self):
        # adding legs can only add cost; a model that "saves" money is broken
        s, a = self.m["spread_share_of_1r"], self.m["all_in_share_of_1r"]
        self.assertGreaterEqual(a["p50"], s["p50"])
        self.assertGreaterEqual(a["p90"], s["p90"])

    def test_fallback_rows_are_counted_not_hidden(self):
        cov = self.m["coverage"]
        self.assertEqual(cov["joined"] + cov["missing"], self.m["trades"])
        self.assertIn("MEASURED", cov["note"])

    def test_swap_total_is_small_and_signed_both_ways(self):
        carried = self.m["carried"]
        self.assertTrue(carried, "the book does have overnight carries")
        self.assertTrue(any(r["swap"] < 0 for r in carried))   # longs pay
        self.assertTrue(any(r["swap"] > 0 for r in carried))   # shorts earn
        self.assertLess(abs(self.m["legs"]["swap"]["value"]), 20.0)

    def test_json_is_serialisable(self):
        self.assertTrue(json.dumps(self.m))


class SafetyTests(unittest.TestCase):
    def test_tool_never_writes_and_never_imports_the_engine(self):
        path = os.path.join(HERE, "cost_model.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        body = src.split('"""')[2]                            # the code, not the docstring
        self.assertNotIn("import engine", body)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertNotIn("engine", imports)
        for banned in ("open(", ".write(", "makedirs", "os.remove(", "os.rename("):
            self.assertNotIn(banned, body, banned)

    def test_the_measured_spread_helper_is_the_shared_one(self):
        # one definition of "measured spread" for the repo: xm_quote_report.trade_costs
        with open(os.path.join(HERE, "cost_model.py"), encoding="utf-8") as fh:
            self.assertIn("QR.trade_costs", fh.read())

    def test_cli_runs_and_returns_zero(self):
        self.assertEqual(CM.main(["--root", ROOT]), 0)

    def test_a_missing_quote_dir_reports_rather_than_crashing(self):
        # no xm_data, no ledger: the tool must still answer (it is a report)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            empty = os.path.join(d, "empty")
            os.makedirs(empty)
            m = CM.build(root=d, qdir=empty)
            self.assertEqual(m["trades"], 0)
            self.assertIsNone(m["whole"])
            self.assertIsNone(m["legs"]["spread"]["value"])
            text = CM.render(m)
            self.assertIn("nothing to read", text)
            self.assertIn("(no data)", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
