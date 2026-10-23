"""Flask integration tests for the separate, journal-only scalping page.

Run with Flask installed, e.g. `.venv/bin/python tools/test_scalp_dashboard.py`.
Market setup comes from the checked-in snapshot; every write goes to a temp dir.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["GOLD_DATA_DIR"] = ROOT

import dashboard  # noqa: E402


def ticket(**changes):
    payload = {
        "decision": "taken", "side": "BUY", "entry": "100", "stop": "95",
        "target": "110", "account_balance": "10000", "risk_pct": "1",
        "spread": "0.50", "contract_size": "100", "volume_step": "0.01",
        "timeframe": "M5", "setup": "synthetic retest", "notes": "route test",
    }
    payload.update(changes)
    return payload


class ScalpDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="scalp-dashboard-test-")
        self.old_path = dashboard.MANUAL_JOURNAL_FILE_PATH
        dashboard.MANUAL_JOURNAL_FILE_PATH = os.path.join(self.tmp.name, "manual.json")
        self.client = dashboard.app.test_client()
        with open(dashboard.TRADES_FILE_PATH, "rb") as handle:
            self.ledger_hash = hashlib.sha256(handle.read()).hexdigest()

    def tearDown(self):
        dashboard.MANUAL_JOURNAL_FILE_PATH = self.old_path
        self.tmp.cleanup()

    def assert_ledger_unchanged(self):
        with open(dashboard.TRADES_FILE_PATH, "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), self.ledger_hash)

    def test_main_dashboard_links_to_separate_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/scalp"', response.get_data(as_text=True))
        self.assertIn("Manual Scalping", response.get_data(as_text=True))

    def test_page_has_chart_ticket_health_and_no_auto_refresh(self):
        response = self.client.get("/scalp?tf=5")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for needle in ("Manual Scalping", "Risk ticket", "Manual decision journal",
                       "No order placement", "Price and structural levels", "<svg",
                       'action="/scalp/journal"', "/scalp?tf=1", "server recalculates on save"):
            self.assertIn(needle, html)
        self.assertNotIn('http-equiv="refresh"', html)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assert_ledger_unchanged()

    def test_invalid_ticket_is_not_written_and_inputs_survive(self):
        response = self.client.post("/scalp/journal", data=ticket(stop="101", setup="keep me"))
        self.assertEqual(response.status_code, 400)
        html = response.get_data(as_text=True)
        self.assertIn("Not recorded", html)
        self.assertIn("keep me", html)
        self.assertIn('value="101"', html)
        self.assertFalse(os.path.exists(dashboard.MANUAL_JOURNAL_FILE_PATH))
        self.assert_ledger_unchanged()

    def test_skip_taken_close_flow_and_ledger_isolation(self):
        skipped = self.client.post("/scalp/journal", data=ticket(
            decision="skipped", account_balance="10", setup="too small"))
        self.assertEqual(skipped.status_code, 302)
        taken = self.client.post("/scalp/journal", data=ticket())
        self.assertEqual(taken.status_code, 302)
        with open(dashboard.MANUAL_JOURNAL_FILE_PATH, encoding="utf-8") as handle:
            rows = json.load(handle)["entries"]
        self.assertEqual([row["status"] for row in rows], ["SKIPPED", "OPEN"])
        opened = rows[1]
        self.assertEqual(opened["lots"], 0.18)
        closed = self.client.post(f"/scalp/journal/{opened['id']}/close", data={
            "exit_price": "110", "exit_reason": "TP", "timeframe": "M5",
            "close_notes": "synthetic close",
        })
        self.assertEqual(closed.status_code, 302)
        page = self.client.get(closed.headers["Location"]).get_data(as_text=True)
        self.assertIn("CLOSED", page)
        self.assertIn("+171.00", page)
        self.assertIn("synthetic close", page)
        self.assertIn("No broker action was taken", page)
        self.assert_ledger_unchanged()

    def test_autosync_covers_helpers_without_widening_engine_restart(self):
        with open(os.path.join(ROOT, "tools", "autosync.sh"), encoding="utf-8") as handle:
            script = handle.read()
        self.assertIn("DASH_CHANGED=$(git diff --name-only HEAD \"$REMOTE_SHA\" -- dashboard.py pressure.py chart.py manual_scalp.py scalp_template.py", script)
        self.assertIn("CORE_CHANGED=$(git diff --name-only HEAD \"$REMOTE_SHA\" -- engine.py trade_filter.py", script)

    def test_close_cannot_be_replayed(self):
        self.client.post("/scalp/journal", data=ticket())
        opened = dashboard.MS.JournalStore(dashboard.MANUAL_JOURNAL_FILE_PATH).read()["rows"][0]
        url = f"/scalp/journal/{opened['id']}/close"
        self.assertEqual(self.client.post(url, data={"exit_price": "110", "timeframe": "M5"}).status_code, 302)
        replay = self.client.post(url, data={"exit_price": "109", "timeframe": "M5"})
        self.assertEqual(replay.status_code, 400)
        self.assert_ledger_unchanged()


if __name__ == "__main__":
    unittest.main()
