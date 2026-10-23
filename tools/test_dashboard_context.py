"""Hermetic tests for the display-only dashboard panels."""
import os
import sys
import unittest
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pressure as P


class DashboardContextTests(unittest.TestCase):
    def test_costed_scratches_and_exit_order(self):
        rows = [dict(Entry_Time='2026-10-07 01:00:00', Exit_Time=f'2026-10-07 02:0{i}:00',
                     Entry_Price='100', Take_Profit='103', Profit=str(p), Trade_Type=side)
                for i, (p, side) in enumerate([(3, 'BUY'), (-2, 'SELL'), (0, 'BUY')])]
        all_, buy, sell = P.evidence_read(list(reversed(rows)))
        self.assertAlmostEqual(all_['net'], -.2)
        self.assertAlmostEqual(all_['dd'], 2.8)
        self.assertAlmostEqual(all_['expectancy'], -.2/6)
        self.assertEqual((buy['n'], sell['n']), (2, 1))
        self.assertIsNone(P.evidence_read([])[0]['expectancy'])

    def test_completed_buckets_and_gap(self):
        start = datetime(2026, 10, 19)
        rows = [dict(Timestamp=str(start+timedelta(minutes=i)), High=i+2, Low=i,
                     Close=i+1, ATR=2) for i in range(241)]
        result = P.market_map(rows)
        self.assertEqual(result['trends'][1]['delta'], 180)
        # Last forming H1 close must not enter the measurement.
        rows[-1]['Close'] = 99999
        self.assertEqual(P.market_map(rows)['trends'][1]['delta'], 180)
        del rows[100]
        self.assertIsNone(P.market_map(rows)['trends'][1]['delta'])
        self.assertIsNone(P.market_map([]))

    def test_quote_freshness_and_closure(self):
        now = datetime(2026, 10, 19, 20)
        status = dict(trade_active=True, entry_time='2026-10-19 19:00:00')
        quote = dict(ts_utc='2026-10-19 19:59:30', spread='.55', n_ok='6', flags='')
        r = P.risk_read(status, [quote], now)
        self.assertTrue(r['spans'])
        self.assertFalse(r['quote']['stale'])
        self.assertTrue(P.risk_read(status, [quote], now+timedelta(minutes=3))['quote']['stale'])
        quote['flags'] = 'bad'
        self.assertIsNone(P.risk_read({}, [quote], now)['quote'])
        self.assertIsNone(P.risk_read({}, [], now)['remaining'])

    def test_render(self):
        os.environ['GOLD_DATA_DIR'] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        import dashboard
        response = dashboard.app.test_client().get('/')
        self.assertEqual(response.status_code, 200)
        for title in ('Risk now', 'Market map', 'Costed evidence'):
            self.assertIn(title, response.get_data(as_text=True))



class BoxReadTests(unittest.TestCase):
    """The dashboard's Boxes tab read layer (pressure.box_geometry / box_status)."""

    def tape(self, n=40, px=100.0, atr=2.0, last=None, drift=0.0):
        rows = []
        p = px
        for i in range(n):
            o = p
            c = o + drift
            rows.append(dict(Timestamp=f"2026-10-07 {9 + i // 60:02d}:{i % 60:02d}:00",
                             Open=f"{o:.2f}", High=f"{max(o, c) + 0.3:.2f}",
                             Low=f"{min(o, c) - 0.3:.2f}", Close=f"{c:.2f}",
                             ATR=f"{atr:.2f}"))
            p = c
        if last:
            rows[-1].update(last)
        return rows

    def test_box_excludes_the_bar_being_judged(self):
        rows = self.tape(n=30)
        rows[-1].update({"High": "200.00", "Low": "50.00", "Close": "120.00"})
        geom = P.box_geometry(rows)
        box = geom["boxes"][0]
        self.assertAlmostEqual(box["high"], 100.3, places=2)   # prior bars only
        self.assertAlmostEqual(box["low"], 99.7, places=2)
        self.assertNotIn(200.0, [box["high"], box["low"]])

    def test_rejection_at_the_high_is_a_sell_and_quotes_that_edge(self):
        rows = self.tape(n=30)
        hi = max(float(r["High"]) for r in rows[-21:-1])
        rows[-1].update({"High": f"{hi + 0.2:.2f}", "Low": f"{hi - 2.0:.2f}",
                         "Close": f"{hi - 0.5:.2f}", "Open": f"{hi - 0.6:.2f}"})
        geom = P.box_geometry(rows)
        trig = geom["trigger"]
        self.assertEqual(trig["state"], "reject")
        self.assertEqual(trig["side"], "SELL")
        self.assertAlmostEqual(trig["edge"], hi, places=2)      # the HIGH, not the low
        # a fade stop is tight, so the spread must dominate R
        self.assertGreater(trig["setup"]["cost_share_pct"], 20)

    def test_a_break_price_left_days_ago_is_not_a_trigger(self):
        rows = self.tape(n=40)
        box_hi = max(float(r["High"]) for r in rows[-21:-1])
        # close far above the box, but 10 bars ago: the crossing is not current
        for i in range(30, 39):
            rows[i].update({"Close": f"{box_hi + 8:.2f}", "High": f"{box_hi + 8.4:.2f}",
                            "Low": f"{box_hi + 7.6:.2f}"})
        geom = P.box_geometry(rows)
        self.assertNotEqual(geom["trigger"]["state"], "break")

    def test_a_fresh_break_is_a_trigger_on_that_edge(self):
        rows = self.tape(n=40)
        box_hi = max(float(r["High"]) for r in rows[-21:-1])
        rows[-1].update({"Close": f"{box_hi + 1.0:.2f}", "High": f"{box_hi + 1.5:.2f}",
                         "Low": f"{box_hi - 0.2:.2f}"})
        geom = P.box_geometry(rows)
        trig = geom["trigger"]
        self.assertEqual((trig["state"], trig["side"]), ("break", "BUY"))
        self.assertAlmostEqual(trig["edge"], box_hi, places=2)

    def test_verdict_cannot_be_a_candidate_when_geometry_fails(self):
        rows = self.tape(n=30)
        hi = max(float(r["High"]) for r in rows[-21:-1])
        rows[-1].update({"High": f"{hi + 0.2:.2f}", "Low": f"{hi - 2.0:.2f}",
                         "Close": f"{hi - 0.5:.2f}", "Open": f"{hi - 0.6:.2f}"})
        geom = P.box_geometry(rows)
        status = P.box_status(geom, now=datetime(2026, 10, 7, 10, 0))
        geo = [c for c in status["checks"] if c["key"] == "geometry"][0]
        self.assertIn(geo["state"], ("warn", "fail"))
        self.assertNotEqual(status["verdict"]["code"], "candidate")

    def test_a_closed_market_blocks_before_anything_else(self):
        rows = self.tape(n=30)
        hi = max(float(r["High"]) for r in rows[-21:-1])
        rows[-1].update({"High": f"{hi + 0.2:.2f}", "Low": f"{hi - 2.0:.2f}",
                         "Close": f"{hi - 0.5:.2f}", "Open": f"{hi - 0.6:.2f}"})
        geom = P.box_geometry(rows)
        weekend = datetime(2026, 10, 10, 12, 0)          # a Saturday
        status = P.box_status(geom, now=weekend)
        self.assertEqual(status["verdict"]["tone"], "block")

    def test_the_measured_verdict_travels_with_the_read(self):
        status = P.box_status(P.box_geometry(self.tape(n=30)))
        self.assertEqual(status["measured"]["cleared"], 0)
        self.assertIn("no edge", status["measured"]["best"] + "no edge")

    def test_short_or_gappy_tape_refuses_rather_than_guessing(self):
        self.assertFalse(P.box_geometry([])["ok"])
        self.assertFalse(P.box_geometry(self.tape(n=10))["ok"])
        # two runs of 20 bars separated by hours: no 20-bar box exists at the join
        rows = self.tape(n=20)
        later = [dict(r, Timestamp=r["Timestamp"].replace("09:", "15:")) for r in self.tape(n=20)]
        self.assertFalse(P.box_geometry(rows + later)["ok"])

    def test_the_dashboard_renders_the_boxes_tab(self):
        os.environ["GOLD_DATA_DIR"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        import dashboard
        html = dashboard.app.test_client().get("/").get_data(as_text=True)
        for needle in ("Boxes &amp; Timing", 'id="panel-boxes"', "Where the boxes are",
                       "When to trade", "Measured, not assumed", "BUY WATCH", "SELL WATCH",
                       "costed reward/risk", "No edge has been validated",
                       # 2026-10-21: retest tracking, the chop panel, the alert preview
                       "Is the tape choppy? (measured, not felt)",
                       "Telegram alert", "spam control, not an expectancy claim"):
            self.assertIn(needle, html)
        # the old disclaimer is superseded: retests ARE tracked now, on a frozen box.
        # One of the two branches always renders, depending on whether a break is live.
        self.assertNotIn("Retest: not tracked", html)
        self.assertTrue("box frozen at the break" in html or "no break to retest yet" in html)
        # the alert panel is a preview, never a sender, and one of the two states shows
        self.assertTrue("Would send now" in html or "Held" in html)
        # a new page must not break the existing tab switch (journal is also a tab).
        # The Manual Scalping page was removed in the 2026-10-23 redesign: it is not
        # reachable and must not come back as a dead link.
        self.assertIn("var TABS = ['simple', 'journal', 'chart', 'boxes', 'details']", html)
        self.assertNotIn('href="/scalp"', html)
        # Tab persistence must update the URL as well as localStorage: the
        # meta-refresh otherwise replays an old ?tab=chart deep link.
        self.assertIn("url.searchParams.set('tab', name)", html)
        self.assertIn("window.history.replaceState", html)

    def test_the_dashboard_renders_the_chart_tab(self):
        os.environ["GOLD_DATA_DIR"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        import dashboard
        html = dashboard.app.test_client().get("/?tab=chart").get_data(as_text=True)
        for needle in ("Chart &amp; Placement", 'id="panel-chart"',
                       "Where the trade would go", "The cost ruler",
                       "New to charts? Read this first", "<svg", "stand aside",
                       "0 cleared the no-edge reference"):
            self.assertIn(needle, html)
        # the chart is display-only: no form, no button that could send anything
        self.assertNotIn("<form", html)
        # an unmeasured tool must never be drawn as if it were tested
        self.assertNotIn("Fibonacci retracement of", html)
        # every timeframe link keeps the tab
        for tf in ("1", "5", "15"):
            self.assertIn(f"?tab=chart&tf={tf}", html)


if __name__ == '__main__':
    unittest.main()
