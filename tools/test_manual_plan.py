"""Hermetic tests for manual_plan.py — the manual trader's read layer.

Synthetic tapes and a synthetic broker spec only: no live CSVs, no wall clock, no
network, no writes. The dashboard render test is skipped when Flask is absent so a
minimal checkout still runs the rest.

What these pin, and why each one matters:

  1. the lot grid is snapped DOWN and a size under the broker minimum is REFUSED,
     never rounded up (rounding up silently risks more than the trader asked for);
  2. the cost share is spread / risk, invariant to lot size, and its break-even win
     rate matches the payoff it prints;
  3. the stop is the structural one (level + clearance), and a stop that sits INSIDE
     the tested level is refused — the defect 64% of the old book had;
  4. the daily-break clock names "closed" / "guard" / "open" correctly, including a
     window that wraps midnight;
  5. the journal refuses a credential-shaped field, refuses a row inside the repo,
     and appends exactly one ordered line when it is allowed to;
  6. a bare checkout still reads where it stands, but the private journal can never
     default into the repo;
  7. the manual read can never claim a measured edge — the honest footer travels with
     it, and the bot's own gate verdict is attached as context, not as a veto.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import manual_plan as M  # noqa: E402
import pressure as P    # noqa: E402

T0 = datetime(2026, 11, 26, 10, 0)


def tape(n=120, px=3580.0, atr=2.4, step=0.1):
    rows = []
    for i in range(n):
        o = px
        c = px + step
        rows.append({"Timestamp": (T0 + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"),
                     "Open": str(o), "High": str(max(o, c) + 0.4),
                     "Low": str(min(o, c) - 0.4), "Close": str(c), "ATR": str(atr)})
        px = c
    return rows


def spec(**over):
    base = {"source": "captured", "captured_utc": "2026-11-26 13:57:01",
            "account_kind": "REAL", "contract_size": 100.0, "volume_min": 0.01,
            "volume_step": 0.001, "volume_max": 50.0, "point": 0.01,
            "leverage": 1000.0, "stops_level_points": 0.0, "freeze_level_points": 0.0,
            "swap_long": -69.5, "swap_short": 15.07, "path": "GOLD"}
    base.update(over)
    return base


# ── 1. sizing ───────────────────────────────────────────────────────────────
class Sizing(unittest.TestCase):
    def test_lots_snap_down_and_never_up(self):
        lots, note = M.round_lots(0.0199, spec())
        self.assertAlmostEqual(lots, 0.019)
        self.assertIsNone(note)
        lots, note = M.round_lots(0.0299, spec(volume_step=0.01))
        self.assertAlmostEqual(lots, 0.02)
        self.assertIsNone(note)

    def test_a_size_under_the_minimum_is_refused_not_raised(self):
        lots, note = M.round_lots(0.005, spec())
        self.assertEqual(lots, 0.0)
        self.assertIn("minimum lot", note)

    def test_a_size_over_the_maximum_is_capped_with_a_note(self):
        lots, note = M.round_lots(99.0, spec())
        self.assertAlmostEqual(lots, 50.0)
        self.assertIn("maximum", note)

    def test_dollars_risk_and_margin_follow_the_contract(self):
        rows = M.sizing_rows(9.96, budgets=(10.0,), spec=spec(), entry=3580.0)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # 0.010 lot x 100 oz x $9.96 = $9.96 at risk
        self.assertAlmostEqual(row["risk_usd"], 9.96, places=6)
        self.assertAlmostEqual(row["margin_usd"], 0.01 * 100 * 3580.0 / 1000.0, places=6)
        # the cost share is the same number as cost / 1R — size cannot change it
        self.assertAlmostEqual(row["cost_share_pct"], 100.0 * M.COST_ROUND_TRIP / 9.96, places=6)

    def test_a_zero_or_missing_risk_yields_no_rows(self):
        self.assertEqual(M.sizing_rows(0, spec=spec()), [])
        self.assertEqual(M.sizing_rows(None, spec=spec()), [])


# ── 2. cost ─────────────────────────────────────────────────────────────────
class Cost(unittest.TestCase):
    def test_cost_share_is_spread_over_risk(self):
        cost = M.cost_view(100.0, 95.0, 107.5, spread_rt=0.5)
        self.assertAlmostEqual(cost["share_pct"], 10.0)
        self.assertAlmostEqual(cost["gross_rr"], 1.5)
        self.assertTrue(cost["ok"])

    def test_break_even_win_rate_matches_the_net_payoff(self):
        cost = M.cost_view(100.0, 95.0, 107.5, spread_rt=0.5)
        rr = cost["net_rr"]
        self.assertAlmostEqual(cost["breakeven_wr_pct"], 100.0 / (1.0 + rr), places=9)
        # a 1.5:1 geometry needs well under 50%, and a worse payoff needs more
        worse = M.cost_view(100.0, 95.0, 101.0, spread_rt=0.5)
        self.assertGreater(worse["breakeven_wr_pct"], cost["breakeven_wr_pct"])

    def test_zones_follow_the_documented_lines(self):
        tight = M.cost_view(100.0, 99.0, 101.5, spread_rt=0.55)      # 55% of 1R
        self.assertEqual(tight["zone"], "red")
        mid = M.cost_view(100.0, 98.0, 103.0, spread_rt=0.55)        # 27.5%
        self.assertEqual(mid["zone"], "red")
        ok = M.cost_view(100.0, 95.0, 107.5, spread_rt=0.55)         # 11%
        self.assertEqual(ok["zone"], "amber")
        good = M.cost_view(100.0, 90.0, 115.0, spread_rt=0.55)       # 5.5%
        self.assertEqual(good["zone"], "green")

    def test_a_live_spread_above_the_median_is_reported_separately(self):
        cost = M.cost_view(100.0, 95.0, 107.5, spread_rt=0.55, spread_now=1.4)
        self.assertAlmostEqual(cost["share_now_pct"], 28.0)
        self.assertEqual(cost["zone"], "red")

    def test_bad_geometry_returns_no_verdict(self):
        self.assertFalse(M.cost_view(100.0, 100.0, 101.0)["ok"])
        self.assertFalse(M.cost_view(None, 95.0, 101.0)["ok"])


# ── 3. the plan ─────────────────────────────────────────────────────────────
class Plan(unittest.TestCase):
    def test_the_stop_clears_the_tested_level(self):
        # level $10 below the entry, ATR 2.4, clearance 0.5 -> risk = 10 + 1.2
        plan_out = M.plan("BUY", 3580.0, 2.4, level=3570.0)
        self.assertTrue(plan_out["ok"])
        self.assertAlmostEqual(plan_out["risk"], 11.2, places=6)
        self.assertAlmostEqual(plan_out["stop"], 3568.8, places=6)
        self.assertEqual([r for r in plan_out["reasons"] if "clear the tested level" in r], [])

    def test_a_stop_inside_the_level_is_refused(self):
        plan_out = M.plan("BUY", 3580.0, 2.4, level=3570.0, stop=3572.0)
        self.assertTrue(any("clear the tested level" in r for r in plan_out["reasons"]))
        self.assertEqual(plan_out["verdict"], "no trade")

    def test_a_level_on_the_winning_side_is_not_a_stop_constraint(self):
        # SELL with the floor far below the entry: the floor is not the tested edge.
        plan_out = M.plan("SELL", 3580.0, 2.4, level=3550.0)
        self.assertTrue(plan_out["ok"])
        self.assertEqual([r for r in plan_out["reasons"] if "clear the tested level" in r], [])

    def test_the_target_defaults_to_the_bot_ratio_on_the_actual_risk(self):
        plan_out = M.plan("SELL", 3580.0, 2.4, level=3585.0)
        self.assertAlmostEqual(plan_out["target"],
                              3580.0 - P.RR_TARGET * plan_out["risk"], places=6)

    def test_an_explicit_target_on_the_wrong_side_is_flagged_and_replaced(self):
        plan_out = M.plan("BUY", 3580.0, 2.4, target=3500.0)
        self.assertTrue(any("wrong side" in r for r in plan_out["reasons"]))
        self.assertGreater(plan_out["target"], 3580.0)

    def test_an_over_priced_geometry_is_no_trade(self):
        # a 1 ATR stop pays 23% of 1R at $0.55 — over the live 20% veto
        plan_out = M.plan("BUY", 3580.0, 2.4, stop=3577.6)
        self.assertEqual(plan_out["verdict"], "no trade")
        self.assertTrue(any("vetoes" in r for r in plan_out["reasons"]))

    def test_bot_gate_verdict_is_context_and_never_changes_the_verdict(self):
        setup = {"ok": True, "BUY": {"passed": 5, "total": 9, "ready": False,
                                     "gates": [{"name": "Level tested", "ok": False},
                                               {"name": "RSI window", "ok": False}],
                                     "nearest_miss": "Level tested"}}
        plan_out = M.plan("BUY", 3580.0, 2.4, level=3570.0)
        before = plan_out["verdict"]
        M.attach_bot_view(plan_out, setup, "BUY")
        self.assertEqual(plan_out["verdict"], before)
        self.assertFalse(plan_out["bot_view"]["ready"])
        self.assertIn("would NOT enter", plan_out["bot_view"]["text"])
        self.assertIn("Level tested", plan_out["bot_view"]["missing"])

    def test_a_missing_setup_read_says_so_instead_of_guessing(self):
        plan_out = M.plan("BUY", 3580.0, 2.4)
        M.attach_bot_view(plan_out, {"ok": False}, "BUY")
        self.assertFalse(plan_out["bot_view"]["ok"])
        self.assertIn("unavailable", plan_out["bot_view"]["text"])

    def test_no_bar_means_no_plan_rather_than_a_guess(self):
        for side in ("BUY", "SELL"):
            self.assertFalse(M.plan(side, None, None)["ok"])
        self.assertFalse(M.plan("HOLD", 3580.0, 2.4)["ok"])


# ── 4. the daily-break clock ────────────────────────────────────────────────
class Clock(unittest.TestCase):
    def _closure(self, close=(21, 58), reopen=(23, 0), ok=True):
        return {"ok": ok, "source": "observed", "close_tod": close, "reopen_tod": reopen,
                "samples": 5, "last_break": {"at": T0, "close": close, "reopen": reopen},
                "detail": "observed"}

    def test_open_guard_and_closed_states(self):
        closure = self._closure()
        at = lambda h, m: datetime(2026, 11, 26, h, m)
        self.assertEqual(M.session_clock(at(15, 0), closure)["state"], "open")
        self.assertEqual(M.session_clock(at(21, 40), closure)["state"], "guard")
        self.assertEqual(M.session_clock(at(22, 30), closure)["state"], "closed")

    def test_a_window_wrapping_midnight_still_closes(self):
        closure = self._closure(close=(23, 40), reopen=(0, 20))
        self.assertEqual(M.session_clock(datetime(2026, 11, 26, 23, 55), closure)["state"], "closed")
        self.assertEqual(M.session_clock(datetime(2026, 11, 26, 23, 20), closure)["state"], "guard")
        self.assertEqual(M.session_clock(datetime(2026, 11, 26, 12, 0), closure)["state"], "open")

    def test_no_signature_is_unknown_not_open(self):
        clock = M.session_clock(datetime(2026, 11, 26, 12, 0), {"ok": False, "detail": "none"})
        self.assertEqual(clock["state"], "unknown")
        self.assertIn("none", clock["detail"])

    def test_the_signature_is_the_mode_of_recent_holes(self):
        rows, px = [], 3580.0
        day = 0
        for day in range(6):
            base = datetime(2026, 11, 20 + day, 8, 0)
            for i in range(600):                      # 10 h of bars
                ts = base + timedelta(minutes=i)
                rows.append({"Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                             "Close": str(px), "High": str(px + 1), "Low": str(px - 1)})
            # a 62-min hole at 21:58 -> 23:00 only exists if the bars reach there;
            # instead place the hole right after the block for two of the days
            if day >= 4:
                rows.append({"Timestamp": (base + timedelta(minutes=600 + 62))
                             .strftime("%Y-%m-%d %H:%M:%S"),
                             "Close": str(px), "High": str(px + 1), "Low": str(px - 1)})
        closure = M.observed_closure(rows)
        self.assertTrue(closure["ok"])
        self.assertEqual(closure["close_tod"], (17, 59))     # mode of the holes (08:00+600min 22:00? )
        self.assertEqual(closure["source"], "observed")

    def test_a_short_tape_has_no_signature(self):
        self.assertFalse(M.observed_closure(tape(30))["ok"])


# ── 5. the private journal ──────────────────────────────────────────────────
class Journal(unittest.TestCase):
    def row(self, **over):
        base = {"side": "BUY", "manual_entry": "3580.63", "reason_code": "level_retest",
                "contemporaneous_action": "took_it", "timestamp_utc": "2026-11-26 10:00:00"}
        base.update(over)
        return base

    def test_a_complete_row_is_ordered_by_the_schema(self):
        row, problems = M.journal_row(self.row())
        self.assertEqual(problems, [])
        self.assertEqual(tuple(row), M.JOURNAL_FIELDS)

    def test_the_five_required_fields_are_enforced(self):
        for missing in M.JOURNAL_REQUIRED:
            data = self.row()
            data.pop(missing, None)
            row, problems = M.journal_row(data)
            self.assertTrue(any(missing in p for p in problems), missing)

    def test_an_extra_credential_shaped_field_is_refused(self):
        row, problems = M.journal_row(self.row(broker_login="12345"))
        self.assertTrue(any("account identifier" in p for p in problems))
        self.assertTrue(any("unknown field" in p for p in problems))

    def test_the_allowlisted_notes_field_is_not_mistaken_for_an_identifier(self):
        row, problems = M.journal_row(
            self.row(notes_without_account_identifiers="clean retest"))
        self.assertEqual(problems, [])
        self.assertEqual(row["notes_without_account_identifiers"], "clean retest")

    def test_an_unknown_side_is_refused(self):
        row, problems = M.journal_row(self.row(side="LONG"))
        self.assertTrue(any("side must be" in p for p in problems))

    def test_writing_inside_the_repo_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "journal.jsonl")
            ok, detail = M.append_journal(target, {}, repo_root=tmp)
            self.assertFalse(ok)
            self.assertIn("refusing", detail)
            self.assertFalse(os.path.exists(target))

    def test_one_row_one_line_when_it_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = os.path.join(tmp, "data", "journal.jsonl")
            row, _ = M.journal_row(self.row())
            ok, detail = M.append_journal(outside, row, repo_root=os.path.join(tmp, "repo"))
            self.assertTrue(ok, detail)
            ok2, _ = M.append_journal(outside, row, repo_root=os.path.join(tmp, "repo"))
            self.assertTrue(ok2)
            with open(outside, encoding="utf-8") as fh:
                lines = [line for line in fh.read().splitlines() if line]
            self.assertEqual(len(lines), 2)
            self.assertEqual(list(json.loads(lines[0])), list(M.JOURNAL_FIELDS))


# ── 6. the whole read ───────────────────────────────────────────────────────
class Read(unittest.TestCase):
    def test_the_read_produces_both_sides_and_the_honest_footer(self):
        read = M.read(log_rows=tape(), quotes=[{"spread": "0.49", "n_ok": "6"}],
                      spec=spec(), now=datetime(2026, 11, 26, 11, 59))
        self.assertTrue(read["ok"])
        self.assertAlmostEqual(read["spread_now"], 0.49)
        self.assertEqual(set(read["plans"]), {"BUY", "SELL"})
        self.assertEqual(read["measured"]["box_cleared"], 0)
        self.assertIn("negative", read["measured"]["line"])
        self.assertIn("no edge", read["measured"]["line"].lower())
        self.assertEqual(read["journal"]["required"], list(M.JOURNAL_REQUIRED))
        self.assertTrue(read["cost_ruler"]["ok"])

    def test_an_empty_tape_degrades_instead_of_raising(self):
        read = M.read(log_rows=[], quotes=[], spec=spec())
        self.assertFalse(read["ok"])
        # both sides are present but refused — never a plan invented from no bars
        self.assertEqual(set(read["plans"]), {"BUY", "SELL"})
        self.assertFalse(any(plan["ok"] for plan in read["plans"].values()))
        self.assertEqual(read["clock"]["state"], "unknown")

    def test_a_stale_or_flagged_quote_is_not_used_as_the_live_spread(self):
        read = M.read(log_rows=tape(), quotes=[{"spread": "0.40", "n_ok": "6", "flags": "STALE"}],
                      spec=spec(), now=datetime(2026, 11, 26, 11, 59))
        self.assertIsNone(read["spread_now"])

    def test_the_missing_spec_falls_back_to_the_documented_constants(self):
        facts = M.load_spec("/nonexistent-directory")
        self.assertEqual(facts["source"], "default")
        self.assertEqual(facts["contract_size"], M.CONTRACT_SIZE)
        self.assertEqual(facts["volume_min"], M.VOLUME_MIN)

    def test_the_captured_spec_is_read_from_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, M.SPEC_FILE), "w", encoding="utf-8") as fh:
                json.dump({"captured_utc": "2026-11-26 13:57:01",
                           "decoded": {"account_kind": "REAL"},
                           "account": {"leverage": 500},
                           "symbol_info": {"trade_contract_size": 100.0,
                                           "volume_min": 0.01, "volume_step": 0.001,
                                           "volume_max": 50.0, "point": 0.01}}, fh)
            facts = M.load_spec(tmp)
        self.assertEqual(facts["source"], "captured")
        self.assertEqual(facts["leverage"], 500.0)
        self.assertEqual(facts["account_kind"], "REAL")

    def test_the_module_never_imports_the_engine(self):
        with open(os.path.join(ROOT, "manual_plan.py"), encoding="utf-8") as fh:
            body = fh.read()
        self.assertNotIn("import engine", body)
        self.assertNotIn("from engine", body)
        self.assertNotIn("import trade_filter", body)


class CliDefaults(unittest.TestCase):
    """A bare checkout must work, and the journal must never default into the repo."""

    def test_the_data_dir_falls_back_to_the_checkout_but_the_journal_does_not(self):
        env = {"PATH": os.environ.get("PATH", ""), "HOME": "/tmp/fake-home"}
        env.pop("GOLD_DATA_DIR", None)
        code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r);"
                "import manual_trade as T;"
                "print(T.DATA_DIR); print(T.JOURNAL_FILE)"
                % (ROOT, os.path.join(ROOT, "tools")))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=env, cwd="/tmp")
        self.assertEqual(out.returncode, 0, out.stderr)
        data_dir, journal = out.stdout.strip().splitlines()[:2]
        # In a bare checkout there is no /opt/gold, so the tool reads where it stands...
        self.assertEqual(data_dir, ROOT)
        # ...but a filled journal is private, so it is NOT written under the checkout.
        self.assertFalse(M.inside_repo(journal, ROOT), journal)
        self.assertTrue(journal.endswith("manual_trade_journal.jsonl"))


class DashboardRender(unittest.TestCase):
    """The tab must render, and must never expose a form or a send button."""

    def test_the_manual_tab_renders_display_only(self):
        # The data directory is read at import time, so set it BEFORE importing.
        os.environ["GOLD_DATA_DIR"] = ROOT
        try:
            import dashboard
        except Exception as exc:                  # Flask is optional in a bare checkout
            self.skipTest(f"dashboard not importable here: {exc}")
        html = dashboard.app.test_client().get("/?tab=manual").get_data(as_text=True)
        # These strings are inside <div id="panel-manual">, so they are rendered
        # whether or not the tab is the one selected — this is a render test.
        for needle in ("Manual Trade", 'id="panel-manual"',
                       "Manual trade — size it, cost it, then decide",
                       "your numbers:",
                       "can your stop still be enforced",
                       "If you risk", "Record the decision before the outcome",
                       "No edge", "'manual'", "the bot reads"):
            self.assertIn(needle, html)
        # The parallel Manual desk session added its own ?tab=desk panel; the
        # TABS list must contain both display-only tabs in this merged tree.
        self.assertIn("var TABS = ['simple', 'journal', 'chart', 'boxes', 'manual', 'desk', "
                      "'readiness', 'details']", html)
        panel = html[html.index('id="panel-manual"'):html.index("END MANUAL TRADE")]
        # Display-only: no form, no input, no button inside the panel at all.
        self.assertNotIn("<form", panel)
        self.assertNotIn("<input", panel)
        self.assertNotIn("<button", panel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
