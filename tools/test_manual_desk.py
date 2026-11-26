#!/usr/bin/env python3
"""Hermetic tests for manual_desk.py — the display-only MANUAL DESK read layer.

Synthetic status/ctx only: no live CSVs, no Flask, no wall clock, no writes.
Pins the things that would silently lie to a human trading alongside the bot:

  1. open paper trade geometry / ratchet / 240-min time stop, and malformed
     status reported as unusable rather than coerced;
  2. the registered $0.40 stays binding and $0.57 stays deferred;
  3. break-even arithmetic (40% uncosted, higher with cost AND scratches);
  4. every checklist row reads the engine's gates back honestly, missing reads
     are 'unknown' (never green), and the verdict never says buy or sell;
  5. the §7 private observation template carries every field and its rules;
  6. the module never imports the engine and never opens a file for writing.

Run: python3 tools/test_manual_desk.py
"""
import ast
import inspect
import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import manual_desk as MD  # noqa: E402
import pressure as P  # noqa: E402

NOW = datetime(2026, 11, 26, 14, 59)   # Thursday, market open


def ctx(**kw):
    base = {
        "feed": {"ok": True, "age_seconds": 12},
        "setup": {"ok": True, "atr": 2.40, "close": 3580.63},
        "location": {"buy": {"risk": 9.96}, "sell": {"risk": 9.96}},
        "portfolio": {
            "sides_blocked": {"BUY": None, "SELL": None},
            "next_window": ("Daily Market Rollover & Spread Spike",
                            ("BUY", "SELL"), datetime(2026, 11, 26, 21, 45)),
            "cooldown_minutes_left": 0, "cooldown_note": "",
            "daily_sls": 8, "breaker_on": False,
        },
        "risk_now": {"quote": {"spread": 0.55, "stale": False}},
    }
    base.update(kw)
    return base


def status(**kw):
    base = {"trade_active": True, "trade_type": "BUY", "current_trade_num": 1065,
            "entry_price": 3571.95, "stop_loss": 3565.29, "take_profit": 3581.94,
            "entry_time": "2026-11-26 12:12:06", "be_armed": False}
    base.update(kw)
    return base


def by_key(checks, key):
    return next(c for c in checks if c["key"] == key)


class Mirrors(unittest.TestCase):
    def test_every_mirrored_constant_equals_pressure(self):
        for name, mine, real in (
            ("RR_TARGET", MD.RR_TARGET, P.RR_TARGET),
            ("MAX_HOLD_MINUTES", MD.MAX_HOLD_MINUTES, P.MAX_HOLD_MINUTES),
            ("MIN_ATR", MD.MIN_ATR, P.MIN_ATR),
            ("MAX_ATR", MD.MAX_ATR, P.MAX_ATR_TO_TRADE),
            ("MAX_DAILY_LOSSES", MD.MAX_DAILY_LOSSES, P.MAX_DAILY_LOSSES),
        ):
            self.assertEqual(mine, real, name)

    def test_market_quiet_matches_pressure(self):
        for t in (NOW, datetime(2026, 11, 22, 12, 0), datetime(2026, 11, 26, 21, 30),
                  datetime(2026, 11, 27, 1, 0), datetime(2026, 11, 27, 3, 0)):
            self.assertEqual(MD.market_quiet(t), P.market_quiet(t), str(t))

    def test_module_never_imports_engine_or_writes_a_file(self):
        src = inspect.getsource(MD)
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertFalse(any(name.startswith("engine") or name.startswith("trade_filter")
                             for name in imported))
        self.assertNotIn("open(", src)          # no file writer, no journal reader
        self.assertNotIn("requests", src)


class OpenPosition(unittest.TestCase):
    def test_flat_book_is_explicit_and_draws_no_levels(self):
        r = MD.open_position({"trade_active": False}, NOW)
        self.assertFalse(r["ok"])
        self.assertEqual(MD.open_levels({"trade_active": False}), [])
        self.assertEqual(r["reason"], "no open paper trade")

    def test_geometry_age_and_time_stop(self):
        r = MD.open_position(status(), NOW)
        self.assertTrue(r["ok"])
        self.assertEqual(r["side"], "BUY")
        self.assertAlmostEqual(r["risk_usd"], 6.66, places=2)
        self.assertAlmostEqual(r["reward_usd"], 9.99, places=2)
        self.assertAlmostEqual(r["rr"], 1.5, places=2)
        self.assertAlmostEqual(r["age_min"], 166.9, places=1)
        self.assertAlmostEqual(r["time_left_min"], 73.1, places=1)
        self.assertFalse(r["ratcheted"])
        self.assertTrue(r["paper_only"])

    def test_ratcheted_stop_is_flagged_and_not_drawn_twice(self):
        r = MD.open_position(status(stop_loss=3571.95, be_armed=True), NOW)
        self.assertTrue(r["ratcheted"])
        self.assertIsNone(r["rr"])
        levels = MD.open_levels(status(stop_loss=3571.95, be_armed=True))
        self.assertEqual(len(levels), 2)       # entry+BE label, and target
        self.assertIn("BE stop", levels[0]["label"])
        self.assertEqual([l["kind"] for l in levels], ["open_entry", "open_target"])

    def test_three_levels_and_their_kinds(self):
        levels = MD.open_levels(status())
        self.assertEqual(len(levels), 3)
        self.assertEqual([l["kind"] for l in levels],
                         ["open_entry", "open_stop", "open_target"])
        self.assertEqual([l["price"] for l in levels], [3571.95, 3565.29, 3581.94])

    def test_malformed_status_never_becomes_a_position(self):
        for bad in (status(entry_price="nan"), status(stop_loss=None),
                    status(take_profit="oops"), {"trade_active": True}, None):
            r = MD.open_position(bad, NOW)
            self.assertFalse(r["ok"], str(bad))
            self.assertEqual(MD.open_levels(bad), [], str(bad))
        # Valid geometry but an unparseable entry time keeps the levels and
        # refuses to invent an age / time-stop clock.
        r = MD.open_position(status(entry_time="not a time"), NOW)
        self.assertTrue(r["ok"])
        self.assertIsNone(r["age_min"])
        self.assertIsNone(r["time_left_min"])
        self.assertIn("unknown", r["note"])

    def test_future_entry_does_not_produce_negative_age(self):
        r = MD.open_position(status(entry_time="2026-11-26 18:00:00"), NOW)
        self.assertGreaterEqual(r["age_min"], 0)
        self.assertLessEqual(r["time_left_min"], MD.MAX_HOLD_MINUTES)


class Cost(unittest.TestCase):
    def test_registered_cost_stays_binding_even_after_the_next_window_date(self):
        before = MD.cost_basis(NOW)
        self.assertEqual(before["binding_rt"], 0.40)
        self.assertEqual(before["next_rt"], 0.57)
        self.assertIn("2026-12-01 21:00 UTC", before["next_from"])
        self.assertEqual(before["days_left"], 6)
        after = MD.cost_basis(datetime(2026, 12, 2, 10, 0))
        self.assertEqual(after["binding_rt"], 0.40)   # no silent re-cost
        self.assertEqual(after["days_left"], 0)
        self.assertIn("pre-registration", after["next_status"])

    def test_break_even_is_40_percent_uncosted_and_rises(self):
        self.assertEqual(MD.break_even_wr(1.5, 0.0, 6.0), 40.0)
        self.assertEqual(MD.break_even_wr(1.5, 0.40, 6.0), 42.67)
        with_scratches = MD.break_even_wr(1.5, 0.40, 6.0, 0.27)
        self.assertGreater(with_scratches, 42.67)
        self.assertGreater(MD.break_even_wr(1.5, 0.57, 6.0), 42.67)
        self.assertIsNone(MD.break_even_wr(1.5, 0.40, 0))
        self.assertIsNone(MD.break_even_wr(1.5, 0.40, None))

    def test_cost_ruler_is_spread_over_risk_and_flags_tight_stops(self):
        ruler = MD.cost_ruler(2.40)
        self.assertEqual(len(ruler), 6)
        self.assertAlmostEqual(ruler[0]["risk_usd"], 2.40, places=2)
        self.assertAlmostEqual(ruler[0]["shares"][0]["pct"], 16.7, places=1)
        self.assertEqual(ruler[0]["verdict"], "too tight")
        self.assertEqual(ruler[1]["verdict"], "cautious")
        self.assertEqual(ruler[-1]["verdict"], "cost-affordable")
        self.assertEqual(MD.cost_ruler(0.20)[0]["verdict"], "too tight")
        self.assertEqual(MD.cost_ruler(None), [])


class Checklist(unittest.TestCase):
    def test_clean_context_has_no_red_or_amber_rows(self):
        checks = MD.checklist({"trade_active": False}, ctx(), NOW)
        v = MD.verdict(checks)
        self.assertEqual(v["state"], "pass", str(checks))
        self.assertEqual(v["counts"]["block"], 0)
        self.assertEqual(v["counts"]["unknown"], 0)
        self.assertEqual(len(checks), 8)

    def test_verdict_is_about_conditions_only(self):
        for checks in (MD.checklist({}, ctx(), NOW),
                       MD.checklist({}, ctx(feed={"ok": False}), NOW)):
            v = MD.verdict(checks)
            self.assertNotIn("buy", v["headline"].lower())
            self.assertNotIn("sell", v["headline"].lower())

    def test_stale_feed_blocks(self):
        self.assertEqual(by_key(MD.checklist({}, ctx(feed={"ok": True, "age_seconds": 900}), NOW),
                                "feed")["state"], "block")

    def test_missing_feed_is_unknown_not_green(self):
        self.assertEqual(by_key(MD.checklist({}, ctx(feed={}), NOW), "feed")["state"], "unknown")

    def test_atr_outside_band_blocks(self):
        for atr in (0.9, 5.1):
            c = by_key(MD.checklist({}, ctx(setup={"atr": atr}), NOW), "atr")
            self.assertEqual(c["state"], "block", str(atr))

    def test_blackouts_are_direction_aware(self):
        both = ctx(portfolio={"sides_blocked": {"BUY": "rollover", "SELL": "rollover"},
                              "cooldown_minutes_left": 0, "daily_sls": 8,
                              "breaker_on": False})
        self.assertEqual(by_key(MD.checklist({}, both, NOW), "blackout")["state"], "block")
        one = ctx(portfolio={"sides_blocked": {"BUY": "London open", "SELL": None},
                             "cooldown_minutes_left": 0, "daily_sls": 8,
                             "breaker_on": False})
        c = by_key(MD.checklist({}, one, NOW), "blackout")
        self.assertEqual(c["state"], "warn")
        self.assertIn("BUY", c["value"])

    def test_breaker_and_cooldown(self):
        p = dict(ctx()["portfolio"], breaker_on=True, daily_sls=10,
                 cooldown_minutes_left=24)
        checks = MD.checklist({}, ctx(portfolio=p), NOW)
        self.assertEqual(by_key(checks, "breaker")["state"], "block")
        self.assertEqual(by_key(checks, "cooldown")["state"], "warn")

    def test_closed_market_blocks(self):
        for t in (datetime(2026, 11, 22, 12, 0), datetime(2026, 11, 26, 22, 0)):
            self.assertEqual(by_key(MD.checklist({}, ctx(), t), "closure")["state"], "block")

    def test_spread_over_20_percent_of_r_blocks(self):
        c = ctx(location={"buy": {"risk": 1.0}, "sell": {"risk": 1.0}})
        self.assertEqual(by_key(MD.checklist({}, c, NOW), "cost_share")["state"], "block")
        c = ctx(location={"buy": {"risk": 5.0}, "sell": {"risk": 5.0}})
        self.assertEqual(by_key(MD.checklist({}, c, NOW), "cost_share")["state"], "warn")

    def test_stale_quote_falls_back_to_measured_median(self):
        c = ctx(risk_now={"quote": {"spread": 0.01, "stale": True}})
        detail = by_key(MD.checklist({}, c, NOW), "cost_share")["detail"]
        self.assertIn("measured median", detail)
        self.assertIn("$0.55", detail)

    def test_open_paper_position_warns_about_one_position(self):
        c = by_key(MD.checklist(status(), ctx(), NOW), "one_position")
        self.assertEqual(c["state"], "warn")
        self.assertIn("BUY", c["value"])
        self.assertIn("stop cluster", c["detail"])

    def test_empty_context_is_unknown_not_a_green_light(self):
        v = MD.verdict(MD.checklist({}, {}, NOW))
        self.assertGreater(v["counts"]["unknown"], 0)
        self.assertNotEqual(v["state"], "pass")


class Brief(unittest.TestCase):
    def test_brief_is_json_safe_and_carries_every_section(self):
        b = MD.brief(status(), ctx(), NOW)
        json.dumps(b)                          # must not raise (no datetime leaking)
        for key in ("ok", "as_of", "open", "levels", "checks", "verdict", "cost",
                    "break_even", "ruler", "notes", "observation", "disclaimer"):
            self.assertIn(key, b)
        self.assertEqual(len(b["levels"]), 3)
        self.assertEqual(len(b["ruler"]), 6)
        self.assertIn("no order", b["disclaimer"])

    def test_flat_brief_is_still_useful(self):
        b = MD.brief({"trade_active": False}, ctx(), NOW)
        self.assertTrue(b["ok"])
        self.assertFalse(b["open"]["ok"])
        self.assertEqual(b["levels"], [])

    def test_observation_template_has_every_section_7_field_and_the_rules(self):
        b = MD.brief({}, ctx(), NOW)
        fields = b["observation"]["fields"]
        for required in ("timestamp_utc", "bot_trade_id", "bot_entry", "bot_sl",
                         "bot_tp", "manual_entry", "manual_exit", "pressure_source",
                         "pressure_metric", "pressure_timeframe",
                         "pressure_value_at_entry", "pressure_value_at_stop_touch",
                         "last_closed_bar_utc", "contemporaneous_action", "reason_code",
                         "max_hold_or_exit_rule", "post_stop_markout_horizons", "mfe",
                         "mae", "hypothetical_exit", "estimated_cost",
                         "notes_without_account_identifiers", "side"):
            self.assertIn(required, fields)
        self.assertEqual(len(b["observation"]["header"].split(",")), len(fields))
        joined = " ".join(b["observation"]["rules"])
        self.assertIn("100", joined)
        self.assertIn("mark-out", joined)
        self.assertIn("BEFORE", joined)
        self.assertIn("outside Git", joined)

    def _cli(self):
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manual_desk_report.py")
        spec = importlib.util.spec_from_file_location("manual_desk_report_under_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_cli_template_is_a_header_only_and_read_only(self):
        CLI = self._cli()
        t = CLI.template_text()
        self.assertEqual(t.splitlines()[2], MD.CSV_HEADER)
        self.assertIn("Private manual observation log", t)
        self.assertIn("outside Git", t)
        self.assertNotIn("3580", t)             # no filled rows, no live data

    def test_cli_text_renders_without_a_wall_clock_or_live_files(self):
        CLI = self._cli()
        out = CLI.text(MD.brief(status(), ctx(), NOW))
        self.assertIn("MANUAL DESK", out)
        self.assertIn("CHECKLIST", out)
        self.assertIn("COST RULER", out)
        self.assertIn("PRIVATE OBSERVATION LOG", out)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
