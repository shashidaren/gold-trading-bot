#!/usr/bin/env python3
"""Hermetic tests for the 🚦 Readiness tab and its display-only read layer.

The timeline is a *reference view*: it must never import the engine, write a
file, place an order, or be able to open the LIVE gate on its own.  Tests inject
a fixed clock and a fake scorecard so no repo data (and no Flask install) is
needed for the pure-logic cases.
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import readiness as RD  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)


def check(cid, status="TODO", area="engineering", evidence="next action",
          blocking=True, title=None):
    return dict(id=cid, area=area, title=title or cid, status=status,
                evidence=evidence, blocking=blocking)


def progress(**kw):
    base = dict(complete_days=11, target_days=14, weekends=1,
                target_weekends=2, rows=35571, median_spread=0.55,
                offsets=[7200, 10800], newest_ts=NOW.timestamp(),
                filling_mode=2, filling_flags=["IOC"])
    base.update(kw)
    return base


class TimelineTests(unittest.TestCase):
    def test_elapsed_days_is_a_floor_not_a_rounding_guess(self):
        self.assertEqual(RD._elapsed_days(RD.LOG_START, NOW), 55)
        self.assertEqual(RD._elapsed_days(RD.CUTOVER, NOW), 20)
        self.assertEqual(RD._elapsed_days(NOW, NOW), 0)
        # A clock before the reference point must not produce a negative day count.
        self.assertEqual(RD._elapsed_days(NOW, RD.LOG_START), 0)

    def test_days_left_counts_calendar_days_to_the_gate_not_trading_days(self):
        self.assertEqual(RD._ceil_days(RD.US_DST_END, NOW), 6)
        self.assertEqual(RD._ceil_days(RD.REGISTERED_END, NOW), 37)
        self.assertEqual(RD._ceil_days(NOW, NOW), 0)
        self.assertEqual(RD._ceil_days(NOW, NOW.replace(day=27)), 0)

    def test_next_weekend_end_lands_on_a_sunday_and_never_in_the_past(self):
        for day in (26, 27, 28, 29, 30, 31):
            d = RD._next_weekend_end(datetime(2026, 10, day, 12, tzinfo=UTC))
            self.assertEqual(d.weekday(), 6, day)  # Sunday
            self.assertGreater(d, datetime(2026, 10, day, 12, tzinfo=UTC))

    def test_timeline_has_elapsed_completed_pending_and_conditional_rows(self):
        rows = RD.build_timeline(NOW, progress(), {"pass": 9, "todo": 8,
                                                   "manual": 3, "total": 20})
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id["forward_test"]["state"], "done")
        self.assertEqual(by_id["structstop_era"]["state"], "active")
        self.assertEqual(by_id["dst_us"]["state"], "active")
        # G1 was signed on 2026-10-27 (docs/REVIEW-2026-10-27-g1-decision.md): the row goes done and
        # the owner's remaining action moves to the next row, A2 — the deploy itself.
        self.assertEqual(by_id["g1"]["state"], "done")
        self.assertEqual(by_id["a2"]["state"], "pending")
        self.assertIn("no open position", by_id["a2"]["detail"])
        self.assertEqual(by_id["edge_review"]["state"], "conditional")
        self.assertEqual(by_id["live_review"]["state"], "conditional")
        self.assertIn("d elapsed", by_id["forward_test"]["days_text"])
        self.assertIn("d left", by_id["window_15"]["days_text"])
        self.assertIn("–", by_id["edge_review"]["days_text"])
        self.assertNotIn("None", " ".join(str(v) for r in rows for v in r.values()))

    def test_completed_sample_row_goes_done_only_when_targets_are_met(self):
        counts = {"pass": 9, "todo": 8, "manual": 3, "total": 20}
        short = {r["id"]: r for r in RD.build_timeline(NOW, progress(), counts)}
        full = {r["id"]: r for r in RD.build_timeline(
            NOW, progress(complete_days=14, weekends=2), counts)}
        self.assertEqual(short["cost_sample"]["state"], "active")
        self.assertEqual(full["cost_sample"]["state"], "done")


class ViewTests(unittest.TestCase):
    def test_real_scorecard_wires_into_the_view_without_injection(self):
        view = RD.readiness_view(root=RD.ROOT, now=NOW)
        self.assertTrue(view["ok"], view.get("reason"))
        self.assertEqual(view["gate"]["label"], "CLOSED")
        self.assertEqual(view["gate"]["counts"]["total"], 20)
        self.assertEqual(view["gate"]["counts"]["pass"], 11)   # B2: broker_be + broker_time_stop
        self.assertEqual(view["gate"]["counts"]["todo"], 6)
        self.assertEqual(view["gate"]["counts"]["manual"], 3)
        self.assertEqual(len(view["checks"]), 20)
        self.assertEqual(len(view["pending_checks"]), 9)
        self.assertTrue(view["completed"])
        self.assertTrue(view["blockers"])
        self.assertIn("$0.55", view["progress"]["median_spread_text"])
        self.assertIn("not deadlines", view["disclaimer"])

    def test_all_pass_checks_open_the_gate_but_never_imply_g2_approval(self):
        checks = [check("a", "PASS"), check("b", "PASS")]
        view = RD.readiness_view(now=NOW, checks=checks, progress=progress())
        self.assertTrue(view["gate"]["open"])
        self.assertEqual(view["gate"]["label"], "OPEN")
        self.assertIn("G2 owner approval", view["gate"]["headline"])
        self.assertEqual(view["pending_checks"], [])

    def test_a_non_blocking_todo_cannot_open_the_live_gate(self):
        checks = [check("a", "PASS"), check("b", "TODO", blocking=False)]
        view = RD.readiness_view(now=NOW, checks=checks, progress=progress())
        self.assertTrue(view["gate"]["open"])  # non-blocking, by definition
        self.assertEqual(len(view["pending_checks"]), 1)  # still shown as pending

    def test_missing_data_is_reported_not_faked(self):
        view = RD.readiness_view(now=NOW, checks=[], progress={})
        self.assertFalse(view["ok"])
        self.assertEqual(view["gate"]["label"], "CLOSED")
        self.assertIn("not deadlines", view["disclaimer"])

    def test_missing_median_spread_renders_a_dash_not_a_crash(self):
        view = RD.readiness_view(now=NOW, checks=[check("a")],
                                 progress=progress(median_spread=None, newest_ts=None))
        self.assertEqual(view["progress"]["median_spread_text"], "—")
        self.assertEqual(view["elapsed"]["as_of_data"], "—")

    def test_cli_json_is_serialisable(self):
        import json
        view = RD.readiness_view(now=NOW, checks=[check("a")], progress=progress())
        self.assertIn("TIMELINE (days)", RD._text(view))
        self.assertTrue(json.dumps(view))


class DashboardWiringTests(unittest.TestCase):
    """The tab must render even when the trading read layer is unavailable."""

    @classmethod
    def setUpClass(cls):
        os.environ["GOLD_DATA_DIR"] = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        import dashboard
        cls.dashboard = dashboard

    def setUp(self):
        # Inject a cheap deterministic view; no quote CSV scan on every render.
        self.real_view = RD.readiness_view
        self.view = self.real_view(now=NOW, checks=[check("a")], progress=progress())
        self.dashboard._readiness_cache.update({"at": 1e18, "view": self.view})
        self.real_pr = self.dashboard.PR

    def tearDown(self):
        self.dashboard.PR = self.real_pr
        self.dashboard._readiness_cache.update({"at": 0.0, "view": None})

    def test_nav_button_panel_and_js_tab_exist(self):
        with open(os.path.join(RD.ROOT, "dashboard.py"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("id=\"tab-readiness\"", html)
        self.assertIn("id=\"panel-readiness\"", html)
        self.assertIn("'readiness'", html.split("var TABS =")[1].split(";")[0])
        # the one-shot refresh flag must not replay on the 15s meta refresh
        self.assertIn("url.searchParams.delete('readiness')", html)

    def test_page_renders_the_timeline_completed_and_pending(self):
        r = self.dashboard.app.test_client().get("/")
        self.assertEqual(r.status_code, 200)
        text = r.get_data(as_text=True)
        self.assertIn("Live readiness — timeline in days", text)
        self.assertIn("Timeline in days", text)
        self.assertIn("Completed (", text)
        self.assertIn("owner / host blockers", text)
        self.assertIn("G1 — pre-registration sign-off", text)
        self.assertIn("A2 — the deploy commit itself", text)
        self.assertIn("LIVE-gate checks (read-only)", text)
        self.assertIn("not deadlines", text)

    def test_readiness_tab_survives_a_broken_pressure_read(self):
        self.dashboard.PR = None
        r = self.dashboard.app.test_client().get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Live readiness — timeline in days", r.get_data(as_text=True))

    def test_a_broken_readiness_layer_degrades_to_a_notice_not_a_500(self):
        self.dashboard._readiness_cache.update({"at": 0.0, "view": None})
        def broken(*a, **kw):
            raise RuntimeError("scorecard exploded")
        self.dashboard.RD.readiness_view = broken
        try:
            r = self.dashboard.app.test_client().get("/")
        finally:
            self.dashboard.RD.readiness_view = self.real_view
        self.assertEqual(r.status_code, 200)
        self.assertIn("Readiness view unavailable", r.get_data(as_text=True))

    def test_refresh_query_forces_a_new_read(self):
        calls = []
        def counted(*a, **kw):
            calls.append(1)
            return self.view
        self.dashboard.RD.readiness_view = counted
        try:
            client = self.dashboard.app.test_client()
            first = client.get("/")  # served from cache
            self.assertEqual(first.status_code, 200)
            self.assertEqual(calls, [])
            fresh = client.get("/?tab=readiness&readiness=refresh")  # explicit owner refresh
            self.assertEqual(fresh.status_code, 200)
            self.assertIn("Live readiness — timeline in days", fresh.get_data(as_text=True))
            self.assertEqual(len(calls), 1)
        finally:
            self.dashboard.RD.readiness_view = self.real_view


if __name__ == "__main__":
    unittest.main(verbosity=2)
