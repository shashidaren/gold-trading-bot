"""Hermetic tests for chart.py (the Chart & Placement tab's read layer).

Synthetic tapes only — no live CSVs, no wall clock. Pins the four things that
could silently lie:

  1. aggregation never invents a bar and flags the forming one;
  2. the pixel view never draws outside its own plot box, and an off-range
     level is pinned rather than dropped;
  3. the cost ruler's arithmetic is spread / risk, and it agrees with the
     documented $0.40 / $0.55 models;
  4. a placement card is only ever "watch"/"ready" when the geometry is
     actually worth taking, and the box chooser refuses a swing-sized box.

Run: python3 tools/test_manual_chart.py
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chart as C  # noqa: E402

T0 = datetime(2026, 10, 23, 6, 0)


def bar(minute, o, h, l, c, atr=1.5):
    ts = T0 + timedelta(minutes=minute)
    return {"Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "Open": str(o),
            "High": str(h), "Low": str(l), "Close": str(c), "ATR": str(atr)}


def tape(n=120, px=4000.0, step=0.2, span=1.0, atr=1.5, skip=()):
    out = []
    for k in range(n):
        if k in skip:
            continue
        o = px
        c = px + step
        out.append(bar(k, o, max(o, c) + span, min(o, c) - span, c, atr))
        px = c
    return out


def box(name, hi, lo, close, atr):
    return {"name": name, "high": hi, "low": lo, "width": hi - lo,
            "width_atr": (hi - lo) / atr,
            "dist_up_usd": hi - close, "dist_down_usd": close - lo,
            "dist_up_atr": (hi - close) / atr, "dist_down_atr": (close - lo) / atr}


class Parsing(unittest.TestCase):
    def test_bad_rows_are_dropped_not_coerced(self):
        rows = tape(10)
        rows.append({"Timestamp": "not-a-time", "Open": "1", "High": "2", "Low": "1", "Close": "2"})
        rows.append({"Timestamp": "2026-10-23 06:11:00", "Open": "", "High": "2",
                     "Low": "1", "Close": "2"})
        rows.append({"Timestamp": "2026-10-23 06:12:00", "Open": "1", "High": "nan",
                     "Low": "1", "Close": "2"})
        self.assertEqual(len(C.bars(rows)), 10)

    def test_duplicate_timestamps_collapse(self):
        rows = tape(5) + [dict(tape(5)[2], Close="9999")]
        out = C.bars(rows)
        self.assertEqual(len(out), 5)
        self.assertEqual(out[2]["c"], 9999.0)     # last writer wins, no duplicate bar

    def test_empty_input_is_safe(self):
        self.assertEqual(C.bars(None), [])
        v = C.view(rows=[])
        self.assertFalse(v["ok"])
        self.assertIn("warming up", v["reason"])


class Aggregation(unittest.TestCase):
    def test_five_minute_candle_is_the_union_of_its_minutes(self):
        rows = [bar(0, 100, 101, 99, 100.5), bar(1, 100.5, 103, 100, 102),
                bar(2, 102, 102.5, 98, 99), bar(3, 99, 100, 97, 99.5),
                bar(4, 99.5, 101, 99, 100)]
        cs = C.candles(C.bars(rows), group=5)
        self.assertEqual(len(cs), 1)
        c = cs[0]
        self.assertEqual((c["o"], c["h"], c["l"], c["c"]), (100, 103, 97, 100))
        self.assertFalse(c["partial"])              # 5 of 5 minutes present

    def test_a_forming_candle_is_flagged_partial(self):
        cs = C.candles(C.bars([bar(0, 100, 101, 99, 100), bar(1, 100, 101, 99, 100)]), group=5)
        self.assertEqual(len(cs), 1)
        self.assertTrue(cs[0]["partial"])

    def test_a_gap_does_not_bridge_two_sessions(self):
        """Missing minutes produce fewer candles; nothing is interpolated."""
        rows = [bar(0, 100, 101, 99, 100), bar(1, 100, 101, 99, 100),
                bar(2, 100, 101, 99, 100), bar(3, 100, 101, 99, 100),
                bar(4, 100, 101, 99, 100),
                # 60-minute hole, then five more minutes
                bar(65, 200, 201, 199, 200), bar(66, 200, 201, 199, 200)]
        cs = C.candles(C.bars(rows), group=5)
        self.assertEqual(len(cs), 2)
        self.assertEqual(cs[1]["o"], 200)          # no phantom candle at 201.. between
        self.assertNotEqual(cs[0]["c"], cs[1]["o"])

    def test_limit_keeps_the_newest(self):
        cs = C.candles(C.bars(tape(60)), group=5, limit=4)
        self.assertEqual(len(cs), 4)
        self.assertEqual(cs[0]["ts"], T0 + timedelta(minutes=40))


class Levels(unittest.TestCase):
    def test_shared_box_edges_are_merged_not_double_labelled(self):
        boxes = [box("20-bar level (engine's own)", 4004, 3996, 4000, 1.5),
                 box("last 1h (60 bars)", 4004, 3994, 4000, 1.5)]
        lvls = C.levels_from_boxes(boxes, close=4000)
        prices = [round(l["price"], 2) for l in lvls]
        self.assertEqual(len(prices), len(set(prices)))
        self.assertIn("engine", [l["kind"] for l in lvls])   # the important one survives

    def test_prior_day_is_labelled_high_and_low(self):
        lvls = C.levels_from_boxes([box("prior day 2026-10-22 (UTC)", 4126, 4021, 4022, 1.5)], 4022)
        labels = [l["label"] for l in lvls]
        self.assertTrue(any("high" in l.lower() for l in labels))
        self.assertTrue(any("low" in l.lower() for l in labels))


class View(unittest.TestCase):
    def setUp(self):
        self.v = C.view(rows=tape(120), width=900, height=360)

    def test_every_candle_is_inside_the_plot_box(self):
        v = self.v
        l, t, w, h = v["plot"]["l"], v["plot"]["t"], v["plot"]["w"], v["plot"]["h"]
        for k in v["candles"]:
            self.assertGreaterEqual(k["cx"], l - 0.01)
            self.assertLessEqual(k["x"] + k["w"], l + w + 0.01)
            self.assertGreaterEqual(k["y_high"], t - 0.01)
            self.assertLessEqual(k["y_low"], t + h + 0.01)
            self.assertGreaterEqual(k["body_h"], 1.0)
            self.assertLessEqual(k["y_top"] + k["body_h"], t + h + 0.01)

    def test_price_axis_is_ordered_top_to_bottom(self):
        ys = [t["y"] for t in self.v["ticks"]]
        self.assertGreaterEqual(len(ys), 3)
        # price up = y down, so ascending prices give descending pixel rows
        self.assertEqual(ys, sorted(ys, reverse=True))
        prices = [t["price"] for t in self.v["ticks"]]
        self.assertEqual(prices, sorted(prices))

    def test_an_offrange_level_is_pinned_to_the_edge_not_dropped(self):
        v = C.view(rows=tape(120), boxes=[box("prior day 2026-10-22 (UTC)", 9999, 1, 4024, 1.5)])
        day = [l for l in v["levels"] if l["kind"] == "day"]
        self.assertEqual(len(day), 2)
        self.assertTrue(all(not l["in_range"] for l in day))
        self.assertTrue(any(l.get("offscreen_above") for l in day))
        self.assertTrue(any(l.get("offscreen_above") is False for l in day))

    def test_bands_cover_the_whole_plot_without_overlap(self):
        bands = self.v["bands"]
        self.assertEqual(bands[0]["x0"], self.v["plot"]["l"])
        for a, b in zip(bands, bands[1:]):
            self.assertAlmostEqual(a["x1"], b["x0"], places=2)

    def test_blackout_windows_are_flagged_by_side(self):
        self.assertEqual(C._blackout_at(datetime(2026, 10, 23, 8, 0), 5), "buy")    # London, buys only
        self.assertEqual(C._blackout_at(datetime(2026, 10, 23, 13, 30), 5), "both")  # NY open
        self.assertIsNone(C._blackout_at(datetime(2026, 10, 23, 10, 0), 5))

    def test_a_flat_tape_does_not_divide_by_zero(self):
        flat = [bar(k, 4000, 4000, 4000, 4000, atr=1.5) for k in range(30)]
        v = C.view(rows=flat)
        self.assertTrue(v["ok"])
        self.assertGreater(v["y_max"], v["y_min"])


class CostRuler(unittest.TestCase):
    def test_share_is_spread_over_risk(self):
        r = C.cost_ruler(atr=1.0)
        row = next(x for x in r["rows"] if x["mult"] == 2.0)
        self.assertAlmostEqual(row["share"]["0.55"], 27.5, places=6)   # 0.55 / 2.00
        self.assertAlmostEqual(row["share"]["0.40"], 20.0, places=6)

    def test_minimum_stop_for_a_ten_percent_share(self):
        """R >= 10 x cost, the box doc's rule, expressed in ATR."""
        r = C.cost_ruler(atr=1.48)
        self.assertAlmostEqual(r["min_mult"]["0.55"], 0.55 / 0.10 / 1.48, places=6)
        self.assertAlmostEqual(r["min_mult"]["0.40"], 0.40 / 0.10 / 1.48, places=6)

    def test_zones_escalate_with_a_tighter_stop(self):
        r = C.cost_ruler(atr=1.0)
        zones = [x["zone"] for x in r["rows"]]
        shares = [x["share_pct"] for x in r["rows"]]
        self.assertEqual(zones[0], "red")
        self.assertNotEqual(zones[-1], "red")          # a wide stop is not the bad case
        self.assertEqual(shares, sorted(shares, reverse=True))

    def test_no_atr_means_no_ruler(self):
        self.assertFalse(C.cost_ruler(None)["ok"])
        self.assertFalse(C.cost_ruler(0)["ok"])


class BoxChoice(unittest.TestCase):
    def test_a_swing_sized_box_is_refused_and_explained(self):
        narrow = box("20-bar level (engine's own)", 4004, 3996, 4000, 1.5)   # 5.3 ATR
        wide = box("prior day 2026-10-22 (UTC)", 4126, 4021, 4022, 1.5)      # 70 ATR
        chosen, note = C.pick_box([wide, narrow], close=4022, atr=1.5)
        self.assertEqual(chosen["name"], narrow["name"])
        self.assertIn("swing trade", note)

    def test_the_nearest_usable_box_wins(self):
        near = box("last 1h (60 bars)", 4010, 4000, 4009, 1.5)
        far = box("last 4h (240 bars)", 4020, 3980, 4009, 1.5)   # 27 ATR — refused
        chosen, note = C.pick_box([far, near], close=4009, atr=1.5)
        self.assertEqual(chosen["name"], "last 1h (60 bars)")
        # the refused box is 8.7 ATR away, further than the chosen one's 0.7 —
        # so there is nothing a reader would have reached for first, no note
        self.assertIsNone(note)

    def test_no_boxes_is_safe(self):
        chosen, note = C.pick_box([], close=4000, atr=1.5)
        self.assertIsNone(chosen)
        self.assertTrue(note)


def card(side="BUY", **kw):
    base = {"side": side, "entry": 4004.0, "stop": 3992.0, "target": 4016.0,
            "risk": 12.0, "reward": 12.0, "gross_rr": 1.0, "net_rr": 0.95,
            "threshold": 4004.0, "reasons": [], "chasing": False, "confirmed": False,
            "state": "WAIT — no breakout close", "box": "20-bar level (engine's own)"}
    base.update(kw)
    return base


class PlanCards(unittest.TestCase):
    def test_a_target_under_one_r_is_never_a_setup(self):
        out = C.plan_cards([card()])[0]
        self.assertEqual(out["verdict"], "skip")
        self.assertTrue(any("0.95R" in r for r in out["reasons"]))

    def test_good_geometry_is_still_only_a_watch(self):
        out = C.plan_cards([card(net_rr=1.4)])[0]
        self.assertEqual(out["verdict"], "watch")
        self.assertFalse(out["reasons"])

    def test_a_confirmed_good_setup_carries_the_context_warning(self):
        out = C.plan_cards([card(net_rr=1.4, confirmed=True)])[0]
        self.assertEqual(out["verdict"], "ready")
        self.assertIn("context only", out["verdict_text"])

    def test_an_expensive_stop_is_named(self):
        out = C.plan_cards([card(net_rr=1.4, risk=2.0)])[0]   # $0.55 / $2 = 27.5% of R
        self.assertEqual(out["verdict"], "skip")
        self.assertTrue(any("28%" in r for r in out["reasons"]))   # 0.55 / 2.00 = 27.5%

    def test_the_other_side_blackout_is_not_printed(self):
        """A London BUY-only blackout must not tell a seller to stand aside."""
        out = C.plan_cards([card(side="SELL",
                                 reasons=["London Open & Early Session Kill-Zone blocks BUY"],
                                 net_rr=1.4)])[0]
        self.assertEqual(out["reasons"], [])
        buy = C.plan_cards([card(side="BUY",
                                 reasons=["London Open & Early Session Kill-Zone blocks BUY"],
                                 net_rr=1.4)])[0]
        self.assertTrue(buy["reasons"])

    def test_numbers_are_printed_even_when_the_verdict_is_skip(self):
        out = C.plan_cards([card()])[0]
        self.assertIsNotNone(out["entry"])
        self.assertIsNotNone(out["stop"])
        self.assertIsNotNone(out["target"])
        self.assertIn("below", out["stop_sentence"])       # BUY stop sits below the box


class VerdictText(unittest.TestCase):
    def test_unavailable_reads_do_not_crash(self):
        self.assertFalse(C.plain_verdict(None)["ok"])
        self.assertFalse(C.plain_verdict({"ok": False, "reason": "x"})["ok"])

    def test_failing_checks_are_named(self):
        st = {"ok": True, "verdict": {"tone": "warn", "headline": "Waiting — at the edge"},
              "checks": [{"label": "Location", "state": "pass"},
                         {"label": "Trigger", "state": "fail"},
                         {"label": "Feed", "state": "fail"}]}
        out = C.plain_verdict(st)
        self.assertEqual(out["missing"], ["Trigger", "Feed"])
        self.assertIn("2 of 3", out["detail"])
        self.assertIn("do not force", out["detail"])

    def test_all_green_still_refuses_to_predict(self):
        st = {"ok": True, "verdict": {"tone": "ok", "headline": "Conditions line up"},
              "checks": [{"label": "Location", "state": "pass"}]}
        out = C.plain_verdict(st)
        self.assertIn("coin flip", out["detail"])


class TeachingText(unittest.TestCase):
    def test_unmeasured_tools_are_declared_absent(self):
        """The panel promises these are not drawn; the constant must say so."""
        blob = " ".join(t + " " + b for t, b in C.HOW_TO_READ).lower()
        for word in ("fibonacci", "vwap", "trendline"):
            self.assertIn(word, blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
